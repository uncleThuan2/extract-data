"""Telegram bot – upload documents, ask questions, export Excel."""

from __future__ import annotations

import io
import logging
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.helpers import EXTRACTION_PROMPT_TEMPLATE, format_sources, parse_pipe_table
from config import settings
from schemas import QAResult
from services import (
    ask,
    delete_file,
    export_extracted_data,
    export_qa_history,
    get_supported_extensions_str,
    is_supported_file,
    list_indexed_files,
    process_document,
    upsert_chunks,
)

logger = logging.getLogger(__name__)

qa_history: dict[int, list[QAResult]] = defaultdict(list)
MAX_TELEGRAM_MSG = 4000


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *PDF Q&A Bot*\n\n"
        "Tôi có thể giúp bạn hỏi đáp tài liệu PDF\\!\n\n"
        "📌 *Commands:*\n"
        "/upload – Gửi file để index \(PDF, DOCX, TXT, CSV\.\.\.\)\n"
        "/ask `<câu hỏi>` – Hỏi về tài liệu\n"
        "/extract `<mô tả>` – Trích xuất data → Excel\n"
        "/export – Xuất lịch sử Q&A → Excel\n"
        "/files – Xem danh sách file đã index\n\n"
        "💡 Hoặc gửi file PDF trực tiếp để tôi index\\!",
        parse_mode="MarkdownV2",
    )


# ---------------------------------------------------------------------------
# /upload or direct file
# ---------------------------------------------------------------------------
async def upload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"📎 Gửi file cho tôi (kéo thả hoặc attach).\n"
        f"Hỗ trợ: {get_supported_extensions_str()}"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document files sent directly to the bot."""
    document = update.message.document
    if not document:
        return

    filename = document.file_name or "unknown.txt"
    if not is_supported_file(filename):
        await update.message.reply_text(
            f"⚠️ File không được hỗ trợ.\n"
            f"Hỗ trợ: {get_supported_extensions_str()}"
        )
        return

    msg = await update.message.reply_text(f"⏳ Đang xử lý {filename}...")

    try:
        tg_file = await document.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        chunks = process_document(bytes(file_bytes), filename)
        if not chunks:
            await msg.edit_text("⚠️ Không extract được text từ file này.")
            return

        count = upsert_chunks(chunks)
        await msg.edit_text(
            f"✅ {filename} đã index thành công!\n"
            f"📄 {count} chunks lưu trên Supabase.\n\n"
            f"Dùng /ask để hỏi về tài liệu."
        )
    except Exception:
        logger.exception("Error processing file %s", filename)
        await msg.edit_text("❌ Lỗi khi xử lý file. Kiểm tra logs.")


# ---------------------------------------------------------------------------
# /ask
# ---------------------------------------------------------------------------
async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text(
            "❓ Dùng: /ask <câu hỏi>\n\nVí dụ: /ask Tóm tắt nội dung chính"
        )
        return

    msg = await update.message.reply_text("🤔 Đang tìm câu trả lời...")

    try:
        result = ask(question)
        qa_history[update.effective_chat.id].append(result)

        answer = result.answer
        if len(answer) > MAX_TELEGRAM_MSG:
            answer = answer[:MAX_TELEGRAM_MSG] + "…"

        sources_str = ""
        if result.sources:
            source_lines = format_sources(result.sources)
            sources_str = "\n\n📚 Sources:\n" + "\n".join(f"• {s}" for s in source_lines)

        await msg.edit_text(f"{answer}{sources_str}")
    except Exception:
        logger.exception("Error answering question")
        await msg.edit_text("❌ Lỗi khi trả lời. Kiểm tra logs.")


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------
async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = qa_history.get(update.effective_chat.id, [])
    if not history:
        await update.message.reply_text("📭 Chưa có lịch sử Q&A. Dùng /ask trước.")
        return

    msg = await update.message.reply_text("📊 Đang tạo file Excel...")
    try:
        excel_bytes = export_qa_history(history)
        await update.message.reply_document(
            document=io.BytesIO(excel_bytes),
            filename="qa_report.xlsx",
            caption=f"📊 Exported {len(history)} Q&A entries.",
        )
        await msg.delete()
    except Exception:
        logger.exception("Error exporting Excel")
        await msg.edit_text("❌ Lỗi khi xuất Excel.")


# ---------------------------------------------------------------------------
# /extract
# ---------------------------------------------------------------------------
async def extract_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text(
            "📋 Dùng: /extract <mô tả data cần trích>\n\n"
            "Ví dụ: /extract tất cả tên công ty và địa chỉ"
        )
        return

    msg = await update.message.reply_text("⏳ Đang trích xuất data...")
    try:
        extraction_prompt = EXTRACTION_PROMPT_TEMPLATE.format(prompt=prompt)
        result = ask(extraction_prompt, top_k=10)

        headers, rows = parse_pipe_table(result.answer)
        if not rows:
            await msg.edit_text(f"📝 {result.answer}")
            return

        excel_bytes = export_extracted_data(rows, headers)
        await update.message.reply_document(
            document=io.BytesIO(excel_bytes),
            filename="extracted_data.xlsx",
            caption=f"📊 Extracted {len(rows)} rows.",
        )
        await msg.delete()
    except Exception:
        logger.exception("Error extracting data")
        await msg.edit_text("❌ Lỗi khi trích xuất data.")


# ---------------------------------------------------------------------------
# /files
# ---------------------------------------------------------------------------
async def files_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("📂 Đang tải danh sách...")
    try:
        filenames = list_indexed_files()
        if not filenames:
            await msg.edit_text("💭 Chưa có file nào. Gửi file để bắt đầu.")
            return
        lines = [f"`{i+1}.` 📄 {f}" for i, f in enumerate(filenames)]
        await msg.edit_text(
            f"*Indexed files ({len(filenames)}):*\n" + "\n".join(lines),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Error listing files")
        await msg.edit_text("❌ Lỗi khi liệt kê files.")


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------
async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filename = " ".join(context.args) if context.args else ""
    if not filename:
        await update.message.reply_text(
            "🗑 Dùng: /delete <tên file>\n\n"
            "Ví dụ: /delete report.pdf\n\n"
            "Dùng /files để xem danh sách tên file chính xác."
        )
        return

    msg = await update.message.reply_text(f"⏳ Đang xóa {filename}...")
    try:
        count = delete_file(filename)
        if count == 0:
            await msg.edit_text(
                f"⚠️ Không tìm thấy file *{filename}*.\n"
                f"Dùng /files để xem tên chính xác.",
                parse_mode="Markdown",
            )
        else:
            await msg.edit_text(
                f"✅ Đã xóa *{filename}* ({count} chunks đã xóa khỏi Supabase).",
                parse_mode="Markdown",
            )
    except Exception:
        logger.exception("Error deleting file %s", filename)
        await msg.edit_text("❌ Lỗi khi xóa file. Kiểm tra logs.")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("upload", upload_cmd))
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("extract", extract_cmd))
    app.add_handler(CommandHandler("files", files_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    # Accept all document types (filtering is done inside handle_document)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info("Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

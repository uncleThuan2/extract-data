"""Telegram bot – ask questions, export Excel."""

from __future__ import annotations

import asyncio
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
    format_storage_stats,
    get_storage_stats,
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
        r"👋 *PDF Q&A Bot*" + "\n\n"
        r"Tôi có thể giúp bạn hỏi đáp tài liệu PDF\!" + "\n\n"
        r"📌 *Commands:*" + "\n"

        r"/ask `<câu hỏi>` – Hỏi về tài liệu" + "\n"
        r"/extract `<mô tả>` – Trích xuất data → Excel" + "\n"
        r"/export – Xuất lịch sử Q&A → Excel" + "\n"
        r"/files – Xem danh sách file đã index" + "\n"
        r"/storage – Xem dung lượng Supabase hiện tại" + "\n\n"
        r"💡 Hoặc gửi file PDF trực tiếp để tôi index\!",
        parse_mode="MarkdownV2",
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

    msg = await update.message.reply_text(f"⏳ [1/3] Đang tải file {filename}...")

    try:
        tg_file = await document.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        size_kb = len(file_bytes) / 1024
        logger.info("Downloaded %s (%.0f KB)", filename, size_kb)

        await msg.edit_text(f"⏳ [2/3] Đang xử lý văn bản từ {filename}...")
        chunks = await asyncio.to_thread(process_document, bytes(file_bytes), filename)
        logger.info("Processed %d chunks from %s", len(chunks), filename)
        if not chunks:
            await msg.edit_text(
                f"⚠️ Không extract được text từ <b>{filename}</b>.\n"
                f"Đảm bảo file có nội dung văn bản (không phải ảnh scan).",
                parse_mode="HTML",
            )
            return

        await msg.edit_text(
            f"⏳ [3/3] Đang embed và lưu {len(chunks)} chunks lên Supabase...\n"
            f"⏱ File lớn có thể mất vài phút (Gemini free giới hạn 100 req/phút)."
        )
        count = await asyncio.to_thread(upsert_chunks, chunks)
        await msg.edit_text(
            f"✅ <b>{filename}</b> đã index thành công!\n"
            f"ℹ️ Kích thước: {size_kb:.0f} KB\n"
            f"📄 {count} chunks lưu trên Supabase\n\n"
            f"Dùng /ask để hỏi về tài liệu.",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Error processing file %s: %s", filename, exc)
        err_msg = str(exc)[:500]
        try:
            await msg.edit_text(
                f"❌ <b>Lỗi khi xử lý {filename}:</b>\n\n<code>{err_msg}</code>",
                parse_mode="HTML",
            )
        except Exception:
            await update.message.reply_text(
                f"❌ Lỗi: <code>{err_msg}</code>", parse_mode="HTML"
            )


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
        result = await asyncio.to_thread(ask, question)
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
        excel_bytes = await asyncio.to_thread(export_qa_history, history)
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
        result = await asyncio.to_thread(ask, extraction_prompt, 10)

        headers, rows = parse_pipe_table(result.answer)
        if not rows:
            await msg.edit_text(f"📝 {result.answer}")
            return

        excel_bytes = await asyncio.to_thread(export_extracted_data, rows, headers)
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
        filenames = await asyncio.to_thread(list_indexed_files)
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
        count = await asyncio.to_thread(delete_file, filename)
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
# /storage
# ---------------------------------------------------------------------------
async def storage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("📊 Đang kiểm tra dung lượng...")
    try:
        stats = await asyncio.to_thread(get_storage_stats)
        text = format_storage_stats(stats, bold="*")
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Error fetching storage stats")
        await msg.edit_text("❌ Lỗi khi lấy thông tin dung lượng. Kiểm tra logs.")


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
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("extract", extract_cmd))
    app.add_handler(CommandHandler("files", files_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("storage", storage_cmd))
    # Accept all document types (filtering is done inside handle_document)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info("Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

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
    list_indexed_files,
    FileAlreadyIndexedError,
    UnsupportedFileError,
    upload_file,
)

logger = logging.getLogger(__name__)

qa_history: dict[int, list[QAResult]] = defaultdict(list)
MAX_TELEGRAM_MSG = 4000


async def _safe_reply(update: Update, text: str, **kwargs) -> None:
    """Send a reply, never raising – last-resort fallback."""
    try:
        await update.message.reply_text(text, **kwargs)
    except Exception as e:
        logger.error("Failed to send reply to user: %s", e)


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
        r"💡 Gửi file PDF/DOCX/Excel trực tiếp để index\!",
        parse_mode="MarkdownV2",
    )


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick health check – confirms bot is alive and responding."""
    import platform, sys
    await update.message.reply_text(
        f"🏓 Pong!\nPython {sys.version.split()[0]} | {platform.system()}"
    )


# ---------------------------------------------------------------------------
# Document upload handler
# ---------------------------------------------------------------------------
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document files sent directly to the bot – upload to Supabase."""
    document = update.message.document
    if not document:
        return

    filename = document.file_name or "unknown"

    # Quick check: unsupported extension (no DB call needed)
    try:
        from services.document_processor import SUPPORTED_EXTENSIONS
        from pathlib import PurePath
        ext = PurePath(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            await update.message.reply_text(
                f"⚠️ File <b>{filename}</b> không được hỗ trợ.\n"
                f"Hỗ trợ: {get_supported_extensions_str()}",
                parse_mode="HTML",
            )
            return
    except Exception:
        pass

    msg = await update.message.reply_text(f"⏳ [1/3] Đang tải file <b>{filename}</b>...", parse_mode="HTML")

    try:
        # Download file bytes from Telegram
        tg_file = await document.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        size_kb = len(file_bytes) / 1024
        logger.info("Downloaded '%s' (%.0f KB)", filename, size_kb)

        await msg.edit_text(f"⏳ [2/3] Đang xử lý và kiểm tra <b>{filename}</b>...", parse_mode="HTML")

        # upload_file handles: duplicate check, text extraction, Jina embed, upsert
        count = await asyncio.to_thread(upload_file, file_bytes, filename)

        await msg.edit_text(
            f"✅ <b>{filename}</b> đã index thành công!\n"
            f"ℹ️ Kích thước: {size_kb:.0f} KB\n"
            f"📄 {count} chunks lưu trên Supabase\n\n"
            f"Dùng /ask để hỏi về tài liệu.",
            parse_mode="HTML",
        )

    except FileAlreadyIndexedError as exc:
        import html as _html
        await msg.edit_text(
            f"⚠️ <b>File đã tồn tại!</b>\n\n"
            f"{_html.escape(exc.message)}\n\n"
            f"Dùng /delete {_html.escape(filename)} nếu muốn index lại.",
            parse_mode="HTML",
        )

    except UnsupportedFileError as exc:
        import html as _html
        await msg.edit_text(
            f"⚠️ {_html.escape(str(exc))}",
            parse_mode="HTML",
        )

    except Exception as exc:
        logger.exception("Error uploading file '%s'", filename)
        import html as _html
        err = _html.escape(str(exc)[:400])
        try:
            await msg.edit_text(
                f"❌ <b>Lỗi khi xử lý {filename}:</b>\n\n<code>{err}</code>",
                parse_mode="HTML",
            )
        except Exception:
            await _safe_reply(update, f"❌ Lỗi: {str(exc)[:300]}")


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

        text = f"{answer}{sources_str}"
        try:
            await msg.edit_text(text)
        except Exception:
            await update.message.reply_text(text)
    except Exception:
        logger.exception("Error answering question")
        try:
            await msg.edit_text("❌ Lỗi khi trả lời. Kiểm tra logs.")
        except Exception:
            await update.message.reply_text("❌ Lỗi khi trả lời.")


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------
async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    logger.info("CMD /export called by chat_id=%s", chat_id)
    msg = None
    try:
        history = qa_history.get(update.effective_chat.id, [])
        logger.info("CMD /export history_len=%d for chat_id=%s", len(history), chat_id)
        if not history:
            await _safe_reply(update,
                "📭 Chưa có lịch sử Q&A.\n\n"
                "Dùng /ask <câu hỏi> trước, rồi /export để xuất Excel."
            )
            return

        msg = await update.message.reply_text("📊 Đang tạo file Excel...")
        excel_bytes = await asyncio.to_thread(export_qa_history, history)
        await update.message.reply_document(
            document=io.BytesIO(excel_bytes),
            filename="qa_report.xlsx",
            caption=f"📊 Exported {len(history)} Q&A entries.",
        )
        try:
            await msg.edit_text(f"✅ Xuất xong – {len(history)} Q&A entries.")
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Error exporting Excel")
        err = str(exc)[:300]
        text = f"❌ Lỗi khi xuất Excel:\n<code>{err}</code>"
        if msg:
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                await _safe_reply(update, f"❌ Lỗi: {err}")
        else:
            await _safe_reply(update, f"❌ Lỗi: {err}")


# ---------------------------------------------------------------------------
# /extract
# ---------------------------------------------------------------------------
async def extract_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    logger.info("CMD /extract called by chat_id=%s args=%s", chat_id, context.args)

    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await _safe_reply(update,
            "📋 Dùng: /extract <mô tả data cần trích>\n\n"
            "Ví dụ: /extract tất cả tên công ty và địa chỉ"
        )
        return

    # Send loading message first – guaranteed before any heavy work
    msg = None
    try:
        msg = await update.message.reply_text("⏳ Đang trích xuất data (có thể mất 15-30s)...")
    except Exception as e:
        logger.error("extract_cmd: failed to send loading message: %s", e)

    try:
        extraction_prompt = EXTRACTION_PROMPT_TEMPLATE.format(prompt=prompt)
        result = await asyncio.to_thread(ask, extraction_prompt, 5)
        logger.info("CMD /extract got answer len=%d", len(result.answer))

        headers, rows = parse_pipe_table(result.answer)
        logger.info("CMD /extract parsed rows=%d headers=%s", len(rows), headers)

        if not rows:
            import html as _html
            text = f"📝 {_html.escape(result.answer[:MAX_TELEGRAM_MSG])}"
            if msg:
                try:
                    await msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    await _safe_reply(update, result.answer[:MAX_TELEGRAM_MSG])
            else:
                await _safe_reply(update, result.answer[:MAX_TELEGRAM_MSG])
            return

        excel_bytes = await asyncio.to_thread(export_extracted_data, rows, headers)
        await update.message.reply_document(
            document=io.BytesIO(excel_bytes),
            filename="extracted_data.xlsx",
            caption=f"📊 Extracted {len(rows)} rows.",
        )
        if msg:
            try:
                await msg.edit_text(f"✅ Trích xuất xong – {len(rows)} dòng dữ liệu.")
            except Exception:
                pass

    except Exception as exc:
        logger.exception("Error extracting data")
        err = str(exc)[:300]
        import html as _html
        text = f"❌ Lỗi khi trích xuất data:\n<code>{_html.escape(err)}</code>"
        if msg:
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                await _safe_reply(update, f"❌ Lỗi: {err}")
        else:
            await _safe_reply(update, f"❌ Lỗi: {err}")


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
        import html
        lines = [f"{i+1}. 📄 {html.escape(f)}" for i, f in enumerate(filenames)]
        text = f"<b>Indexed files ({len(filenames)}):</b>\n" + "\n".join(lines)
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            await msg.edit_text(f"Indexed files ({len(filenames)}):\n" + "\n".join(lines))
    except Exception:
        logger.exception("Error listing files")
        try:
            await msg.edit_text("❌ Lỗi khi liệt kê files.")
        except Exception:
            await update.message.reply_text("❌ Lỗi khi liệt kê files.")


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
        import html
        safe_name = html.escape(filename)
        if count == 0:
            text = f"⚠️ Không tìm thấy file <b>{safe_name}</b>.\nDùng /files để xem tên chính xác."
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                await update.message.reply_text(f"⚠️ Không tìm thấy file {filename}.")
        else:
            text = f"✅ Đã xóa <b>{safe_name}</b> ({count} chunks đã xóa khỏi Supabase)."
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                await update.message.reply_text(f"✅ Đã xóa {filename} ({count} chunks).")
    except Exception:
        logger.exception("Error deleting file %s", filename)
        try:
            await msg.edit_text("❌ Lỗi khi xóa file. Kiểm tra logs.")
        except Exception:
            await update.message.reply_text("❌ Lỗi khi xóa file.")


# ---------------------------------------------------------------------------
# /storage
# ---------------------------------------------------------------------------
async def storage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = None
    try:
        msg = await update.message.reply_text("📊 Đang kiểm tra dung lượng...")
        stats = await asyncio.to_thread(get_storage_stats)
        text = format_storage_stats(stats, bold="b")
        try:
            await msg.edit_text(text, parse_mode="HTML")
        except Exception:
            plain = format_storage_stats(stats, bold="")
            try:
                await msg.edit_text(plain)
            except Exception:
                await _safe_reply(update, plain)
    except Exception as exc:
        logger.exception("Error fetching storage stats")
        err = str(exc)[:300]
        text = f"❌ Lỗi khi lấy dung lượng:\n<code>{err}</code>"
        if msg:
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                await _safe_reply(update, f"❌ Lỗi: {err}")
        else:
            await _safe_reply(update, f"❌ Lỗi: {err}")


# ---------------------------------------------------------------------------
# Global error handler
# ---------------------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch all unhandled exceptions and notify the user."""
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        err = str(context.error)[:300]
        await _safe_reply(update, f"❌ Lỗi không mong muốn:\n{err}")


# Map command text → handler function (for CODE-entity fallback)
_COMMAND_MAP: dict[str, any] = {}  # populated after functions are defined


async def _handle_code_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback: handle messages where Telegram sent a command with CODE entity
    instead of BOT_COMMAND (happens when user taps a copied code block)."""
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip()
    if not text.startswith("/"):
        return
    # Extract command and args
    parts = text.split(maxsplit=1)
    cmd = parts[0].lstrip("/").lower().split("@")[0]  # strip @botname
    context.args = parts[1].split() if len(parts) > 1 else []
    handler_fn = _COMMAND_MAP.get(cmd)
    if handler_fn:
        logger.info("CODE-entity command re-routed: /%s args=%s", cmd, context.args)
        await handler_fn(update, context)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Populate CODE-entity fallback map
    _COMMAND_MAP.update({
        "start": start_cmd, "help": start_cmd, "ping": ping_cmd,
        "ask": ask_cmd, "export": export_cmd, "extract": extract_cmd,
        "files": files_cmd, "delete": delete_cmd, "storage": storage_cmd,
    })

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("ask", ask_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("extract", extract_cmd))
    app.add_handler(CommandHandler("files", files_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("storage", storage_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    # Fallback: handle commands that Telegram sent with CODE entity instead of BOT_COMMAND
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_code_commands))
    app.add_error_handler(error_handler)

    logger.info("Telegram bot starting...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
    )


if __name__ == "__main__":
    main()

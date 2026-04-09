"""Discord bot – upload documents, ask questions, export Excel."""

from __future__ import annotations

import io
import logging
from collections import defaultdict

import discord
from discord import app_commands

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

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

qa_history: dict[int, list[QAResult]] = defaultdict(list)
MAX_DISCORD_MSG = 1900


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@bot.event
async def on_ready() -> None:
    await tree.sync()
    logger.info("Bot ready as %s – slash commands synced", bot.user)


# ---------------------------------------------------------------------------
# /upload
# ---------------------------------------------------------------------------
@tree.command(name="upload", description="Upload a document to index for Q&A")
@app_commands.describe(file="The file to upload (PDF, DOCX, TXT, CSV, XLSX, etc.)")
async def upload_cmd(interaction: discord.Interaction, file: discord.Attachment) -> None:
    if not is_supported_file(file.filename):
        await interaction.response.send_message(
            f"⚠️ Unsupported file type.\n"
            f"Supported: {get_supported_extensions_str()}",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        file_bytes = await file.read()
        chunks = process_document(file_bytes, file.filename)
        if not chunks:
            await interaction.followup.send("⚠️ Could not extract text from this file.")
            return

        count = upsert_chunks(chunks)
        await interaction.followup.send(
            f"✅ **{file.filename}** indexed successfully!\n"
            f"📄 {count} chunks stored in Supabase.\n"
            f"Now ask me anything with `/ask`."
        )
    except Exception:
        logger.exception("Error processing file %s", file.filename)
        await interaction.followup.send("❌ Error processing file. Check logs.")


# ---------------------------------------------------------------------------
# /ask
# ---------------------------------------------------------------------------
@tree.command(name="ask", description="Ask a question about uploaded PDFs")
@app_commands.describe(question="Your question about the documents")
async def ask_cmd(interaction: discord.Interaction, question: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        result = ask(question)
        qa_history[interaction.channel_id].append(result)

        answer = result.answer
        if len(answer) > MAX_DISCORD_MSG:
            answer = answer[:MAX_DISCORD_MSG] + "…"

        sources_str = ""
        if result.sources:
            source_lines = format_sources(result.sources)
            sources_str = "\n📚 **Sources:**\n" + "\n".join(f"• {s}" for s in source_lines)

        await interaction.followup.send(f"{answer}\n{sources_str}")
    except Exception:
        logger.exception("Error answering question")
        await interaction.followup.send("❌ Error answering question. Check logs.")


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------
@tree.command(name="export", description="Export Q&A history of this channel as Excel")
async def export_cmd(interaction: discord.Interaction) -> None:
    history = qa_history.get(interaction.channel_id, [])
    if not history:
        await interaction.response.send_message(
            "📭 No Q&A history in this channel yet. Use `/ask` first.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    try:
        excel_bytes = export_qa_history(history)
        file = discord.File(io.BytesIO(excel_bytes), filename="qa_report.xlsx")
        await interaction.followup.send(
            f"📊 Exported **{len(history)}** Q&A entries.", file=file
        )
    except Exception:
        logger.exception("Error exporting Excel")
        await interaction.followup.send("❌ Error exporting Excel. Check logs.")


# ---------------------------------------------------------------------------
# /extract
# ---------------------------------------------------------------------------
@tree.command(
    name="extract",
    description="Extract structured data from PDFs and export as Excel",
)
@app_commands.describe(
    prompt="Describe what data to extract (e.g., 'all company names and addresses')"
)
async def extract_cmd(interaction: discord.Interaction, prompt: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        extraction_prompt = EXTRACTION_PROMPT_TEMPLATE.format(prompt=prompt)
        result = ask(extraction_prompt, top_k=10)

        headers, rows = parse_pipe_table(result.answer)
        if not rows:
            await interaction.followup.send(f"📝 {result.answer}")
            return

        excel_bytes = export_extracted_data(rows, headers)
        file = discord.File(io.BytesIO(excel_bytes), filename="extracted_data.xlsx")
        await interaction.followup.send(
            f"📊 Extracted **{len(rows)}** rows.", file=file
        )
    except Exception:
        logger.exception("Error extracting data")
        await interaction.followup.send("❌ Error extracting data. Check logs.")


# ---------------------------------------------------------------------------
# /files
# ---------------------------------------------------------------------------
@tree.command(name="files", description="List all indexed files")
async def files_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        filenames = list_indexed_files()
        if not filenames:
            await interaction.followup.send("💭 No files indexed yet. Use `/upload`.")
            return
        lines = [f"`{i+1}.` 📄 {f}" for i, f in enumerate(filenames)]
        await interaction.followup.send(
            f"**Indexed files ({len(filenames)}):**\n" + "\n".join(lines)
        )
    except Exception:
        logger.exception("Error listing files")
        await interaction.followup.send("❌ Error listing files.")


# ---------------------------------------------------------------------------
# /delete
# ---------------------------------------------------------------------------
@tree.command(name="delete", description="Delete a file from the vector store by name")
@app_commands.describe(filename="Exact filename to delete (use /files to see names)")
async def delete_cmd(interaction: discord.Interaction, filename: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        count = delete_file(filename)
        if count == 0:
            await interaction.followup.send(
                f"⚠️ File **{filename}** not found. Use `/files` to see available names."
            )
        else:
            await interaction.followup.send(
                f"✅ Deleted **{filename}** ({count} chunks removed from Supabase)."
            )
    except Exception:
        logger.exception("Error deleting file %s", filename)
        await interaction.followup.send("❌ Error deleting file. Check logs.")


# ---------------------------------------------------------------------------
# /storage
# ---------------------------------------------------------------------------
@tree.command(name="storage", description="Show current Supabase storage usage")
async def storage_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        stats = get_storage_stats()
        msg = format_storage_stats(stats, bold="**")
        await interaction.followup.send(msg)
    except Exception:
        logger.exception("Error fetching storage stats")
        await interaction.followup.send("❌ Error fetching storage stats. Check logs.")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    bot.run(settings.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()

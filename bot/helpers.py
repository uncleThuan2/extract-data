"""Shared helpers for bot modules (Discord & Telegram)."""

from __future__ import annotations


def format_sources(sources: list[dict]) -> list[str]:
    """Deduplicate and format source references."""
    seen: set[str] = set()
    lines: list[str] = []
    for s in sources:
        key = f"{s['filename']} p.{s['page_number']}"
        if key not in seen:
            lines.append(key)
            seen.add(key)
    return lines


def parse_pipe_table(text: str) -> tuple[list[str], list[dict]]:
    """Parse LLM pipe-separated response into header + rows.

    Returns (headers, rows) where rows is a list of dicts.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return [], []

    headers = [h.strip() for h in lines[0].split("|") if h.strip()]
    rows: list[dict] = []
    for line in lines[1:]:
        clean = line.lstrip("0123456789.-) ").strip()
        parts = [p.strip() for p in clean.split("|") if p.strip()]
        if len(parts) >= len(headers):
            rows.append(dict(zip(headers, parts)))
    return headers, rows


EXTRACTION_PROMPT_TEMPLATE = (
    "Extract the following data from the documents and format as a "
    "structured list. Each item should have clear fields.\n\n"
    "Data to extract: {prompt}\n\n"
    "Format your response as a numbered list with consistent fields "
    "separated by ' | ' (pipe). First line should be the header."
)

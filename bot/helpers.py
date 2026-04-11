"""Shared helpers for the Telegram bot."""

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


def _strip_md(text: str) -> str:
    """Remove markdown bold/italic markers from a string."""
    return text.replace("**", "").replace("__", "").replace("*", "").replace("_", "").strip()


def parse_pipe_table(text: str) -> tuple[list[str], list[dict]]:
    """Parse LLM pipe-separated response into header + rows.

    Handles:
    - Markdown bold (**header**) in headers and cells
    - Section title lines without pipes (skipped)
    - Separator lines (--- | --- | ---)
    - Numbered rows (1. col | col | col)

    Returns (headers, rows) where rows is a list of dicts.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # Find the first line that actually contains a pipe – that is the header
    header_idx = -1
    for i, line in enumerate(lines):
        if "|" in line:
            header_idx = i
            break

    if header_idx == -1:
        return [], []

    raw_headers = [_strip_md(h) for h in lines[header_idx].split("|") if h.strip()]
    headers = [h for h in raw_headers if h]  # drop empty after stripping

    if not headers:
        return [], []

    rows: list[dict] = []
    for line in lines[header_idx + 1:]:
        # Skip separator lines like "--- | --- | ---"
        if set(line.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue
        if all(c in "-|: " for c in line):
            continue
        # Strip leading numbering:  "1." / "1)" / "-"
        clean = line.lstrip("0123456789.-) ").strip()
        parts = [_strip_md(p) for p in clean.split("|") if p.strip()]
        if not parts:
            continue
        # Only include rows that have at least as many parts as headers
        # Pad with empty strings if slightly short
        while len(parts) < len(headers):
            parts.append("")
        rows.append(dict(zip(headers, parts)))
    return headers, rows


EXTRACTION_PROMPT_TEMPLATE = (
    "Extract the following data from the documents.\n\n"
    "Data to extract: {prompt}\n\n"
    "Rules:\n"
    "- Output ONLY a pipe-separated table, no other text before or after\n"
    "- First line must be the column headers separated by | (example: Name | Value | Unit)\n"
    "- Each subsequent line is one data row, values separated by |\n"
    "- Do NOT use markdown bold (**), do NOT number the rows\n"
    "- If a field is unknown write N/A\n"
    "- Example output format:\n"
    "  Field | Description | Type\n"
    "  Health status | Self-reported health scale | Scale\n"
    "  Age | Age in years | Numeric"
)

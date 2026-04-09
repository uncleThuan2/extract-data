"""Data models for the PDF Q&A system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocumentChunk:
    """A chunk of text extracted from a PDF document."""

    text: str
    metadata: dict
    chunk_id: str


@dataclass
class QAResult:
    """Result of a question-answering query."""

    answer: str
    sources: list[dict] = field(default_factory=list)
    query: str = ""

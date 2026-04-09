"""RAG-based Question Answering service."""

from __future__ import annotations

import logging

from config import settings
from schemas import QAResult
from services.ai_client import get_chat_fn
from services.vector_store import search_similar

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided document context.

Rules:
- Answer ONLY based on the provided context. If the context doesn't contain enough info, say so.
- Cite the source page numbers when possible (e.g., "Theo trang 5, ...").
- Answer in the same language as the question.
- Be concise but thorough.
- If asked to extract structured data (tables, lists), format it clearly."""


def ask(question: str, top_k: int = 5) -> QAResult:
    """Answer a question using RAG: retrieve relevant chunks → ask LLM."""
    relevant_docs = search_similar(question, top_k=top_k)

    if not relevant_docs:
        return QAResult(
            answer="Không tìm thấy tài liệu nào liên quan. Hãy upload PDF trước.",
            sources=[],
            query=question,
        )

    context_parts = [
        f"[File: {doc['filename']}, Trang {doc['page_number']}]\n{doc['text']}"
        for doc in relevant_docs
    ]
    context = "\n\n---\n\n".join(context_parts)

    chat_fn = get_chat_fn()
    answer = chat_fn(
        system=SYSTEM_PROMPT,
        user=f"Context from documents:\n\n{context}\n\n---\n\nQuestion: {question}",
    ) or "Không thể trả lời."

    return QAResult(
        answer=answer,
        sources=relevant_docs,
        query=question,
    )

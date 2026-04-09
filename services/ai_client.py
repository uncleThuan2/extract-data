"""Unified AI client – supports OpenAI, Google Gemini, GitHub Copilot, and Jina AI.

Chat provider → set AI_PROVIDER in .env:
  AI_PROVIDER=openai    → uses OPENAI_API_KEY
  AI_PROVIDER=gemini    → uses GEMINI_API_KEY (free)
  AI_PROVIDER=copilot   → uses GITHUB_TOKEN

Embed provider → set EMBED_PROVIDER (optional, defaults to AI_PROVIDER):
  EMBED_PROVIDER=jina   → uses JINA_API_KEY (free 1M tokens/month, no RPM limit)

Recommended combo: AI_PROVIDER=gemini + EMBED_PROVIDER=jina
"""

from __future__ import annotations

import logging
import re
import time
from typing import Protocol

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol – shared interface both providers implement
# ---------------------------------------------------------------------------

class EmbedFn(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class ChatFn(Protocol):
    def __call__(self, system: str, user: str) -> str: ...


# ---------------------------------------------------------------------------
# OpenAI implementation
# ---------------------------------------------------------------------------

def _openai_embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _openai_chat(system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Gemini implementation  (google-genai SDK ≥ 1.0)
# gemini-embedding-001 default output = 3072 dims.
# We pin output_dimensionality to EMBEDDING_DIMENSION so it matches
# whatever dimension the Supabase collection was created with.
# embed_content accepts a list of strings → batched in one call (max 100).
# Free tier: 100 requests/min → retry with server-suggested wait on 429.
# ---------------------------------------------------------------------------

_GEMINI_EMBED_BATCH = 100   # max items per embed_content call
_GEMINI_MAX_RETRIES = 5
_GEMINI_RETRY_DEFAULT = 35  # seconds to wait if not specified in error


def _parse_retry_after(exc: Exception) -> float:
    """Extract 'retry in X.Xs' from Gemini 429 error message."""
    match = re.search(r"retry in ([\d.]+)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1.0  # +1s buffer
    return _GEMINI_RETRY_DEFAULT


def _gemini_embed(texts: list[str]) -> list[list[float]]:
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.EmbedContentConfig(
        output_dimensionality=settings.EMBEDDING_DIMENSION,
    )
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), _GEMINI_EMBED_BATCH):
        batch = texts[i : i + _GEMINI_EMBED_BATCH]
        for attempt in range(1, _GEMINI_MAX_RETRIES + 1):
            try:
                response = client.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=batch,
                    config=config,
                )
                embeddings.extend(e.values for e in response.embeddings)
                break
            except ClientError as exc:
                if exc.code == 429 and attempt < _GEMINI_MAX_RETRIES:
                    wait = _parse_retry_after(exc)
                    logger.warning(
                        "Gemini rate limit hit (batch %d/%d). Waiting %.0fs before retry %d/%d...",
                        i // _GEMINI_EMBED_BATCH + 1,
                        (len(texts) - 1) // _GEMINI_EMBED_BATCH + 1,
                        wait,
                        attempt,
                        _GEMINI_MAX_RETRIES,
                    )
                    time.sleep(wait)
                else:
                    raise
    return embeddings


def _gemini_chat(system: str, user: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=settings.LLM_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            max_output_tokens=2000,
        ),
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Jina AI embedding  (OpenAI-compatible, free 1M tokens/month, no RPM limit)
# Docs: https://jina.ai/embeddings
# ---------------------------------------------------------------------------

_JINA_BASE_URL = "https://api.jina.ai/v1"
_JINA_EMBED_BATCH = 2048  # max items per call


def _jina_embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.JINA_API_KEY, base_url=_JINA_BASE_URL)
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), _JINA_EMBED_BATCH):
        batch = texts[i : i + _JINA_EMBED_BATCH]
        response = client.embeddings.create(
            model=settings.JINA_EMBEDDING_MODEL,
            input=batch,
            extra_body={"dimensions": settings.EMBEDDING_DIMENSION},
        )
        embeddings.extend(item.embedding for item in response.data)
    return embeddings


# ---------------------------------------------------------------------------
# GitHub Copilot implementation (GitHub Models API – OpenAI-compatible)
# Docs: https://docs.github.com/en/github-models
# ---------------------------------------------------------------------------

_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"


def _copilot_embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.GITHUB_TOKEN,
        base_url=_GITHUB_MODELS_BASE_URL,
    )
    response = client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _copilot_chat(system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.GITHUB_TOKEN,
        base_url=_GITHUB_MODELS_BASE_URL,
    )
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Factory – returns the right functions based on AI_PROVIDER
# ---------------------------------------------------------------------------

def get_embed_fn() -> EmbedFn:
    provider = settings.effective_embed_provider
    if provider == "jina":
        logger.debug("Using Jina AI embedding (%s, %d dims)", settings.JINA_EMBEDDING_MODEL, settings.EMBEDDING_DIMENSION)
        return _jina_embed
    if provider == "gemini":
        logger.debug("Using Gemini embedding (%s)", settings.GEMINI_EMBEDDING_MODEL)
        return _gemini_embed
    if provider == "copilot":
        logger.debug("Using GitHub Copilot embedding (%s)", settings.EMBEDDING_MODEL)
        return _copilot_embed
    logger.debug("Using OpenAI embedding (%s)", settings.EMBEDDING_MODEL)
    return _openai_embed


def get_chat_fn() -> ChatFn:
    provider = settings.AI_PROVIDER
    if provider == "gemini":
        logger.debug("Using Gemini chat (%s)", settings.LLM_MODEL)
        return _gemini_chat
    if provider == "copilot":
        logger.debug("Using GitHub Copilot chat (%s)", settings.LLM_MODEL)
        return _copilot_chat
    logger.debug("Using OpenAI chat (%s)", settings.LLM_MODEL)
    return _openai_chat

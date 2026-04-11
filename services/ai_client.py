"""Unified AI client with multi-provider fallback.

Embedding: Jina AI only (free, no RPM limit, 1M tokens/month).

Chat providers with auto-fallback (set CHAT_PROVIDERS in .env):
  groq    → GROQ_API_KEY,   model: GROQ_LLM_MODEL    (default: llama-3.1-8b-instant)
  gemini  → GEMINI_API_KEY, model: GEMINI_LLM_MODEL  (default: gemini-2.0-flash-lite)
  openai  → OPENAI_API_KEY, model: OPENAI_LLM_MODEL  (default: gpt-4o-mini)
  copilot → GITHUB_TOKEN,   model: COPILOT_LLM_MODEL (default: gpt-4o-mini)

Example .env:
  CHAT_PROVIDERS=groq,gemini
  GROQ_API_KEY=...
  GEMINI_API_KEY=...
  EMBED_PROVIDER=jina
  JINA_API_KEY=...
"""

from __future__ import annotations

import logging
import re
import time
from typing import Protocol

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class EmbedFn(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class ChatFn(Protocol):
    def __call__(self, system: str, user: str) -> str: ...


# ---------------------------------------------------------------------------
# Quota / rate-limit helpers
# ---------------------------------------------------------------------------

def _is_quota_exhausted(exc: Exception) -> bool:
    """Return True if the error means daily quota is gone (not just RPM throttle)."""
    msg = str(exc)
    return (
        "limit: 0" in msg
        or "PerDay" in msg
        or ("per day" in msg.lower() and "rate limit" in msg.lower())
        or ("day" in msg.lower() and "quota" in msg.lower())
    )


def _parse_retry_after(exc: Exception, default: float = 35.0) -> float:
    match = re.search(r"retry in ([\d.]+)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1.0
    return default


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_exhausted_providers: set[str] = set()
_gemini_key_index: int = 0
_MAX_RETRIES = 4


def _current_gemini_key() -> str:
    keys = settings.gemini_api_keys
    if not keys:
        raise ValueError("No GEMINI_API_KEY configured.")
    return keys[min(_gemini_key_index, len(keys) - 1)]


def _rotate_gemini_key() -> bool:
    global _gemini_key_index
    keys = settings.gemini_api_keys
    _gemini_key_index += 1
    if _gemini_key_index < len(keys):
        logger.warning("Rotating to Gemini API key #%d/%d", _gemini_key_index + 1, len(keys))
        return True
    logger.warning("All %d Gemini API key(s) exhausted.", len(keys))
    _gemini_key_index = len(keys) - 1
    return False


# ---------------------------------------------------------------------------
# Chat implementations (one per provider)
# ---------------------------------------------------------------------------

def _chat_groq(system: str, user: str) -> str:
    from openai import OpenAI, RateLimitError

    client = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=settings.GROQ_LLM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1,
                max_tokens=2000,
            )
            return resp.choices[0].message.content or ""
        except RateLimitError as exc:
            if _is_quota_exhausted(exc):
                raise
            if attempt < _MAX_RETRIES:
                wait = _parse_retry_after(exc, default=60.0)
                logger.warning("Groq RPM limit. Waiting %.0fs (retry %d/%d)...", wait, attempt, _MAX_RETRIES)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Groq chat failed after all retries")


def _chat_gemini(system: str, user: str) -> str:
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            client = genai.Client(api_key=_current_gemini_key())
            resp = client.models.generate_content(
                model=settings.GEMINI_LLM_MODEL,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )
            return resp.text or ""
        except ClientError as exc:
            if exc.code != 429:
                raise
            if _is_quota_exhausted(exc):
                if _rotate_gemini_key():
                    continue
                raise
            if attempt < _MAX_RETRIES:
                wait = _parse_retry_after(exc)
                logger.warning("Gemini RPM limit. Waiting %.0fs (retry %d/%d)...", wait, attempt, _MAX_RETRIES)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini chat failed after all retries")


def _chat_openai(system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=settings.OPENAI_LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _chat_copilot(system: str, user: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.GITHUB_TOKEN, base_url="https://models.inference.ai.azure.com")
    resp = client.chat.completions.create(
        model=settings.COPILOT_LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


_CHAT_DISPATCH: dict[str, ChatFn] = {
    "groq": _chat_groq,
    "gemini": _chat_gemini,
    "openai": _chat_openai,
    "copilot": _chat_copilot,
}


# ---------------------------------------------------------------------------
# Chat with automatic fallback across providers
# ---------------------------------------------------------------------------

def chat_with_fallback(system: str, user: str) -> str:
    """Try each provider in CHAT_PROVIDERS order. Falls back on daily quota exhaustion."""
    providers = settings.chat_providers
    last_exc: Exception | None = None

    for provider in providers:
        if provider in _exhausted_providers:
            logger.debug("Skipping exhausted provider: %s", provider)
            continue

        fn = _CHAT_DISPATCH.get(provider)
        if fn is None:
            logger.warning("Unknown chat provider '%s', skipping.", provider)
            continue

        try:
            logger.debug("Trying chat provider: %s", provider)
            return fn(system, user)
        except Exception as exc:
            if _is_quota_exhausted(exc):
                logger.warning("Provider '%s' daily quota exhausted – switching to next.", provider)
                _exhausted_providers.add(provider)
                last_exc = exc
            else:
                raise

    raise RuntimeError(
        f"All chat providers exhausted: {providers}. Last error: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Embedding – Jina AI only
# ---------------------------------------------------------------------------

def _embed_jina(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.JINA_API_KEY, base_url="https://api.jina.ai/v1")
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), 2048):
        batch = texts[i : i + 2048]
        resp = client.embeddings.create(
            model=settings.JINA_EMBEDDING_MODEL,
            input=batch,
            extra_body={"dimensions": settings.EMBEDDING_DIMENSION},
        )
        embeddings.extend(item.embedding for item in resp.data)
    return embeddings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embed_fn() -> EmbedFn:
    logger.debug("Embed: Jina (%s, %d dims)", settings.JINA_EMBEDDING_MODEL, settings.EMBEDDING_DIMENSION)
    return _embed_jina


def get_chat_fn() -> ChatFn:
    logger.debug("Chat providers (ordered): %s", settings.chat_providers)
    return chat_with_fallback

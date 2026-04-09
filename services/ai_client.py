"""Unified AI client – supports OpenAI, Google Gemini, and GitHub Copilot.

Switch provider via AI_PROVIDER in .env:
  AI_PROVIDER=openai    → uses OPENAI_API_KEY
  AI_PROVIDER=gemini    → uses GEMINI_API_KEY (free tier)
  AI_PROVIDER=copilot   → uses GITHUB_TOKEN (GitHub Copilot subscribers, free)
"""

from __future__ import annotations

import logging
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
# text-embedding-004 is only available on v1beta – use SDK default (v1beta)
# embedContent accepts ONE content at a time → loop over texts
# ---------------------------------------------------------------------------

def _gemini_embed(texts: list[str]) -> list[list[float]]:
    from google import genai

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    embeddings = []
    for text in texts:
        response = client.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=text,
        )
        embeddings.append(response.embeddings[0].values)
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
    provider = settings.AI_PROVIDER
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

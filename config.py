import os

from dotenv import load_dotenv

load_dotenv()

_VALID_PROVIDERS = ("openai", "gemini", "copilot", "groq")
_VALID_EMBED_PROVIDERS = ("openai", "gemini", "copilot", "jina")


class Settings:
    # --- Ordered fallback chain for chat providers ---
    # Example: CHAT_PROVIDERS=groq,gemini,openai
    # When a provider hits daily quota, automatically falls back to the next.
    @property
    def chat_providers(self) -> list[str]:
        raw = os.getenv("CHAT_PROVIDERS", "groq").strip()
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    # --- Embedding provider: always Jina ---
    EMBED_PROVIDER: str = "jina"

    # --- OpenAI ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_LLM_MODEL: str = os.getenv("OPENAI_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini"))

    # --- Google Gemini ---
    # Supports multiple keys for rotation: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3...
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_LLM_MODEL: str = os.getenv("GEMINI_LLM_MODEL", os.getenv("LLM_MODEL", "gemini-2.0-flash-lite"))
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    @property
    def gemini_api_keys(self) -> list[str]:
        """Return all configured Gemini API keys (for rotation)."""
        keys = []
        if self.GEMINI_API_KEY:
            keys.append(self.GEMINI_API_KEY)
        i = 2
        while True:
            key = os.getenv(f"GEMINI_API_KEY_{i}", "")
            if not key:
                break
            keys.append(key)
            i += 1
        return keys

    # --- Groq (free tier: https://console.groq.com) ---
    # 14,400 req/day for llama-3.1-8b-instant, no credit card required
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_LLM_MODEL: str = os.getenv("GROQ_LLM_MODEL", os.getenv("LLM_MODEL", "llama-3.1-8b-instant"))

    # --- GitHub Copilot (GitHub Models API) ---
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    COPILOT_LLM_MODEL: str = os.getenv("COPILOT_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini"))

    # --- Jina AI (free embedding, no RPM limit, 1M tokens/month) ---
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")
    JINA_EMBEDDING_MODEL: str = os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3")

    # --- Bot Token ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # --- Supabase ---
    SUPABASE_URL: str = os.environ["SUPABASE_URL"]
    SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
    SUPABASE_DB_URL: str = os.environ["SUPABASE_DB_URL"]

    # --- Legacy single LLM_MODEL (kept for backward compat) ---
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))

    # jina-embeddings-v3      = 1024 dims (or set lower via EMBEDDING_DIMENSION)
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    COLLECTION_NAME: str = "pdf_documents"


settings = Settings()

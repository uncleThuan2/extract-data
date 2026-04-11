import os

from dotenv import load_dotenv

load_dotenv()

_VALID_PROVIDERS = ("openai", "gemini", "copilot")
_VALID_EMBED_PROVIDERS = ("openai", "gemini", "copilot", "jina")


class Settings:
    # --- AI Provider for CHAT: "openai", "gemini", or "copilot" ---
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "openai").lower()

    # --- Embedding provider (defaults to AI_PROVIDER if not set) ---
    # Set EMBED_PROVIDER=jina to use Jina AI for fast free embeddings
    # while keeping AI_PROVIDER=gemini for chat.
    EMBED_PROVIDER: str = os.getenv("EMBED_PROVIDER", "").lower()

    @property
    def effective_embed_provider(self) -> str:
        return self.EMBED_PROVIDER or self.AI_PROVIDER

    # --- OpenAI ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # --- Google Gemini ---
    # Supports multiple keys for rotation: GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3...
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
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

    # --- Jina AI (free embedding, no RPM limit, 1M tokens/month) ---
    # Get free key at: https://jina.ai/embeddings
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")
    JINA_EMBEDDING_MODEL: str = os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3")

    # --- GitHub Copilot (GitHub Models API) ---
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # --- Bot Token ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # --- Supabase ---
    SUPABASE_URL: str = os.environ["SUPABASE_URL"]
    SUPABASE_KEY: str = os.environ["SUPABASE_KEY"]
    SUPABASE_DB_URL: str = os.environ["SUPABASE_DB_URL"]

    # --- LLM / Embedding models ---
    # OpenAI defaults
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))

    # text-embedding-3-small = 1536 dims (OpenAI & Copilot)
    # gemini-embedding-001    = 768 dims (pinned via output_dimensionality)
    # jina-embeddings-v3      = 1024 dims (or set lower via EMBEDDING_DIMENSION)
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    COLLECTION_NAME: str = "pdf_documents"

    def __post_init__(self) -> None:
        if self.AI_PROVIDER not in _VALID_PROVIDERS:
            raise ValueError(
                f"AI_PROVIDER must be one of {_VALID_PROVIDERS}, got '{self.AI_PROVIDER}'"
            )


settings = Settings()

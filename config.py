import os

from dotenv import load_dotenv

load_dotenv()

_VALID_PROVIDERS = ("openai", "gemini", "copilot")


class Settings:
    # --- AI Provider: "openai", "gemini", or "copilot" ---
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "openai").lower()

    # --- OpenAI ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # --- Google Gemini ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    # --- GitHub Copilot (GitHub Models API) ---
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # --- Bot Tokens ---
    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
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
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    COLLECTION_NAME: str = "pdf_documents"

    def __post_init__(self) -> None:
        if self.AI_PROVIDER not in _VALID_PROVIDERS:
            raise ValueError(
                f"AI_PROVIDER must be one of {_VALID_PROVIDERS}, got '{self.AI_PROVIDER}'"
            )


settings = Settings()

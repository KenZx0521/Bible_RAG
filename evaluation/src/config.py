"""
Configuration management - reads from ../.env
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Evaluation LLM Provider: claude | openai | gemini | ollama
    eval_llm_provider: str = "claude"

    # Anthropic
    anthropic_api_key: str = ""
    eval_claude_model: str = "claude-haiku-4-5"

    # OpenAI
    openai_api_key: str = ""
    eval_openai_model: str = "gpt-4o-mini"

    # Gemini (Google)
    google_api_key: str = ""
    eval_gemini_model: str = "gemini-2.0-flash"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    eval_ollama_model: str = "gemma3:4b"

    # LLM generation settings
    llm_max_tokens: int = 10000
    llm_temperature: float = 0.1

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bible_rag"
    postgres_user: str = "bible"
    postgres_password: str = "bible_password"

    # Backend RAG API
    backend_url: str = "http://localhost:8000"

    # Evaluation settings
    top_k: int = 5
    request_delay: float = 1.5
    batch_size: int = 5

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()

"""
Configuration management - reads from ../.env
"""

from pathlib import Path
from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
_EVAL_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Run mode state: set by CLI at startup (not an env var).
    # None → results/, True → results_graph/, False → results_no_graph/
    _graph_mode: bool | None = PrivateAttr(default=None)
    # When True, overrides graph mode and routes output to results_semantic/.
    _semantic_only: bool = PrivateAttr(default=False)

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

    # RAGAS RunConfig for API providers (ollama uses its own serialized path).
    # workers=16 saturates Anthropic rate limits → backoff retries blow the
    # 180s job timeout (observed 27% TimeoutError); 4 workers stays under.
    eval_ragas_workers: int = 4
    eval_ragas_timeout: int = 600

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def set_graph_mode(self, use_graph: bool | None) -> None:
        """Set run-mode flag. Controls `results_dir` output target."""
        self._graph_mode = use_graph

    def set_semantic_mode(self, semantic_only: bool) -> None:
        """Set semantic-only flag. When True, overrides graph mode for results_dir."""
        self._semantic_only = semantic_only

    @property
    def results_dir(self) -> Path:
        """Resolve output directory based on graph/semantic mode set by CLI."""
        if self._semantic_only:
            return _EVAL_ROOT / "results_semantic"
        if self._graph_mode is True:
            return _EVAL_ROOT / "results_graph"
        if self._graph_mode is False:
            return _EVAL_ROOT / "results_no_graph"
        return _EVAL_ROOT / "results"


settings = Settings()

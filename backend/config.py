"""
Application configuration using pydantic-settings.
Reads from .env file in project root.
"""

from typing import Literal

from pydantic_settings import BaseSettings
from pathlib import Path

# The only graph strategy R1 has: the event_registry auxiliary lane, which
# appends a curated event anchor AFTER the finished top-k (never competes for a
# slot). Every Neo4j-backed strategy was removed with R1 (D-09: no Neo4j).
GraphStrategyName = Literal["event_registry"]


class Settings(BaseSettings):
    # Which build to serve (design §7.6/§7.8): rag_meta.serving's row for
    # RAG_ENV, unless RAG_BUILD_ID names one (tests, staging). Resolved once at
    # startup; STRICT_BUILD_CHECK=false lets a failed handshake start the app so
    # /api/v1/health can list the mismatches (it still serves no data).
    rag_env: Literal["prod", "staging"] = "prod"
    rag_build_id: str | None = None
    strict_build_check: bool = True
    # Where the contract directories are mounted (read-only); None reads
    # rag_meta.builds.contracts_dir as it is (a host path).
    contracts_root: str | None = None

    # PostgreSQL (the build's schema comes from rag_meta.builds)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bible_rag"
    postgres_user: str = "bible"
    postgres_password: str = "bible_password"

    # Qdrant (the build's collection comes from rag_meta.builds)
    qdrant_host: str = "localhost"
    qdrant_http_port: int = 6333
    qdrant_grpc_port: int = 6334

    # LLM Provider: ollama | claude | openai | gemini
    llm_provider: str = "ollama"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"

    # Claude (Anthropic)
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Gemini (Google)
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # LLM generation settings
    llm_max_tokens: int = 100000
    llm_temperature: float = 0.1

    # Model settings
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # RAG settings
    default_top_k: int = 5
    semantic_search_top_k: int = 20
    reranker_top_k: int = 5

    # Route weights per route type (the keys the routes read).
    route_weights: dict = {
        "R2": {"sql": 0.9, "semantic": 0.6},
        "R3": {"semantic": 0.7, "sql": 0.5},
        "R4": {"semantic": 0.7, "sql": 0.5},
        "R5": {"semantic": 0.65, "sql_chapter": 0.85, "sql": 0.4},
        "R6": {"semantic": 0.7, "sql": 0.5},
    }

    # Graph toggle. With Neo4j gone it gates only the event_registry lane;
    # overridable per request via `use_graph`.
    rag_use_graph: bool = True

    # Graph strategies in effect when use_graph is on: ["event_registry"] (the
    # default since 2026-10-04) or []. Env value is a JSON array.
    rag_graph_strategies: list[GraphStrategyName] = ["event_registry"]

    # Event registry auxiliary lane: how many curated anchors may be appended
    # after the top-k. The 2026-10 simulation found no gain from a second slot.
    rag_event_registry_slots: int = 1

    # Rank fusion: final ranking sorts by
    #     fused = (1 - alpha) * rerank_score + alpha * strategy_weight
    # instead of rerank_score alone (alpha=0 is pure reranker ordering).
    rag_rank_fusion_enabled: bool = True
    rag_rank_fusion_alpha: float = 0.3

    model_config = {
        "env_file": str(Path(__file__).resolve().parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

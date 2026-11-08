"""
Application configuration using pydantic-settings.
Reads from .env file in project root.
"""

from typing import Literal

from pydantic_settings import BaseSettings
from pathlib import Path

# The graph side of a request: the event_registry auxiliary lane, which appends a curated event
# anchor AFTER the finished top-k (never competes for a slot); graph_walk (utils.retrieval.graph_walk),
# whose passages join the candidate pool before ranking; and kin_card (utils.kg.kin_card), a kinship
# card for the prompt. The last two read the build's graph in Neo4j, so they do nothing on a build
# without one.
GraphStrategyName = Literal["event_registry", "graph_walk", "kin_card"]


class Settings(BaseSettings):
    # Which build to serve (design §7.6/§7.8): rag_meta.serving's row for
    # RAG_ENV, always. RAG_BUILD_ID, when set, is the build the operator expects:
    # if serving names another, the handshake fails. Resolved once at startup;
    # STRICT_BUILD_CHECK=false lets a failed handshake start the app so
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

    # Neo4j, only for a build with a graph (database.neo4j_db); no defaults: a build with a
    # graph on a backend without these reports graph state "unavailable" on /api/v1/health
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""

    # LLM Provider: vllm | ollama | claude | openai | gemini
    llm_provider: str = "vllm"

    # vLLM (docker-compose.yml's vllm service; the model is its --served-model-name)
    vllm_base_url: str = "http://localhost:8010"
    vllm_model: str = "google/gemma-4-E4B-it"

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

    # Route weights per route type (the keys the routes read). Each only raises a
    # candidate's weight to its floor: a "semantic" above the dense arm's 0.65 for a
    # non-verse hit would flatten the arm's verse prior (0.70 / 0.65; R3/R4/R6 ran
    # 0.7 until 2026-10-29).
    route_weights: dict = {
        "R2": {"sql": 0.9, "semantic": 0.6},
        "R3": {"semantic": 0.65, "sql": 0.5},
        "R4": {"semantic": 0.65, "sql": 0.5},
        "R5": {"semantic": 0.65, "sql_chapter": 0.85, "sql": 0.4},
        "R6": {"semantic": 0.65, "sql": 0.5},
    }

    # Graph toggle: the event_registry lane, the graph walk and the three cards; overridable per
    # request via `use_graph`.
    rag_use_graph: bool = True

    # Graph strategies in effect when use_graph is on: any of the three names, [] for none.
    # Env value is a JSON array.
    rag_graph_strategies: list[GraphStrategyName] = ["event_registry", "graph_walk", "kin_card"]

    # Graph walk (utils.retrieval.graph_walk). Its seeds: this many of the dense arm's passages.
    walk_seed_passages: int = 10
    # A name in more passages than this is a hub: the walk does not cross it.
    walk_max_df: int = 150
    # Names kept per round, first-round passages that seed the second, passages a walk returns.
    walk_top_names: int = 30
    walk_round2_seeds: int = 20
    walk_k: int = 10
    # A seed's PARALLEL pericope's passages get this much of its weight; s = s1 + this·s2.
    walk_parallel_factor: float = 0.5
    walk_round2_factor: float = 0.5
    # A walked passage's weight in the pool: below the dense arm's (0.65-0.7), so it gets in on the reranker's
    # word and not on its own. One already in the pool keeps its weight.
    walk_weight: float = 0.5

    # Kinship card (utils.kg.kin_card): its size, and the weight of the passages holding its verses.
    kin_card_max_rows: int = 12
    kin_card_max_chars: int = 700
    kin_evidence_weight: float = 0.75

    # Chronology card (utils.regnal): on dynasty-chronology questions the generator gets the
    # regnal layer's derivation card (Kay 2026-10-19: on by default). Needs a build with
    # regnal_layer.json; overridable per request via `use_regnal_card`.
    rag_regnal_card: bool = True

    # Genesis age card (utils.gen_card): on the Genesis 5/11 age questions its rule takes, and only
    # where the chronology card's trigger does not fire, the generator gets the Genesis layer's card
    # (plan 2026-10-21 D5: on by default). Needs a build with gen_layer.json and gen_names.json;
    # overridable per request via `use_gen_card`.
    rag_gen_card: bool = True

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

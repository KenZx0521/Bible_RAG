"""
Application configuration using pydantic-settings.
Reads from .env file in project root.
"""

from typing import Literal

from pydantic_settings import BaseSettings
from pathlib import Path

# Graph strategies, by the label each reports in strategies_used; "all" enables
# every one. Single source of truth: router.GRAPH_STRATEGIES and the request
# model both derive from this, and Settings validation rejects unknown names at
# startup.
GraphStrategyName = Literal[
    "all",
    "graph_person",      # R3 person → MENTIONS pericopes
    "graph_event",       # R4/R5 event anchors
    "graph_place",       # R6 place → MENTIONS pericopes
    "graph",             # R5 entity traversal over intent entities
    "entity_path",       # R3/R6 Entity-Entity relation walk
    "entity_query",      # R3-R6 bible_entities vector supplement
    "cross_ref_expand",  # R3/R4/R6 pre-rerank CROSS_REFERENCES expansion
    "cross_reference",   # R5 CROSS_REFERENCES from semantic seeds (its sources
                         # are labelled cross_ref_expand when multi-hop is on)
    "event_registry",    # R4/R5 auxiliary lane: appends a curated event anchor
                         # AFTER the finished top-k (never competes for a slot);
                         # not included in "all", which keeps its Round 3 meaning
]


class Settings(BaseSettings):
    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bible_rag"
    postgres_user: str = "bible"
    postgres_password: str = "bible_password"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_http_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_collection: str = "bible_embeddings"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"

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

    # Route weights per route type.
    # entity_query is supplement-only (always below semantic) so it never
    # displaces a high-scoring semantic chunk from the pre-rerank pool.
    route_weights: dict = {
        "R2": {"sql": 0.9, "semantic": 0.6},
        "R3": {"graph": 0.9, "semantic": 0.7, "entity_query": 0.6, "sql": 0.5},
        "R4": {"graph": 0.85, "semantic": 0.7, "entity_query": 0.6, "sql": 0.5},
        "R5": {"cross_ref": 0.85, "graph": 0.75, "semantic": 0.65, "sql_chapter": 0.85, "entity_query": 0.6, "sql": 0.4},
        "R6": {"graph": 0.85, "semantic": 0.7, "entity_query": 0.6, "sql": 0.5},
    }

    # Hybrid Search settings
    hybrid_search_enabled: bool = False
    qdrant_hybrid_collection: str = "bible_embeddings_hybrid"
    bm25_vocabulary_path: str = "output/bm25_vocabulary.json"
    hybrid_prefetch_limit: int = 50
    hybrid_fusion_method: str = "rrf"

    # Graph retrieval toggle (gates Neo4j-backed graph_retriever + cross_ref_retriever).
    # Can be overridden per-request via the `use_graph` payload field.
    rag_use_graph: bool = True

    # Which graph strategies may inject candidates when use_graph is on
    # (GraphStrategyName above). Overridable per request via `graph_strategies`.
    # Env value must be a JSON array: RAG_GRAPH_STRATEGIES='["all"]' (every
    # strategy, the pre-2026-10 behaviour), '[]' (none); a bare word or an empty
    # value fails at startup. The 2026-10 diagnosis of the Round 3 500-question
    # runs found graph_event the only strategy whose injected passages beat the
    # ones they displaced (26% vs 18% gold); graph_person cost R3 verse recall
    # −0.046. Since 2026-10-04 the default is the event_registry auxiliary
    # lane instead: it keeps graph_event's curated-event gains but appends
    # after the top-k, so the top-k equals graph-off (500 questions: verse
    # recall +0.0072 vs k-aligned dense, no question worse; graph_event in the
    # pool had 6 questions worse) and its answers were non-inferior to dense@6
    # (evaluation/experiments/2026-10-03_event_registry/results.md).
    rag_graph_strategies: list[GraphStrategyName] = ["event_registry"]

    # Event registry auxiliary lane (graph strategy "event_registry"): how many
    # curated anchors may be appended after the top-k. The 2026-10 simulation
    # found no gain from a second slot over the first.
    rag_event_registry_slots: int = 1

    # Cross-reference 2-hop expansion: traverse CROSS_REFERENCES from top graph
    # seeds to surface neighbouring pericopes. Activates the hand-curated
    # cross-book edges plus TSK community edges in R3/R4/R5/R6 pre-rerank pool.
    # expand_limit dropped 30→10 after the 2026-07-06 P0 eval: post-TSK every
    # seed has ~180 one-hop neighbours, and 30 topically-related but
    # narrative-wrong candidates per route displaced correct pericopes on
    # EVENT questions (EVENT_015/017/019, PERSON_011, GENERAL_013).
    rag_use_cross_ref_expand: bool = True
    rag_cross_ref_max_hops: int = 2
    rag_cross_ref_top_seeds: int = 5
    rag_cross_ref_expand_limit: int = 10

    # Rank fusion (last-mile fix for the 2026-05 + 2026-07 double evidence that
    # pure rerank_score ordering lets BGE literal surface matches erase graph
    # signals): final ranking sorts by
    #     fused = (1 - alpha) * rerank_score + alpha * strategy_weight
    # instead of rerank_score alone. Strategy weight is the per-candidate
    # retrieval prior (graph anchors 0.85-0.9 / semantic 0.7 / TSK cross-ref
    # 0.5-0.6 / sql_supplement 0.5), so graph-anchored candidates win close
    # calls while a large rerank gap still dominates. alpha=0 degrades to the
    # legacy pure-reranker behaviour.
    rag_rank_fusion_enabled: bool = True
    rag_rank_fusion_alpha: float = 0.3

    # Entity-Path retriever: walks Entity-[r]-Entity edges (FATHER_OF, RULED, ...)
    # populated by scripts/relation_extraction/extract_relations.py. Provides
    # multi-hop fact-level reasoning that 1-hop MENTIONS cannot reach.
    rag_use_entity_path: bool = True
    rag_entity_path_max_hops: int = 2
    rag_entity_path_limit: int = 15
    qdrant_entity_collection: str = "bible_entities"

    # Entity-Query retriever (supplement-only across R3/R4/R5/R6) — BGE-M3 query
    # → bible_entities vector match → Neo4j MENTIONS pericopes. Adds candidates
    # that semantic embedding misses (e.g. "王國分裂" → 列王紀上12 via Event
    # entity「北方的支派反叛」). Simulation on 100-question eval recovers ≥1
    # ground-truth chapter on 8/10 failure cases that pure semantic missed.
    # Weight 0.6 (below semantic 0.7) ensures supplement candidates do not
    # displace high-scoring semantic chunks pre-rerank.
    rag_use_entity_query: bool = True
    rag_entity_query_top_k: int = 8
    rag_entity_query_score_threshold: float = 0.4
    rag_entity_query_hub_threshold: int = 50
    rag_entity_query_pericopes_per_entity_normal: int = 5
    rag_entity_query_pericopes_per_entity_hub: int = 3
    rag_entity_query_supplement_cap: int = 5

    model_config = {
        "env_file": str(Path(__file__).resolve().parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


settings = Settings()

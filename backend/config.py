"""
Application configuration using pydantic-settings.
Reads from .env file in project root.
"""

from pydantic_settings import BaseSettings
from pathlib import Path


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

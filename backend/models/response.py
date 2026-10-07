"""
Pydantic v2 response models.
"""

from typing import Optional
from pydantic import BaseModel


class Source(BaseModel):
    id: str
    book: str
    chapter: int | None = None
    title: str
    verse_range: str = ""
    score: float | None = None
    # Retrieval provenance for eval diagnostics: which strategy surfaced this
    # candidate (semantic / graph_event / cross_ref_expand / ...) and the raw
    # reranker score when `score` is the fused score.
    strategy: str | None = None
    rerank_score: float | None = None
    # Every strategy that returned this passage, first-seen order. `strategy`
    # names only the copy that won dedup, so a graph label alone cannot tell
    # whether dense retrieval had found the passage too.
    found_by: list[str] | None = None
    # Exact context block fed to the generator for this source
    # (`[i] 書卷 第N章 - 標題 (節)` + text). Only when include_context=true.
    context: str | None = None


class IntentInfo(BaseModel):
    type: str
    entities: list[str] = []
    verse_refs: list[str] = []


class RetrievalStats(BaseModel):
    strategies_used: list[str] = []
    total_candidates: int = 0
    reranked_top_k: int = 0
    route_used: str = ""
    strategy_errors: dict[str, str] = {}
    use_graph: bool = True
    # Graph strategies allowed for this request (they only run when use_graph).
    graph_strategies: list[str] = []
    # Effective rank-fusion alpha for this request (None = fusion disabled).
    fusion_alpha: float | None = None
    # Event-registry events the question triggered; their anchors appear as
    # extra sources (strategy "event_registry") after the top-k when missing.
    event_registry_events: list[str] = []


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    intent: IntentInfo
    retrieval_stats: RetrievalStats


class VerseResponse(BaseModel):
    book_id: str
    book_name: str
    chapter: int
    verse: int | None = None
    text: str = ""
    pericope_id: str | None = None
    pericope_title: str | None = None


class ChapterResponse(BaseModel):
    id: str
    chapter_num: int
    book_name: str
    book_name_en: str
    total_verses: int
    pericopes: list[dict]


class EntityResponse(BaseModel):
    entity_id: str
    type: str
    canonical_name: str
    aliases: list[str] = []
    description: str | None = None
    mention_count: int = 0
    related_passages: list[dict] = []
    related_entities: list[dict] = []


class HealthResponse(BaseModel):
    status: str
    services: dict[str, bool]
    # Report-only: the pinned tokenizer fingerprint of the embedder and the
    # reranker (None before init). A failing contract already stops startup,
    # so these never change `status`.
    encoder: dict[str, dict | None] = {}

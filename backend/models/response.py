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
    # Effective rank-fusion alpha for this request (None = fusion disabled).
    fusion_alpha: float | None = None


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

"""
Pydantic v2 response models.
"""

from pydantic import BaseModel


class Source(BaseModel):
    # The record's id in the build's grammar (ragcommon.ids): a passage (ps:),
    # a chunk (ck:), or for a verse lookup the verse record (vs:{unit}) when it
    # is one unit, else its slot range ({start_key}~{end_key}). Read `kind` and
    # start_key/end_key instead of parsing it.
    id: str
    book: str
    chapter: int | None = None
    title: str
    # chapter-internal integer range ("19-31", "2-3")
    verse_range: str = ""
    score: float | None = None
    # Retrieval provenance for eval diagnostics: which strategy surfaced this
    # candidate (hybrid_hybrid / verse_direct / event_registry / ...) and the raw
    # reranker score when `score` is the fused score.
    strategy: str | None = None
    rerank_score: float | None = None
    # Every strategy that returned this passage, first-seen order.
    found_by: list[str] | None = None
    # Exact context block fed to the generator for this source
    # (`[i] 書卷 第N章 - 標題 (節)` + text). Only when include_context=true.
    context: str | None = None
    # passage | chunk | verse
    kind: str | None = None
    # first and last verse key covered ("act.9.19b" marks a second half)
    start_key: str | None = None
    end_key: str | None = None
    # the passage holding the record (for a verse lookup: of its first unit)
    passage_id: str | None = None
    # every passage the record spans, when more than one (a verse a mid-verse
    # heading cuts, or a verse range crossing passages)
    split_passage_ids: list[str] = []
    build_id: str | None = None


class IntentInfo(BaseModel):
    type: str
    entities: list[str] = []
    verse_refs: list[str] = []
    # reference-shaped text that names no verse of this edition (e.g. 約翰福音3:99)
    rejected_refs: list[str] = []


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
    # Event-registry events (legacy ids) the question triggered; their anchors
    # appear as extra sources (strategy "event_registry") after the top-k.
    event_registry_events: list[str] = []


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    intent: IntentInfo
    retrieval_stats: RetrievalStats


class MidHeading(BaseModel):
    heading_id: str
    offset: int
    text: str


class VerseResponse(BaseModel):
    book_id: str
    book_name: str
    chapter: int
    verse: int | None = None
    # the whole unit: a merged unit's text once; an omitted slot's 「本譯本此節從缺」
    text: str = ""
    # the passage holding the unit (an old pericope is a new passage)
    pericope_id: str | None = None
    pericope_title: str | None = None
    verse_range: str = ""                 # the unit's label: "3", or "2-3" when merged
    unit_key: str | None = None
    status: str = "present"               # present | merged | omitted_variant
    footnote: str | None = None           # an omitted slot's variant footnote
    passage_id: str | None = None
    split_passage_ids: list[str] = []
    headings: list[MidHeading] = []       # headings printed inside the unit
    alias: str | None = None              # external verse number resolved (jhn.7.53->jhn.8.1)
    build_id: str | None = None


class ChapterResponse(BaseModel):
    id: str
    chapter_num: int
    book_name: str
    book_name_en: str
    total_verses: int
    # the chapter's passages in canonical order
    pericopes: list[dict]
    # superscription and book division texts (never returned by /verse)
    chapter_texts: list[dict] = []
    build_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    services: dict[str, bool]
    # The pinned tokenizer fingerprints of the embedder and the reranker.
    encoder: dict[str, dict | None] = {}
    build_id: str | None = None
    # {build_id, ok, strict, mismatches}: any mismatch makes /health answer 503
    handshake: dict = {}

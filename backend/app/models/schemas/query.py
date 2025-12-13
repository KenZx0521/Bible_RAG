"""Query request and response schemas."""

from enum import Enum
from pydantic import BaseModel, Field


class QueryMode(str, Enum):
    """Query mode options."""

    AUTO = "auto"
    VERSE = "verse"
    TOPIC = "topic"
    PERSON = "person"
    EVENT = "event"


class QueryType(str, Enum):
    """Classified query type."""

    VERSE_LOOKUP = "VERSE_LOOKUP"
    TOPIC_QUESTION = "TOPIC_QUESTION"
    PERSON_QUESTION = "PERSON_QUESTION"
    EVENT_QUESTION = "EVENT_QUESTION"
    GENERAL_BIBLE_QUESTION = "GENERAL_BIBLE_QUESTION"


class QueryOptions(BaseModel):
    """Query options."""

    max_results: int = Field(default=5, ge=1, le=20)
    include_graph: bool = Field(default=False)


class QueryRequest(BaseModel):
    """RAG query request."""

    query: str = Field(..., min_length=1, max_length=500)
    mode: QueryMode = Field(default=QueryMode.AUTO)
    options: QueryOptions = Field(default_factory=QueryOptions)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "聖經怎麼談饒恕？",
                    "mode": "auto",
                    "options": {"max_results": 5, "include_graph": False},
                }
            ]
        }
    }


class PericopeSegment(BaseModel):
    """Pericope segment in query response."""

    id: int
    type: str = "pericope"
    book: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    title: str
    text_excerpt: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class QueryMeta(BaseModel):
    """Query response metadata."""

    query_type: str
    used_retrievers: list[str]
    total_processing_time_ms: int = Field(ge=0)
    llm_model: str


class GraphContext(BaseModel):
    """Graph context in query response."""

    related_topics: list[str] = Field(default_factory=list)
    related_persons: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """RAG query response."""

    answer: str
    segments: list[PericopeSegment]
    meta: QueryMeta
    graph_context: GraphContext | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "answer": "## 饒恕的核心教導\n\n聖經中對於饒恕有多處教導...",
                    "segments": [
                        {
                            "id": 1234,
                            "type": "pericope",
                            "book": "馬太福音",
                            "chapter_start": 18,
                            "verse_start": 21,
                            "chapter_end": 18,
                            "verse_end": 35,
                            "title": "饒恕七十個七次",
                            "text_excerpt": "那時，彼得進前來，對耶穌說...",
                            "relevance_score": 0.87,
                        }
                    ],
                    "meta": {
                        "query_type": "TOPIC_QUESTION",
                        "used_retrievers": ["sparse", "dense"],
                        "total_processing_time_ms": 3542,
                        "llm_model": "qwen2",
                    },
                    "graph_context": None,
                }
            ]
        }
    }

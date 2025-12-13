"""Pydantic schemas package."""

from app.models.schemas.book import (
    BookBase,
    BookChapters,
    BookDetail,
    BookList,
    ChapterInfo,
)
from app.models.schemas.common import (
    PaginatedResponse,
    PaginationParams,
)
from app.models.schemas.pericope import (
    BookPericopes,
    PericopeBase,
    PericopeDetail,
    PericopeList,
)
from app.models.schemas.query import (
    GraphContext,
    PericopeSegment,
    QueryMeta,
    QueryMode,
    QueryOptions,
    QueryRequest,
    QueryResponse,
    QueryType,
)
from app.models.schemas.verse import (
    BookVerses,
    VerseBase,
    VerseDetail,
    VerseList,
    VerseSearchResult,
)
from app.models.schemas.graph import (
    CrossReference,
    CrossReferenceType,
    EntityBase,
    EntityDetail,
    EntityRelationshipsResponse,
    EntitySearchResult,
    EntityType,
    GraphEdge,
    GraphNode,
    GraphResponse,
    GraphRetrievalResult,
    GraphStats,
    ParallelPassage,
    PericopeEntitiesResponse,
    PericopeParallelsResponse,
    ProphecyLink,
    RelatedTopic,
    RelationshipInfo,
    TopicBase,
    TopicDetail,
    TopicRelatedResponse,
    TopicSearchResult,
    TopicType,
    VerseCrossReferencesResponse,
    VerseEntitiesResponse,
    VersePropheciesResponse,
)

__all__ = [
    # Common
    "PaginationParams",
    "PaginatedResponse",
    # Book
    "BookBase",
    "BookDetail",
    "BookList",
    "ChapterInfo",
    "BookChapters",
    # Verse
    "VerseBase",
    "VerseDetail",
    "VerseList",
    "VerseSearchResult",
    "BookVerses",
    # Pericope
    "PericopeBase",
    "PericopeDetail",
    "PericopeList",
    "BookPericopes",
    # Query
    "QueryMode",
    "QueryType",
    "QueryOptions",
    "QueryRequest",
    "PericopeSegment",
    "QueryMeta",
    "GraphContext",
    "QueryResponse",
    # Graph
    "EntityType",
    "TopicType",
    "EntityBase",
    "EntityDetail",
    "TopicBase",
    "TopicDetail",
    "GraphNode",
    "GraphEdge",
    "GraphResponse",
    "EntitySearchResult",
    "TopicSearchResult",
    "VerseEntitiesResponse",
    "PericopeEntitiesResponse",
    "RelationshipInfo",
    "EntityRelationshipsResponse",
    "GraphRetrievalResult",
    "GraphStats",
    # Cross-references
    "CrossReferenceType",
    "CrossReference",
    "VerseCrossReferencesResponse",
    # Prophecy
    "ProphecyLink",
    "VersePropheciesResponse",
    # Parallels
    "ParallelPassage",
    "PericopeParallelsResponse",
    # Related topics
    "RelatedTopic",
    "TopicRelatedResponse",
]

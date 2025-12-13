"""Graph-related schemas for Neo4j knowledge graph API."""

from enum import Enum
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Entity type enumeration."""

    PERSON = "PERSON"
    PLACE = "PLACE"
    GROUP = "GROUP"
    EVENT = "EVENT"
    TOPIC = "TOPIC"


class TopicType(str, Enum):
    """Topic type enumeration."""

    DOCTRINE = "DOCTRINE"
    MORAL = "MORAL"
    HISTORICAL = "HISTORICAL"
    PROPHETIC = "PROPHETIC"
    OTHER = "OTHER"


# Base schemas
class EntityBase(BaseModel):
    """Base entity schema."""

    id: int
    name: str
    type: EntityType

    model_config = {"from_attributes": True}


class EntityDetail(EntityBase):
    """Detailed entity with relationships."""

    description: str | None = None
    related_verses_count: int = 0
    related_entities: list[EntityBase] = Field(default_factory=list)


class TopicBase(BaseModel):
    """Base topic schema."""

    id: int
    name: str
    type: TopicType

    model_config = {"from_attributes": True}


class TopicDetail(TopicBase):
    """Detailed topic with relationships."""

    description: str | None = None
    related_verses_count: int = 0
    related_topics: list[TopicBase] = Field(default_factory=list)


# Graph visualization schemas
class GraphNode(BaseModel):
    """Node in graph response for visualization."""

    id: str
    label: str
    type: str
    properties: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Edge in graph response for visualization."""

    source: str
    target: str
    type: str
    properties: dict = Field(default_factory=dict)


class GraphResponse(BaseModel):
    """Graph subgraph response for visualization."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# Search schemas
class EntitySearchResult(BaseModel):
    """Entity search result."""

    entities: list[EntityBase] = Field(default_factory=list)
    total: int = 0


class TopicSearchResult(BaseModel):
    """Topic search result."""

    topics: list[TopicBase] = Field(default_factory=list)
    total: int = 0


# Verse entity schemas
class VerseEntitiesResponse(BaseModel):
    """All entities for a specific verse."""

    verse_id: int
    verse_reference: str = ""
    persons: list[EntityBase] = Field(default_factory=list)
    places: list[EntityBase] = Field(default_factory=list)
    groups: list[EntityBase] = Field(default_factory=list)
    events: list[EntityBase] = Field(default_factory=list)
    topics: list[TopicBase] = Field(default_factory=list)


# Pericope entity schemas
class PericopeEntitiesResponse(BaseModel):
    """All entities for a specific pericope."""

    pericope_id: int
    pericope_title: str = ""
    persons: list[EntityBase] = Field(default_factory=list)
    places: list[EntityBase] = Field(default_factory=list)
    groups: list[EntityBase] = Field(default_factory=list)
    events: list[EntityBase] = Field(default_factory=list)
    topics: list[TopicBase] = Field(default_factory=list)


# Relationship schemas
class RelationshipInfo(BaseModel):
    """Information about a relationship."""

    type: str
    source_id: int
    source_name: str
    source_type: str
    target_id: int
    target_name: str
    target_type: str
    properties: dict = Field(default_factory=dict)


class EntityRelationshipsResponse(BaseModel):
    """Relationships for an entity."""

    entity: EntityBase
    relationships: list[RelationshipInfo] = Field(default_factory=list)


# Graph retrieval result (for RAG pipeline integration)
class GraphRetrievalResult(BaseModel):
    """Result from graph-based retrieval."""

    id: int  # pericope_id
    book_id: int
    book_name: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    title: str
    text: str
    score: float = 0.0
    graph_context: dict = Field(default_factory=dict)

    @property
    def reference(self) -> str:
        """Get formatted reference string."""
        if self.chapter_start == self.chapter_end:
            return f"{self.book_name} {self.chapter_start}:{self.verse_start}-{self.verse_end}"
        return f"{self.book_name} {self.chapter_start}:{self.verse_start}-{self.chapter_end}:{self.verse_end}"


# Graph statistics
class GraphStats(BaseModel):
    """Statistics about the knowledge graph."""

    total_persons: int = 0
    total_places: int = 0
    total_groups: int = 0
    total_events: int = 0
    total_topics: int = 0
    total_relationships: int = 0


# Cross-reference schemas
class CrossReferenceType(str, Enum):
    """Cross-reference type enumeration."""

    QUOTES = "QUOTES"
    ALLUDES_TO = "ALLUDES_TO"


class CrossReference(BaseModel):
    """A cross-reference between two verses."""

    verse_id: int
    book_name: str
    chapter: int
    verse: int
    reference: str
    type: CrossReferenceType
    votes: int = 0


class VerseCrossReferencesResponse(BaseModel):
    """Cross-references for a verse."""

    verse_id: int
    verse_reference: str
    quotes: list[CrossReference] = Field(default_factory=list)
    quoted_by: list[CrossReference] = Field(default_factory=list)
    alludes_to: list[CrossReference] = Field(default_factory=list)
    alluded_by: list[CrossReference] = Field(default_factory=list)
    total: int = 0


# Prophecy schemas
class ProphecyLink(BaseModel):
    """A prophecy fulfillment link."""

    verse_id: int
    book_name: str
    chapter: int
    verse: int
    reference: str
    text_excerpt: str = ""
    confidence: float = 0.0


class VersePropheciesResponse(BaseModel):
    """Prophecy links for a verse."""

    verse_id: int
    verse_reference: str
    is_ot: bool = False
    fulfillments: list[ProphecyLink] = Field(default_factory=list)  # NT verses this fulfills
    prophecies: list[ProphecyLink] = Field(default_factory=list)  # OT verses fulfilled here
    total: int = 0


# Parallel passage schemas
class ParallelPassage(BaseModel):
    """A parallel passage in another Gospel."""

    pericope_id: int
    book_name: str
    title: str
    reference: str
    parallel_name: str = ""


class PericopeParallelsResponse(BaseModel):
    """Parallel passages for a pericope."""

    pericope_id: int
    pericope_title: str
    pericope_reference: str
    parallels: list[ParallelPassage] = Field(default_factory=list)
    total: int = 0


# Related topic schemas
class RelatedTopic(BaseModel):
    """A related topic with weight."""

    id: int
    name: str
    type: TopicType
    weight: float = 0.0
    co_occurrence: int = 0


class TopicRelatedResponse(BaseModel):
    """Related topics for a topic."""

    topic_id: int
    topic_name: str
    related: list[RelatedTopic] = Field(default_factory=list)
    total: int = 0

"""
Pydantic Models for Bible Chunking

Defines the data structures for Book, Chapter, Pericope, Chunk, and Verse.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class Verse(BaseModel):
    """Represents a single verse or verse range."""

    num: str  # Can be "1" or "1-2" for ranges
    text: str
    is_poetry: bool = False
    lines: List[str] = Field(default_factory=list)  # For poetry with multiple lines

    @property
    def verse_start(self) -> int:
        """Get the starting verse number."""
        if "-" in self.num:
            return int(self.num.split("-")[0])
        return int(self.num)

    @property
    def verse_end(self) -> int:
        """Get the ending verse number."""
        if "-" in self.num:
            return int(self.num.split("-")[1])
        return int(self.num)


class CrossReference(BaseModel):
    """Represents a cross-reference to another passage."""

    reference_text: str  # Original text like "路3‧23－38"
    book_id: Optional[str] = None
    book_name: Optional[str] = None
    chapter: Optional[int] = None
    verse_start: Optional[int] = None
    verse_end: Optional[int] = None
    target_pericope_id: Optional[str] = None  # Will be resolved later


class Footnote(BaseModel):
    """Represents a footnote."""

    verse_ref: str  # e.g., "1:2"
    text: str


class Chunk(BaseModel):
    """
    Represents a chunk of verses within a pericope.
    Only created when pericope exceeds token limit.
    """

    id: str  # Format: "gen:1:0:0" (book:chapter:pericope_index:chunk_index)
    type: str = "chunk"
    parent_id: str  # Pericope ID
    content: str  # Raw verse text joined
    content_for_embedding: str  # Text with context prefix

    metadata: Dict[str, Any] = Field(default_factory=dict)
    verses: List[Verse] = Field(default_factory=list)

    # Embedding-related fields (to be filled later)
    embedding_id: Optional[str] = None

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "id": self.id,
            "type": self.type,
            "parent_id": self.parent_id,
            "content": self.content,
            "content_for_embedding": self.content_for_embedding,
            "metadata": self.metadata,
            "verses": [v.model_dump() for v in self.verses],
        }


class Pericope(BaseModel):
    """
    Represents a pericope (section/paragraph) within a chapter.
    This is the primary unit for embeddings.
    """

    id: str  # Format: "gen:1:0" (book:chapter:pericope_index)
    type: str = "pericope"
    parent_id: str  # Chapter ID
    title: str  # Section title from H3
    content: str  # Raw verse text joined
    content_for_embedding: str  # Text with context prefix

    metadata: Dict[str, Any] = Field(default_factory=dict)
    cross_references: List[CrossReference] = Field(default_factory=list)
    verses: List[Verse] = Field(default_factory=list)
    chunks: List[Chunk] = Field(default_factory=list)  # Only if chunking required

    # Embedding-related fields (to be filled later)
    embedding_id: Optional[str] = None

    @property
    def verse_range(self) -> str:
        """Get verse range string like '1-31'."""
        if not self.verses:
            return ""
        start = self.verses[0].verse_start
        end = self.verses[-1].verse_end
        if start == end:
            return str(start)
        return f"{start}-{end}"

    @property
    def requires_chunking(self) -> bool:
        """Check if this pericope needs to be chunked."""
        return self.metadata.get("requires_chunking", False)

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "id": self.id,
            "type": self.type,
            "parent_id": self.parent_id,
            "title": self.title,
            "content": self.content,
            "content_for_embedding": self.content_for_embedding,
            "metadata": self.metadata,
            "cross_references": [cr.model_dump() for cr in self.cross_references],
            "verses": [v.model_dump() for v in self.verses],
        }


class Chapter(BaseModel):
    """Represents a chapter within a book."""

    id: str  # Format: "gen:1" (book:chapter)
    type: str = "chapter"
    parent_id: str  # Book ID
    chapter_num: int

    metadata: Dict[str, Any] = Field(default_factory=dict)
    pericopes: List[Pericope] = Field(default_factory=list)
    footnotes: List[Footnote] = Field(default_factory=list)

    @property
    def total_verses(self) -> int:
        """Count total verses in chapter."""
        count = 0
        for p in self.pericopes:
            for v in p.verses:
                if "-" in v.num:
                    parts = v.num.split("-")
                    count += int(parts[1]) - int(parts[0]) + 1
                else:
                    count += 1
        return count

    @property
    def total_pericopes(self) -> int:
        """Count pericopes in chapter."""
        return len(self.pericopes)

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "id": self.id,
            "type": self.type,
            "parent_id": self.parent_id,
            "chapter_num": self.chapter_num,
            "total_verses": self.total_verses,
            "total_pericopes": self.total_pericopes,
            "metadata": self.metadata,
            "footnotes": [f.model_dump() for f in self.footnotes],
        }


class Book(BaseModel):
    """Represents a Bible book."""

    id: str  # Short ID like "gen"
    type: str = "book"
    name: str  # Chinese name like "創世記"
    name_en: str  # English name like "Genesis"
    testament: str  # "old" or "new"
    category: str  # e.g., "pentateuch", "gospels"
    order: int  # Canonical order (1-66)

    chapters: List[Chapter] = Field(default_factory=list)

    @property
    def total_chapters(self) -> int:
        """Count total chapters in book."""
        return len(self.chapters)

    @property
    def total_pericopes(self) -> int:
        """Count total pericopes in book."""
        return sum(c.total_pericopes for c in self.chapters)

    @property
    def total_verses(self) -> int:
        """Count total verses in book."""
        return sum(c.total_verses for c in self.chapters)

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "name_en": self.name_en,
            "testament": self.testament,
            "category": self.category,
            "order": self.order,
            "total_chapters": self.total_chapters,
            "total_pericopes": self.total_pericopes,
            "total_verses": self.total_verses,
        }


class EmbeddingQueueItem(BaseModel):
    """Item in the embedding queue."""

    id: str
    type: str  # "pericope" or "chunk"
    text: str  # The text to embed (content_for_embedding)

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "id": self.id,
            "type": self.type,
            "text": self.text,
        }


class Neo4jNode(BaseModel):
    """Node for Neo4j import."""

    labels: List[str]
    properties: Dict[str, Any]

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "labels": self.labels,
            "properties": self.properties,
        }


class Neo4jRelationship(BaseModel):
    """Relationship for Neo4j import."""

    start_id: str
    end_id: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

    def model_dump_jsonl(self) -> Dict[str, Any]:
        """Return dict for JSONL export."""
        return {
            "start": self.start_id,
            "end": self.end_id,
            "type": self.type,
            "properties": self.properties,
        }

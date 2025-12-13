"""Verse-related schemas."""

from pydantic import BaseModel, Field

from app.models.schemas.common import PaginatedResponse


class VerseBase(BaseModel):
    """Base verse schema."""

    id: int
    book_id: int
    book_name: str = Field(..., description="Chinese name of the book")
    chapter: int = Field(ge=1)
    verse: int = Field(ge=1)
    text: str = Field(..., description="Verse text content")
    reference: str = Field(..., description="Full reference e.g., '創世記 1:1'")

    model_config = {"from_attributes": True}


class VerseDetail(VerseBase):
    """Verse with pericope information."""

    pericope_id: int | None = None
    pericope_title: str | None = None


class VerseList(PaginatedResponse):
    """Paginated list of verses."""

    verses: list[VerseBase]


class VerseSearchResult(PaginatedResponse):
    """Search result for verses."""

    query: str = Field(..., description="Search query")
    verses: list[VerseBase]


class BookVerses(BaseModel):
    """Verses in a book response."""

    book_id: int
    book_name: str
    chapter: int | None = Field(None, description="Chapter filter if applied")
    verses: list[VerseBase]
    total: int = Field(ge=0)

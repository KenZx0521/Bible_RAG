"""Pericope-related schemas."""

from pydantic import BaseModel, Field

from app.models.schemas.common import PaginatedResponse
from app.models.schemas.verse import VerseBase


class PericopeBase(BaseModel):
    """Base pericope schema."""

    id: int
    book_id: int
    book_name: str = Field(..., description="Chinese name of the book")
    title: str = Field(..., description="Pericope title")
    reference: str = Field(..., description="Full reference e.g., '創世記 1:1-31'")
    chapter_start: int = Field(ge=1)
    verse_start: int = Field(ge=1)
    chapter_end: int = Field(ge=1)
    verse_end: int = Field(ge=1)

    model_config = {"from_attributes": True}


class PericopeDetail(PericopeBase):
    """Pericope with verses."""

    summary: str | None = None
    verses: list[VerseBase]


class PericopeList(PaginatedResponse):
    """Paginated list of pericopes."""

    pericopes: list[PericopeBase]


class BookPericopes(BaseModel):
    """Pericopes in a book response."""

    book_id: int
    book_name: str
    pericopes: list[PericopeBase]
    total: int = Field(ge=0)

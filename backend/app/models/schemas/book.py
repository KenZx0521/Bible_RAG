"""Book-related schemas."""

from pydantic import BaseModel, Field

from app.models.schemas.common import PaginatedResponse


class BookBase(BaseModel):
    """Base book schema."""

    id: int
    name_zh: str = Field(..., description="Chinese name of the book")
    abbrev_zh: str = Field(..., description="Chinese abbreviation")
    testament: str = Field(..., description="OT or NT")
    order_index: int = Field(..., description="Order in Bible")

    model_config = {"from_attributes": True}


class BookDetail(BookBase):
    """Book with additional statistics."""

    chapter_count: int = Field(ge=0, description="Number of chapters")
    verse_count: int = Field(ge=0, description="Total number of verses")
    pericope_count: int = Field(ge=0, description="Number of pericopes")


class BookList(BaseModel):
    """List of books response."""

    books: list[BookBase]
    total: int = Field(ge=0)


class ChapterInfo(BaseModel):
    """Chapter information."""

    chapter: int = Field(ge=1, description="Chapter number")
    verse_count: int = Field(ge=0, description="Number of verses in chapter")


class BookChapters(BaseModel):
    """Book chapters response."""

    book_id: int
    book_name: str
    chapters: list[ChapterInfo]
    total: int = Field(ge=0)

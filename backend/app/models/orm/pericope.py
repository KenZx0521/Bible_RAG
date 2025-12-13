"""Pericope (passage unit) ORM model."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Pericope(Base, TimestampMixin):
    """Bible pericope (passage unit) model with embedding."""

    __tablename__ = "pericopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    chapter_start: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_start: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_end: Mapped[int] = mapped_column(Integer, nullable=False)
    verse_end: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Vector embedding (bge-m3: 1024 dimensions)
    embedding = mapped_column(Vector(1024), nullable=True)

    # Relationships
    book = relationship("Book", back_populates="pericopes")
    verses = relationship("Verse", back_populates="pericope")

    @property
    def reference(self) -> str:
        """Get human-readable reference string."""
        if self.chapter_start == self.chapter_end:
            return f"{self.chapter_start}:{self.verse_start}-{self.verse_end}"
        return f"{self.chapter_start}:{self.verse_start}-{self.chapter_end}:{self.verse_end}"

    def __repr__(self) -> str:
        return f"<Pericope(id={self.id}, title='{self.title}', ref='{self.reference}')>"

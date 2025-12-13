"""Verse ORM model."""

from sqlalchemy import Computed, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Verse(Base, TimestampMixin):
    """Bible verse model with full-text search support."""

    __tablename__ = "verses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    verse: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    pericope_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pericopes.id", ondelete="SET NULL"), nullable=True
    )

    # Full-text search vector (computed column)
    tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', text)", persisted=True),
        nullable=True,
    )

    # Relationships
    book = relationship("Book", back_populates="verses")
    pericope = relationship("Pericope", back_populates="verses")
    topics = relationship("VerseTopic", back_populates="verse", cascade="all, delete-orphan")
    entities = relationship("VerseEntity", back_populates="verse", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("book_id", "chapter", "verse", name="uq_verse_reference"),
        Index("idx_verses_tsv", "tsv", postgresql_using="gin"),
        Index("idx_verses_book_chapter", "book_id", "chapter"),
    )

    @property
    def reference(self) -> str:
        """Get short reference string."""
        return f"{self.chapter}:{self.verse}"

    def __repr__(self) -> str:
        return f"<Verse(id={self.id}, ref='{self.reference}')>"

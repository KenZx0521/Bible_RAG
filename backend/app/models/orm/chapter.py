"""Chapter ORM model."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Chapter(Base, TimestampMixin):
    """Bible chapter model."""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    book = relationship("Book", back_populates="chapters")

    __table_args__ = (
        UniqueConstraint("book_id", "number", name="uq_chapter_book_number"),
    )

    def __repr__(self) -> str:
        return f"<Chapter(id={self.id}, book_id={self.book_id}, number={self.number})>"

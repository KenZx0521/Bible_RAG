"""Book ORM model."""

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Book(Base, TimestampMixin):
    """Bible book model (e.g., Genesis, Matthew)."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_zh: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    abbrev_zh: Mapped[str] = mapped_column(String(10), nullable=False)
    testament: Mapped[str] = mapped_column(String(2), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)

    # Relationships
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    pericopes = relationship("Pericope", back_populates="book", cascade="all, delete-orphan")
    verses = relationship("Verse", back_populates="book", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("testament IN ('OT', 'NT')", name="check_testament"),
    )

    def __repr__(self) -> str:
        return f"<Book(id={self.id}, name_zh='{self.name_zh}', testament='{self.testament}')>"

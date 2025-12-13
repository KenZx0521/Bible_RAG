"""Entity and VerseEntity ORM models."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Entity(Base, TimestampMixin):
    """Entity model (Person, Place, Group, Event)."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    verse_entities = relationship(
        "VerseEntity", back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("name", "type", name="uq_entity_name_type"),
        CheckConstraint(
            "type IN ('PERSON', 'PLACE', 'GROUP', 'EVENT')",
            name="check_entity_type",
        ),
        Index("idx_entities_type", "type"),
    )

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, name='{self.name}', type='{self.type}')>"


class VerseEntity(Base, TimestampMixin):
    """Verse-Entity association with role."""

    __tablename__ = "verse_entities"

    verse_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("verses.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    verse = relationship("Verse", back_populates="entities")
    entity = relationship("Entity", back_populates="verse_entities")

    __table_args__ = (
        Index("idx_verse_entities_entity", "entity_id"),
    )

    def __repr__(self) -> str:
        return f"<VerseEntity(verse_id={self.verse_id}, entity_id={self.entity_id}, role='{self.role}')>"

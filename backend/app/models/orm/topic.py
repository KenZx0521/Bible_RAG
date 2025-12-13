"""Topic and VerseTopic ORM models."""

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.orm.base import TimestampMixin


class Topic(Base, TimestampMixin):
    """Topic/theme model."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    verse_topics = relationship("VerseTopic", back_populates="topic", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "type IN ('DOCTRINE', 'MORAL', 'HISTORICAL', 'PROPHETIC', 'OTHER')",
            name="check_topic_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<Topic(id={self.id}, name='{self.name}', type='{self.type}')>"


class VerseTopic(Base, TimestampMixin):
    """Verse-Topic association with weight."""

    __tablename__ = "verse_topics"

    verse_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("verses.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # Relationships
    verse = relationship("Verse", back_populates="topics")
    topic = relationship("Topic", back_populates="verse_topics")

    __table_args__ = (
        CheckConstraint("weight >= 0 AND weight <= 1", name="check_weight_range"),
        Index("idx_verse_topics_weight", "weight", postgresql_ops={"weight": "DESC"}),
    )

    def __repr__(self) -> str:
        return f"<VerseTopic(verse_id={self.verse_id}, topic_id={self.topic_id}, weight={self.weight})>"

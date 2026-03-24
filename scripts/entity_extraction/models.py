"""
Data models for entity extraction.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from enum import Enum
import json


class EntityType(str, Enum):
    """Entity type enumeration."""
    PERSON = "Person"
    PLACE = "Place"
    GROUP = "Group"
    EVENT = "Event"
    OBJECT = "Object"
    THEME = "Theme"


class ExtractionMethod(str, Enum):
    """Extraction method enumeration."""
    NER = "ner"
    LLM = "llm"
    DICTIONARY = "dictionary"
    PERICOPE_TITLE = "pericope_title"
    POS_TAG = "pos_tag"
    RULE = "rule"
    GROUNDED_LLM = "grounded_llm"


@dataclass
class EntityCandidate:
    """A candidate entity extracted from bible_md, pending classification."""
    name: str
    proposed_type: Optional[EntityType] = None
    source_ids: List[str] = field(default_factory=list)
    grounding_text: str = ""
    confidence: float = 0.0
    extraction_phase: int = 0
    pos_tag: str = ""
    frequency: int = 1
    evidence: str = ""


@dataclass
class Entity:
    """Represents a unique entity in the knowledge base."""
    entity_id: str
    type: EntityType
    canonical_name: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    extraction_method: ExtractionMethod = ExtractionMethod.NER
    mention_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "entity_id": self.entity_id,
            "type": self.type.value,
            "canonical_name": self.canonical_name,
            "aliases": self.aliases,
            "description": self.description,
            "extraction_method": self.extraction_method.value,
            "mention_count": self.mention_count,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        """Create Entity from dictionary."""
        return cls(
            entity_id=data["entity_id"],
            type=EntityType(data["type"]),
            canonical_name=data["canonical_name"],
            aliases=data.get("aliases", []),
            description=data.get("description", ""),
            extraction_method=ExtractionMethod(data.get("extraction_method", "ner")),
            mention_count=data.get("mention_count", 0),
        )


@dataclass
class EntityMention:
    """Represents a mention of an entity in a source text."""
    mention_id: str
    entity_id: str
    source_id: str
    source_type: str  # "pericope" or "chunk"
    text_span: str
    context: str = ""
    start_pos: Optional[int] = None
    end_pos: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "mention_id": self.mention_id,
            "entity_id": self.entity_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "text_span": self.text_span,
        }
        if self.context:
            result["context"] = self.context
        if self.start_pos is not None:
            result["start_pos"] = self.start_pos
            result["end_pos"] = self.end_pos
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ExtractionResult:
    """Result from LLM extraction for a single text."""
    entities: List[dict] = field(default_factory=list)
    source_id: str = ""
    
    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "entities": self.entities,
        }

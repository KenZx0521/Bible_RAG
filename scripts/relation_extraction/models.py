"""Data models for relation extraction.

Relation extraction operates on pairs of pre-existing entities; we therefore
do NOT mint entity ids here — every head/tail must already exist in Neo4j.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class ExtractionPhase(IntEnum):
    """Provenance of an extracted relation triple."""

    PAIR_MINED = 1     # candidate only — not yet classified
    RULE_MATCH = 2     # regex/keyword surface form match
    DOMAIN_PRIOR = 3   # listed in biblical_priors.yaml
    GROUNDED_LLM = 4   # LLM picked from schema candidate set
    INVERSE_DERIVED = 5  # auto-materialised from another relation's inverse
    ANCHORED_RULE = 6  # slot pattern over a verse, both names resolved (6.05)
    COOCCURRENCE = 7   # same-pericope co-occurrence (Step 10.3 backfill)


# Where a relation row came from. curated rows (Step 10 overlays) have no phase.
SOURCES = ("rule", "prior", "llm", "inverse", "anchored_rule", "cooccurrence", "curated")
PHASE_OF_SOURCE = {
    "rule": 2, "prior": 3, "llm": 4, "inverse": 5, "anchored_rule": 6, "cooccurrence": 7,
}
_SOURCE_OF_PHASE = {phase: source for source, phase in PHASE_OF_SOURCE.items()}

# Optional provenance keys, written after the 10 legacy keys in this order.
PROVENANCE_KEYS = (
    "source", "model", "run_id", "schema_version", "pp_version", "confidence_raw",
    "direction_verified", "sources", "support_pericopes", "evidence_count", "verse",
)


def derive_source(
    phase: Optional[int], notes: str = "", backfilled: Optional[bool] = None
) -> Optional[str]:
    """Source of a row that predates the `source` field, from its phase.

    Plain ints and strings only, so an ExtractionPhase loaded under either
    import name (scripts.relation_extraction.models / relation_extraction.models)
    maps the same. Before phase 7 existed, the 10.3 co-occurrence backfill
    wrote phase 5 with notes='cooccurrence-backfill' and backfilled=true.
    """
    if phase == 5 and (backfilled is True or notes == "cooccurrence-backfill"):
        return "cooccurrence"
    return _SOURCE_OF_PHASE.get(phase)


def _provenance_of(values: dict) -> dict:
    """Provenance keys that are not None, in PROVENANCE_KEYS order; lists copied."""
    return {
        key: list(values[key]) if isinstance(values[key], list) else values[key]
        for key in PROVENANCE_KEYS if values.get(key) is not None
    }


@dataclass
class RelationCandidate:
    """An unverified entity pair sharing context within a single pericope."""

    head_id: str
    tail_id: str
    head_type: str
    tail_type: str
    head_canonical: str
    tail_canonical: str
    source_pericope_id: str
    grounding_text: str = ""
    pair_key: str = ""

    def __post_init__(self) -> None:
        if not self.pair_key:
            a, b = sorted((self.head_id, self.tail_id))
            self.pair_key = f"{a}|{b}|{self.source_pericope_id}"


@dataclass
class ExtractedRelation:
    """Final triple ready to write to Neo4j."""

    head_id: str
    tail_id: str
    relation: str
    confidence: float
    evidence_span: str
    source_pericope_id: str
    extraction_phase: ExtractionPhase
    head_canonical: str = ""
    tail_canonical: str = ""
    notes: str = ""
    # Provenance (REL-04/REL-09); None means "not recorded" and is not written.
    source: Optional[str] = None
    model: Optional[str] = None
    run_id: Optional[str] = None
    schema_version: Optional[str] = None
    pp_version: Optional[str] = None
    confidence_raw: Optional[float] = None
    direction_verified: Optional[bool] = None
    sources: Optional[list[str]] = None
    support_pericopes: Optional[list[str]] = None
    evidence_count: Optional[int] = None
    verse: Optional[str] = None

    @property
    def effective_source(self) -> Optional[str]:
        return self.source or derive_source(int(self.extraction_phase), self.notes)

    def to_dict(self) -> dict:
        return self._legacy_dict() | _provenance_of(vars(self))

    def _legacy_dict(self) -> dict:
        return {
            "head_id": self.head_id,
            "tail_id": self.tail_id,
            "relation": self.relation,
            "confidence": round(self.confidence, 4),
            "evidence_span": self.evidence_span,
            "source_pericope_id": self.source_pericope_id,
            "extraction_phase": int(self.extraction_phase),
            "head_canonical": self.head_canonical,
            "tail_canonical": self.tail_canonical,
            "notes": self.notes,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedRelation":
        return cls(
            head_id=data["head_id"],
            tail_id=data["tail_id"],
            relation=data["relation"],
            confidence=float(data.get("confidence", 0.0)),
            evidence_span=data.get("evidence_span", ""),
            source_pericope_id=data.get("source_pericope_id", ""),
            extraction_phase=ExtractionPhase(int(data.get("extraction_phase", 1))),
            head_canonical=data.get("head_canonical", ""),
            tail_canonical=data.get("tail_canonical", ""),
            notes=data.get("notes", ""),
            **_provenance_of(data),
        )


@dataclass
class RelationSchemaEntry:
    """In-memory representation of one entry from biblical_relations.yaml."""

    name: str
    domain_types: list[str]
    range_types: list[str]
    direction: str  # "directed" | "undirected"
    inverse: Optional[str]
    description_zh: str
    prompt_signals: list[str]
    examples: list[dict] = field(default_factory=list)
    confidence_priors: dict = field(default_factory=dict)

    def confidence_for(self, phase: ExtractionPhase) -> float:
        keymap = {
            ExtractionPhase.RULE_MATCH: "rule_match",
            ExtractionPhase.DOMAIN_PRIOR: "prior",
            ExtractionPhase.GROUNDED_LLM: "llm_class",
            ExtractionPhase.INVERSE_DERIVED: "llm_class",
        }
        return float(self.confidence_priors.get(keymap.get(phase, "llm_class"), 0.5))

    def accepts_pair(self, head_type: str, tail_type: str) -> bool:
        if self.direction == "undirected":
            return (head_type in self.domain_types and tail_type in self.range_types) or (
                tail_type in self.domain_types and head_type in self.range_types
            )
        return head_type in self.domain_types and tail_type in self.range_types

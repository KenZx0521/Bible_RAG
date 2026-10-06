"""Relation rows carry their provenance; legacy rows keep their exact bytes.

REL-04/REL-09: a relation row only had extraction_phase 1–5, and phase 5 meant
both an R5 inverse and a 10.3 co-occurrence backfill, so the source of an edge
could not be read back. Phases 6 (anchored rule) and 7 (co-occurrence) are
added, a row may now carry source / run_id / model / … fields, and
derive_source maps a legacy row's phase (plus notes / backfilled) to a source.

The new keys are written after the 10 legacy keys and only when set, so every
row of today's output/relations.jsonl must still serialise to the same bytes:
the archived W1 evidence scripts and their sha256 values depend on it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from relation_extraction import models
from relation_extraction.models import ExtractedRelation, ExtractionPhase

ROOT = Path(__file__).resolve().parents[2]
RELATIONS = ROOT / "output" / "relations.jsonl"

LEGACY_KEYS = [
    "head_id", "tail_id", "relation", "confidence", "evidence_span",
    "source_pericope_id", "extraction_phase", "head_canonical",
    "tail_canonical", "notes",
]
PROVENANCE_KEYS = [
    "source", "model", "run_id", "schema_version", "pp_version",
    "confidence_raw", "direction_verified", "sources", "support_pericopes",
    "evidence_count", "verse",
]

LEGACY_LINE = (
    '{"head_id": "person:yabolahan", "tail_id": "person:yisa", '
    '"relation": "FATHER_OF", "confidence": 0.99, "evidence_span": "創 21:3", '
    '"source_pericope_id": "", "extraction_phase": 3, '
    '"head_canonical": "亞伯拉罕", "tail_canonical": "以撒", "notes": ""}'
)


def _relation(**fields) -> ExtractedRelation:
    base = dict(
        head_id="person:yabolahan", tail_id="person:yisa", relation="FATHER_OF",
        confidence=0.99, evidence_span="創 21:3", source_pericope_id="",
        extraction_phase=ExtractionPhase.DOMAIN_PRIOR,
    )
    return ExtractedRelation(**(base | fields))


def test_phase_codes_6_and_7():
    assert ExtractionPhase(6) is ExtractionPhase.ANCHORED_RULE
    assert ExtractionPhase(7) is ExtractionPhase.COOCCURRENCE
    assert [(p.name, int(p)) for p in ExtractionPhase][:5] == [
        ("PAIR_MINED", 1), ("RULE_MATCH", 2), ("DOMAIN_PRIOR", 3),
        ("GROUNDED_LLM", 4), ("INVERSE_DERIVED", 5),
    ]
    assert models.SOURCES == (
        "rule", "prior", "llm", "inverse", "anchored_rule", "cooccurrence", "curated",
    )
    assert models.PHASE_OF_SOURCE == {
        "rule": 2, "prior": 3, "llm": 4, "inverse": 5,
        "anchored_rule": 6, "cooccurrence": 7,
    }
    row = json.loads(LEGACY_LINE) | {"extraction_phase": 6}
    assert ExtractedRelation.from_dict(row).extraction_phase is ExtractionPhase.ANCHORED_RULE


def test_derive_source_by_phase_notes_and_backfill():
    derive = models.derive_source
    assert [derive(p) for p in (2, 3, 4, 5, 6, 7)] == [
        "rule", "prior", "llm", "inverse", "anchored_rule", "cooccurrence",
    ]
    assert derive(5, "derived_from=SON_OF") == "inverse"
    assert derive(5, "cooccurrence-backfill") == "cooccurrence"
    assert derive(5, "", backfilled=True) == "cooccurrence"
    assert derive(5, "", backfilled=False) == "inverse"
    # Only backfilled exactly True marks a backfill: a stray truthy value read
    # back from Neo4j or JSONL stays an R5 inverse.
    assert derive(5, "", backfilled="true") == "inverse"
    assert derive(5, "", backfilled=1) == "inverse"
    assert derive(4, "cooccurrence-backfill", backfilled=True) == "llm"
    assert [derive(p) for p in (None, 0, 1, 8)] == [None, None, None, None]
    # Pure over ints: an enum member from the other import name maps the same.
    from scripts.relation_extraction import models as models_by_package_name
    assert derive(models_by_package_name.ExtractionPhase.GROUNDED_LLM) == "llm"

    assert _relation().effective_source == "prior"
    assert _relation(source="curated").effective_source == "curated"
    inverse = _relation(extraction_phase=ExtractionPhase.INVERSE_DERIVED, notes="derived_from=SON_OF")
    assert inverse.effective_source == "inverse"
    backfill = _relation(extraction_phase=ExtractionPhase.INVERSE_DERIVED, notes="cooccurrence-backfill")
    assert backfill.effective_source == "cooccurrence"  # the notes reach derive_source


def test_legacy_row_round_trips_byte_identically():
    relation = ExtractedRelation.from_dict(json.loads(LEGACY_LINE))
    assert relation.to_jsonl() == LEGACY_LINE
    assert list(relation.to_dict()) == LEGACY_KEYS
    assert relation.source is None  # from_dict never derives a source


def test_provenance_keys_follow_legacy_keys_only_when_set():
    relation = _relation(
        verse="創 21:3", run_id="w1-test", source="prior", sources=["prior", "llm"],
        confidence_raw=0.5, direction_verified=False, evidence_count=2,
    )
    data = relation.to_dict()
    assert list(data) == LEGACY_KEYS + [
        "source", "run_id", "confidence_raw", "direction_verified", "sources",
        "evidence_count", "verse",
    ]
    assert ExtractedRelation.from_dict(data) == relation

    full = _relation(**{key: f"{key}-value" for key in PROVENANCE_KEYS})
    assert list(full.to_dict()) == LEGACY_KEYS + PROVENANCE_KEYS
    assert ExtractedRelation.from_dict(json.loads(full.to_jsonl())) == full

    data["sources"].append("inverse")
    assert relation.sources == ["prior", "llm"]  # to_dict hands out a copy
    src = relation.to_dict()
    loaded = ExtractedRelation.from_dict(src)
    src["sources"].append("x")
    assert loaded.sources == ["prior", "llm"]  # and from_dict takes one


@pytest.mark.skipif(not RELATIONS.exists(), reason="output/relations.jsonl is a gitignored build product")
def test_every_output_relations_row_round_trips():
    lines = RELATIONS.read_text(encoding="utf-8").splitlines()
    sources: Counter[str | None] = Counter()
    for line in lines:
        relation = ExtractedRelation.from_dict(json.loads(line))
        assert relation.to_jsonl() == line
        assert relation.source is None
        sources[relation.effective_source] += 1
        assert models.PHASE_OF_SOURCE[relation.effective_source] == relation.extraction_phase
    assert None not in sources and sum(sources.values()) == len(lines)

"""The committed GT v2 passes G-GT against the text layer it was frozen on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragdata.gt.build import answer_fields
from ragdata.gt.changes import get_field
from ragdata.gt.cli import DEFAULTS, gate_files
from ragdata.gt.corpus import ServiceText
from ragdata.gt.textnorm import clause_spans, norm
from ragdata.store import DEFAULT_ROOT, read_layer

UNIVERSE = json.loads(DEFAULTS["freeze"].read_text(encoding="utf-8"))["slot_universe"]
LAYER = Path(DEFAULT_ROOT) / "text" / UNIVERSE
needs_layer = pytest.mark.skipif(not LAYER.is_dir(),
                                 reason=f"text layer {UNIVERSE} not in the store")


@needs_layer
def test_committed_gt_v2_passes_g_gt():
    report = gate_files(DEFAULTS["out"], LAYER, DEFAULTS["v1"], DEFAULTS["changes"],
                        DEFAULTS["freeze"])
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    assert {g.name for g in report.gates if g.passed} >= {"G-GT.refs", "G-GT.freeze"}
    locality = next(g for g in report.gates if g.name == "G-GT.locality")
    assert not locality.hard and locality.observed["unchecked"] == 0


def _half_aligned(doc: dict, corpus: ServiceText) -> list[tuple[str, str, str]]:
    """Answer clauses that write 神 where their own gold verses write 上帝.

    Clauses under the mechanical threshold keep 神 while the rest of the field
    reads 上帝 (VERSE_LOOKUP_012, review of 2026-10-08), whether quoted or not.
    """
    found = []
    for q in doc["questions"]:
        local = corpus.local(q["gold_slots"])
        for name in answer_fields(q):
            for span in clause_spans(get_field(q, name)):
                clause = norm(span.text)
                if "神" in clause and clause not in local and clause.replace("神", "上帝") in local:
                    found.append((q["question_id"], name, span.text))
    return found


@needs_layer
def test_no_answer_clause_is_half_aligned_on_the_divine_name():
    doc = json.loads(DEFAULTS["out"].read_bytes())
    assert _half_aligned(doc, ServiceText.from_layer(read_layer(LAYER))) == []

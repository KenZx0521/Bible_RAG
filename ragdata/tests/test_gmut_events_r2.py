"""G-MUT for L1 in R2 (DOC 1 §4): each mutation of a stored events layer turns a hard gate
red, for the reason its detail names.

The mutated layer is a copy of the mini events layer with ``events.jsonl`` changed (its
contract file kept as built), gated by the runner with every required events gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_build
import mini_kg
from ragdata import store
from ragdata.gates import runner
from ragdata.kg import k1_build

MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("gmut_events")
    text, struct = mini_build.write_layers(root / "given")
    result = k1_build.build_events(text.path, struct.path, root / "store",
                                   mini_kg.write_events_yaml(root / "events.yaml"), MINI_COUNTS)
    assert result.passed
    return result.layers["events"], [text.path, struct.path]


def _gated(tmp_path, built, mutate) -> dict[str, tuple[str, ...]]:
    layer, deps = built
    data = store.read_layer(layer.path)
    rows = [json.loads(json.dumps(r)) for r in data.rows["events.jsonl"]]
    mutate(rows)
    files = {n: (data.path / n).read_bytes() for n in data.file_shas if n != store.DEPENDS_ON}
    files["events.jsonl"] = store.encode_jsonl(rows)
    copy = store.write_layer(tmp_path, "events", files, depends_on=data.depends_on)
    report = runner.gate_layer(copy.path, "events", deps, MINI_COUNTS)
    return {g.name: tuple(g.details) for g in report.gates if g.hard and not g.passed}


def _term_outside(rows):
    rows[1]["pdf_terms"].append({"text": "門徒", "at": "act.9.1", "decided_by": "kay",
                                 "provenance_class": "curated_human"})


def _alias(text):
    def mutate(rows):
        rows[1]["external_aliases"].append({**rows[1]["external_aliases"][0], "text": text})
    return mutate


CLASSES = {
    "a pdf_term outside its anchor": (_term_outside, "G-EVENT", "outside the event's anchors"),
    "an ASCII alias": (_alias("Kingdom"), "G-EVENT", "Latin letters"),
    "a continuation passage dropped": (lambda r: r[2]["anchors"].pop(), "G-EVENT",
                                       "anchors pc:act.9.3b but not its passages"),
    "a retired id without merged_into": (lambda r: r[2].update(merged_from=[]), "G-EVENT",
                                         "missing ['ev0004']"),
    "one trigger given to two events": (_alias("保羅歸主"), "G-EVENT",
                                        "trigger '保羅歸主' belongs to ev0002, ev0003"),
}


def test_the_unmutated_layer_is_green(tmp_path, built):
    assert _gated(tmp_path, built, lambda rows: None) == {}


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_each_mutation_turns_a_hard_gate_red(tmp_path, built, name):
    mutate, gate, reason = CLASSES[name]
    found = _gated(tmp_path, built, mutate)
    assert any(reason in d for d in found.get(gate, ())), found

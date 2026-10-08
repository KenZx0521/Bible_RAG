"""G-EVENT (R1 rules) and the events layer's G-COUNT over the mini rows (design §8)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import mini_build
import mini_kg
from ragdata.contract.counts import load_counts
from ragdata.contract.registry import record_type_for_file
from ragdata.gates.counts import check_counts
from ragdata.gates.events import check_event
from ragdata.gates.schema import check_schema
from ragdata.kg import k1_events

STRUCT = "struct@222222222222"
MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")
LEGACY = json.dumps(mini_kg.legacy_registry(), ensure_ascii=False).encode()


def _compiled():
    snap = check_schema(mini_build.files("text", "struct"), ("text", "struct"))[1]
    doc = k1_events.convert_registry(LEGACY, snap, STRUCT)
    return k1_events.compile_events(doc, snap, STRUCT)


def _gate(rows=None, v1=None, v2=None, legacy=LEGACY):
    compiled = _compiled()
    files = mini_build.files("text", "struct")
    files.update({f"{k}.jsonl": v for k, v in (rows or compiled.rows).items()})
    schema, snap = check_schema(files, ("text", "struct", "events"))
    assert schema.passed, schema.details
    return check_event(snap, v1 or compiled.v1, v2 or compiled.v2, legacy, STRUCT), snap


def test_mini_events_pass_g_event_and_g_count():
    result, snap = _gate()
    assert result.passed, result.details
    counts = check_counts(snap, "events", load_counts(MINI_COUNTS)["events"])
    assert counts.passed, counts.details


def _rows(mutate):
    rows = copy.deepcopy(dict(_compiled().rows))
    mutate(rows)
    return rows


MUTATIONS = {
    "event id gap": lambda r: r["events"][2].update(event_id="ev0004"),
    "anchor curated in R1": lambda r: r["events"][0]["anchors"][0].update(
        provenance_class="curated_human"),
    "pdf term in R1": lambda r: r["events"][0]["pdf_terms"].append({"text": "渴慕"}),
    "external alias in R1": lambda r: r["events"][0]["external_aliases"].append({"text": "x"}),
    "trigger dropped": lambda r: r["events"][1]["legacy_triggers"].pop(),
    "no triggers": lambda r: r["events"][0].update(legacy_triggers=[]),
    "trigger renamed": lambda r: r["events"][0]["legacy_triggers"][0].update(text="渴想"),
    "anchor moved": lambda r: r["events"][0]["anchors"][0].update(
        passage_id="ps:sng.1.1", start_key="sng.1.1", end_key="sng.1.1", start_slot="sng.1.1",
        end_slot="sng.1.1"),
    "anchor to a missing slot": lambda r: r["events"][0]["anchors"][0].update(
        end_key="psa.42.9", end_slot="psa.42.9"),
    "change list misses one": lambda r: r["anchor_changes"].pop(),
    "event renamed": lambda r: r["events"][0].update(name="渴慕"),
}


@pytest.mark.parametrize("case", sorted(MUTATIONS))
def test_mutations_turn_g_event_red(case):
    result, _ = _gate(_rows(MUTATIONS[case]))
    assert not result.passed, case


def test_contract_files_must_follow_the_records():
    compiled = _compiled()
    v1 = copy.deepcopy(compiled.v1)
    v1["events"][0]["anchors"] = ["psa:42:0"]
    assert not _gate(v1=v1)[0].passed
    v2 = copy.deepcopy(compiled.v2)
    v2["events"][0]["anchors"][0]["start_slot"] = "psa.42.2"
    assert not _gate(v2=v2)[0].passed


def test_frozen_check_needs_the_legacy_registry():
    result, _ = _gate(legacy=None)
    assert not result.passed and "legacy registry" in " ".join(result.details)
    other = mini_kg.legacy_registry()
    other["events"][0]["triggers"] = ["渴慕", "渴想"]
    result, _ = _gate(legacy=json.dumps(other, ensure_ascii=False).encode())
    assert not result.passed


def test_events_layer_files_are_record_types():
    assert record_type_for_file("events.jsonl").layer == "events"
    assert record_type_for_file("anchor_changes.jsonl").layer == "events"

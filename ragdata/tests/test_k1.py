"""K1: the R1 event registry, converted from the legacy registry and compiled (§2.21, §5.3)."""

from __future__ import annotations

import copy
import json

import pytest

import mini_build
import mini_kg
from ragdata.gates.schema import check_schema
from ragdata.kg import k1_events
from ragdata.kg.k1_events import EventRegistryError

STRUCT = "struct@222222222222"


def _snapshot(struct=None):
    files = mini_build.files("text", "struct")
    if struct is not None:
        files.update({f"{k}.jsonl": v for k, v in struct.items()})
    return check_schema(files, ("text", "struct"))[1]


def _legacy_bytes(doc=None):
    return json.dumps(doc or mini_kg.legacy_registry(), ensure_ascii=False).encode()


def _converted(doc=None, snapshot=None):
    return k1_events.convert_registry(_legacy_bytes(doc), snapshot or _snapshot(), STRUCT)


def test_conversion_then_compilation_gives_the_oracle():
    doc = _converted()
    assert doc["source"]["sha256"] == mini_kg.legacy_sha()
    result = k1_events.compile_events(doc, _snapshot(), STRUCT)
    assert dict(result.rows) == mini_kg.events_layer(STRUCT)


def test_the_yaml_round_trips(tmp_path):
    doc = _converted()
    path = tmp_path / "events.yaml"
    path.write_text(k1_events.dump_events_yaml(doc), encoding="utf-8")
    assert k1_events.load_events_yaml(path) == doc


def test_v1_keeps_the_backend_shape_with_passage_ids():
    result = k1_events.compile_events(_converted(), _snapshot(), STRUCT)
    legacy = mini_kg.legacy_registry()
    assert set(result.v1) == set(legacy)
    assert result.v1["dropped"] == legacy["dropped"]
    assert result.v1["events"][2] == {"id": "event:saoluo", "name": "掃羅歸主",
                                      "provenance": "manual_edges", "triggers": ["保羅歸主"],
                                      "anchors": ["ps:act.9.1", "ps:act.9.3b"]}


def test_v2_carries_ids_slot_ranges_and_provenance():
    result = k1_events.compile_events(_converted(), _snapshot(), STRUCT)
    first = result.v2["events"][0]
    assert result.v2["schema"] == k1_events.V2_SCHEMA and result.v2["struct"] == STRUCT
    assert first["event_id"] == "ev0001" and first["legacy_id"] == "event:kemu"
    assert first["anchors"][0]["start_slot"] == "psa.42.1"
    assert first["anchors"][0]["provenance_class"] == "legacy_tuned"
    assert first["legacy_triggers"][0]["retire_by"] == "R2"
    assert result.report["counts"] == {"events": 3, "anchors": 4, "passages": 4, "same": 2,
                                       "narrowed": 1, "widened": 1, "legacy_triggers": 4}
    assert result.report["v1_vs_v2"]


def test_an_unknown_legacy_anchor_is_refused():
    doc = mini_kg.legacy_registry()
    doc["events"][0]["anchors"] = ["psa:41:0"]
    with pytest.raises(EventRegistryError, match="psa:41:0"):
        _converted(doc)


def test_a_split_legacy_anchor_is_refused():
    struct = mini_build.struct_layer()
    row = next(r for r in struct["legacy_ids"] if r["legacy_id"] == "psa:42:0")
    row.update(relation="split", new_ids=["ps:psa.42.1", "ps:sng.1.1"])
    with pytest.raises(EventRegistryError, match="one passage"):
        _converted(snapshot=_snapshot(struct))


def test_a_legacy_range_the_passage_does_not_cover_is_refused():
    struct = mini_build.struct_layer()
    row = next(r for r in struct["legacy_ids"] if r["legacy_id"] == "act:9:1")
    row.update(start_slot="act.9.2")
    with pytest.raises(EventRegistryError, match="neither"):
        _converted(snapshot=_snapshot(struct))


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["events"][0]["anchors"][0].update(change="widened"), "conversion gives"),
    (lambda d: d["events"][0]["anchors"][0].update(passage_id="ps:sng.1.1"), "conversion gives"),
    (lambda d: d["events"][1].update(event_id="ev0009"), "ev0002"),
    (lambda d: d["events"][0].update(legacy_triggers=[]), "trigger"),
    (lambda d: d.update(schema="x"), "schema"),
    (lambda d: d["events"][0].pop("name"), "keys"),
])
def test_compile_refuses_a_registry_that_drifted_from_the_conversion(mutate, message):
    doc = copy.deepcopy(_converted())
    mutate(doc)
    with pytest.raises(EventRegistryError, match=message):
        k1_events.compile_events(doc, _snapshot(), STRUCT)


def test_unreadable_legacy_registry_is_refused():
    with pytest.raises(EventRegistryError, match="legacy registry"):
        k1_events.convert_registry(b"{", _snapshot(), STRUCT)


def test_report_lists_same_anchors_that_end_on_a_half_verse():
    result = k1_events.compile_events(_converted(), _snapshot(), STRUCT)
    assert result.report["same_with_half_verse"] == [
        {"event_id": "ev0003", "legacy_anchor": "act:9:1", "passage_id": "ps:act.9.3b"}]

"""K1, R2: events.yaml v2 compiled against the struct layer (§2.21, §5.3, R2 contract spec §2)."""

from __future__ import annotations

import copy
import hashlib

import pytest

import mini_build
import mini_kg
from ragdata import paths
from ragdata.gates.schema import check_schema
from ragdata.kg import k1_events
from ragdata.kg.k1_events import EventRegistryError

STRUCT = "struct@222222222222"


def _snapshot():
    return check_schema(mini_build.files("text", "struct"), ("text", "struct"))[1]


def _compiled(doc=None):
    return k1_events.compile_events(doc or mini_kg.events_yaml(), _snapshot(), STRUCT,
                                    "events@000000000000")


def test_compilation_gives_the_oracle():
    assert dict(_compiled().rows) == mini_kg.events_layer()


def test_a_pericope_expands_into_all_its_passages_with_its_heading_as_evidence():
    saoluo = _compiled().rows["events"][2]
    assert [(a["pericope_id"], a["passage_id"]) for a in saoluo["anchors"]] == [
        ("pc:act.9.1", "ps:act.9.1"), ("pc:act.9.3b", "ps:act.9.3b"),
        ("pc:act.9.3b", "ps:act.10.1")]
    assert {a["evidence"]["heading_id"] for a in saoluo["anchors"][1:]} == {"hd:act.9.3b#1"}


def test_the_contract_projects_the_records_and_lists_retired_events():
    v2 = _compiled().v2
    assert (v2["schema"], v2["variant"], v2["struct"]) == ("ragdata.event_registry.v2", "R2",
                                                          STRUCT)
    assert v2["retired"] == [{"event_id": "ev0004", "legacy_ids": ["event:saoluo2"],
                              "merged_into": "ev0003"}]
    first = v2["events"][0]
    assert set(first) == {"event_id", "legacy_ids", "name", "name_source", "name_heading_id",
                          "anchors", "pdf_terms", "external_aliases"}
    assert first["anchors"] == mini_kg.events()[0]["anchors"]


def test_the_report_counts_and_lists_the_expanded_pericopes():
    report = _compiled().report
    assert report["registry"] == "events@000000000000" and report["struct"] == STRUCT
    assert report["counts"] == {"events": 4, "anchors": 6, "passages": 6,
                                "pericope_declarations": 5, "pericopes": 5, "pdf_terms": 3,
                                "external_aliases": 3, "retired": 1}
    assert report["expanded"] == [{"event_id": "ev0003", "pericope_id": "pc:act.9.3b",
                                   "passage_ids": ["ps:act.9.3b", "ps:act.10.1"]}]


def test_load_events_yaml_names_the_file_bytes(tmp_path):
    path = mini_kg.write_events_yaml(tmp_path / "events.yaml")
    doc, version = k1_events.load_events_yaml(path)
    assert doc == mini_kg.events_yaml()
    assert version == f"events@{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"


def _event(doc, n):
    return doc["events"][n]


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema="ragdata.events.v1"), "schema"),
    (lambda d: d.update(variant="R1"), "variant"),
    (lambda d: d.update(source={}), "keys"),
    (lambda d: d["external_alias_defaults"].pop("note"), "external_alias_defaults"),
    (lambda d: d["retired"][0].pop("merged_into"), r"retired\[0\]"),
    (lambda d: d["retired"][0].update(merged_into="ev0009"), "names no event"),
    (lambda d: _event(d, 0).update(legacy_triggers=["渴慕"]), "keys"),
    (lambda d: _event(d, 0).update(anchors="pc:psa.42.1"), "must be a list"),
    (lambda d: _event(d, 0).update(anchors=["pc:psa.41.1"]), "struct-layer pericope"),
    (lambda d: _event(d, 3).update(anchors=["pc:sng.1.1"]), "declare a quote"),
    (lambda d: _event(d, 3).update(anchors=[{"pericope": "pc:sng.1.1"}]), "keys"),
    (lambda d: _event(d, 2).update(anchors=["pc:act.9.3b", "pc:act.9.1"]), "canon order"),
    (lambda d: _event(d, 2).update(anchors=["pc:act.9.1", "pc:act.9.1"]), "once each"),
    (lambda d: _event(d, 0)["pdf_terms"][0].update(decided_by="kay"), "pdf_terms"),
    (lambda d: _event(d, 1)["external_aliases"][0].pop("text"), "external_aliases"),
])
def test_compile_refuses_what_it_cannot_compile(mutate, message):
    doc = copy.deepcopy(mini_kg.events_yaml())
    mutate(doc)
    with pytest.raises(EventRegistryError, match=message):
        _compiled(doc)


def test_the_committed_registry_is_the_approved_r2_content():
    """config/registries/events.yaml: Kay 2026-10-08 (DOC 2), before any build checks it."""
    doc, _ = k1_events.load_events_yaml(paths.EVENTS_REGISTRY)
    k1_events._check_doc(doc)
    events = doc["events"]
    assert len(events) == 31 and [r["event_id"] for r in doc["retired"]] == ["ev0003", "ev0014"]
    assert sum(len(e["anchors"]) for e in events) == 176
    assert sum(len(e["pdf_terms"]) for e in events) == 12
    assert sum(len(e["external_aliases"]) for e in events) == 25
    curated = [e["event_id"] for e in events if "name_heading_id" not in e]
    assert curated == ["ev0009", "ev0012", "ev0019", "ev0020"]

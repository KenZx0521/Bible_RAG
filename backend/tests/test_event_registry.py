"""Event registry auxiliary lane, read from the build's contract (event_registry.json, R2).

An event fires on one of its triggers (pdf_terms, then external aliases) literally
in the question (book names masked); its anchors are passage ids; it is reported
by its ev id. The lane appends one anchor the top-k lacks, after the finished
top-k, on R4/R5 only. The registry here is written in the contract's shape (§2.1).
"""

import json
from pathlib import Path

import pytest

from utils.retrieval import event_registry as reg

R1_REGISTRY = (Path(__file__).resolve().parent / "fixtures" / "r1_contracts"
               / "b20261008_1bb6912e" / "event_registry.json")
BOOKS = ("使徒行傳", "以弗所書", "約翰一書", "約翰福音")


def _anchor(key: str, end: str) -> dict:
    return {"pericope_id": f"pc:{key}", "passage_id": f"ps:{key}", "start_key": key,
            "end_key": end, "start_slot": key.rstrip("b"), "end_slot": end,
            "evidence": {"heading_id": f"hd:{key}#1", "quote": None},
            "provenance_class": "curated_human", "decided_by": "kay"}


def _event(event_id, legacy_ids, name, anchors, pdf_terms=(), aliases=()) -> dict:
    return {"event_id": event_id, "legacy_ids": list(legacy_ids), "name": name,
            "name_source": "curated", "name_heading_id": None, "anchors": list(anchors),
            "pdf_terms": [{"text": t, "at": "act.2.1", "decided_by": "kay",
                           "provenance_class": "curated_human"} for t in pdf_terms],
            "external_aliases": [{"text": t, "source": "test", "note": "test",
                                  "provenance_class": "external_event_alias"} for t in aliases]}


def _doc() -> dict:
    return {"schema": reg.SCHEMA, "variant": "R2", "struct": "struct@000000000000",
            "events": [
                _event("ev0002", ["event:a", "event:b", "event:c"], "掃羅的轉變",
                       [_anchor("act.9.1", "act.9.3a"), _anchor("act.9.3b", "act.9.9")],
                       aliases=["保羅歸主"]),
                _event("ev0022", ["event:d"], "聖靈降臨", [_anchor("act.2.1", "act.2.13")],
                       pdf_terms=["五旬節", "聖靈降臨"], aliases=["聖靈澆灌"]),
                _event("ev0031", ["event:e"], "逾越節", [_anchor("exo.12.1", "exo.12.28")])],
            "retired": [{"event_id": "ev0003", "legacy_ids": ["event:b"], "merged_into": "ev0002"}]}


def _ev(eid, triggers, anchors):
    return reg.RegistryEvent(id=eid, legacy_ids=(), name=eid, triggers=tuple(triggers),
                             anchors=tuple(anchors))


def test_the_registry_parses_with_ev_ids_triggers_and_passage_anchors():
    events = reg.parse_registry(_doc())

    assert [e.id for e in events] == ["ev0002", "ev0022", "ev0031"]
    assert events[0].legacy_ids == ("event:a", "event:b", "event:c")
    assert events[0].anchors == ("ps:act.9.1", "ps:act.9.3b")
    assert events[1].triggers == ("五旬節", "聖靈降臨", "聖靈澆灌")


def test_an_event_without_triggers_is_kept_and_never_fires():
    events = reg.parse_registry(_doc())

    assert events[2].triggers == () and events[2].anchors == ("ps:exo.12.1",)
    assert reg.match_events("逾越節的羔羊", events, BOOKS) == []


def test_a_trigger_listed_twice_counts_once():
    doc = _doc()
    doc["events"][1]["external_aliases"][0]["text"] = "五旬節"

    assert reg.parse_registry(doc)[1].triggers == ("五旬節", "聖靈降臨")


def test_anchor_passages_are_listed_for_the_startup_check():
    events = reg.parse_registry(_doc())

    assert reg.anchor_passages(events) == ("ps:act.9.1", "ps:act.9.3b", "ps:act.2.1",
                                           "ps:exo.12.1")


def _set(path, value):
    def mutate(doc):
        *parents, last = path
        node = doc
        for key in parents:
            node = node[key]
        node[last] = value
    return mutate


@pytest.mark.parametrize("mutate, message", [
    (_set(["schema"], "ragdata.event_registry.v1"), "schema"),
    (_set(["variant"], "R1"), "variant must be R2"),
    (_set(["events", 0, "legacy_triggers"], [{"text": "保羅歸主"}]), "legacy triggers"),
    (_set(["events", 0, "anchors", 0, "provenance_class"], "external_legacy"), "legacy provenance"),
    (_set(["events", 0, "anchors"], []), "anchors"),
    (_set(["events", 0, "anchors", 0, "passage_id"], "psa:42:0"), "passage"),
    (_set(["events", 0, "event_id"], "event:saoluo"), "not an event id"),
    (_set(["events", 1, "event_id"], "ev0002"), "duplicate"),
    (_set(["events", 0, "pdf_terms"], [{"at": "act.9.1"}]), "text"),
    (_set(["events", 0, "external_aliases"], None), "not a list"),
    (_set(["events", 0, "name"], ""), "name"),
    (_set(["events"], "none"), "events"),
    (_set(["retired"], None), "retired"),
    (_set(["retired", 0, "merged_into"], "ev0099"), "names no event"),
])
def test_a_malformed_registry_raises(mutate, message):
    doc = _doc()
    mutate(doc)

    with pytest.raises(reg.RegistryError, match=message):
        reg.parse_registry(doc)


def test_an_r1_registry_is_refused():
    doc = json.loads(R1_REGISTRY.read_text(encoding="utf-8"))

    with pytest.raises(reg.RegistryError, match="variant must be R2, got 'R1'"):
        reg.parse_registry(doc)
    with pytest.raises(reg.RegistryError, match="legacy"):
        reg.parse_registry({**doc, "variant": "R2"})


def test_an_empty_registry_is_legal():
    assert reg.parse_registry({**_doc(), "events": [], "retired": []}) == ()


def test_book_names_are_masked_before_matching():
    events = (_ev("e:john", ["約翰"], ["ps:jhn.1.1"]),)

    assert reg.match_events("約翰福音第一章說什麼", events, BOOKS) == []
    assert reg.match_events("約翰在哪裡施洗", events, BOOKS) == [events[0]]
    assert reg.mask_book_names("約翰一書與約翰福音", BOOKS) == "□□□□與□□□□"


def test_most_specific_event_first():
    wide = _ev("e:wide", ["天國"], ["ps:mat.5.1", "ps:mat.13.1"])
    narrow = _ev("e:narrow", ["最大"], ["ps:mat.18.1"])

    assert reg.match_events("天國裏誰最大", (wide, narrow), BOOKS) == [narrow, wide]


def test_aux_picks_the_first_anchor_the_core_lacks():
    events = [_ev("e:a", ["x"], ["ps:act.9.1", "ps:act.9.3b"]), _ev("e:b", ["y"], ["ps:mat.18.1"])]

    assert reg.select_aux_anchors(events, ["ps:act.9.1"], 1) == [("e:a", "ps:act.9.3b")]
    assert reg.select_aux_anchors(events, [], 2) == [("e:a", "ps:act.9.1"), ("e:b", "ps:mat.18.1")]
    assert reg.select_aux_anchors(events, ["ps:act.9.1", "ps:act.9.3b", "ps:mat.18.1"], 2) == []

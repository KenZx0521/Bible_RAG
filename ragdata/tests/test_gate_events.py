"""G-EVENT (R2 rules), and G-COUNT, G-PROV and G-SCHEMA on the events layer, over the mini
rows (design §8; DOC 1 §4)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import mini_build
import mini_kg
from ragdata.contract import ContractError, parse_record
from ragdata.contract.counts import load_counts
from ragdata.contract.registry import record_type_for_file
from ragdata.gates.counts import check_counts
from ragdata.gates.events import check_event
from ragdata.gates.prov import check_prov
from ragdata.gates.schema import check_schema
from ragdata.kg.k1_contracts import v2_doc

STRUCT = "struct@222222222222"
MINI_COUNTS = Path(__file__).with_name("mini_counts.yaml")


def _gate(events=None, v2=None):
    events = mini_kg.events() if events is None else events
    files = mini_build.files("text", "struct")
    files["events.jsonl"] = events
    schema, snap = check_schema(files, ("text", "struct", "events"))
    assert schema.passed, schema.details
    return check_event(snap, v2_doc(events, STRUCT) if v2 is None else v2, STRUCT), snap


def test_mini_events_pass_g_event_g_count_and_g_prov():
    result, snap = _gate()
    assert result.passed, result.details
    counts = check_counts(snap, "events", load_counts(MINI_COUNTS)["events"])
    assert counts.passed, counts.details
    assert check_prov({"events.jsonl": mini_kg.events()}).passed


def test_an_empty_registry_is_legal():
    result, _ = _gate([])
    assert result.passed, result.details


def _anchor(rows, event, passage):
    return next(a for a in rows[event]["anchors"] if a["passage_id"] == passage)


def _add_term(rows, event, text, at):
    rows[event]["pdf_terms"].append({"text": text, "at": at, "decided_by": "kay",
                                     "provenance_class": "curated_human"})


def _add_alias(rows, event, text):
    rows[event]["external_aliases"].append({**mini_kg.events()[1]["external_aliases"][0],
                                            "text": text})


MUTATIONS = {
    # 1 ids
    "ids descend": (lambda r: r.insert(0, r.pop(1)), "do not ascend"),
    "retired id dropped": (lambda r: r[2].update(merged_from=[]), "are not ev0001…ev0004"),
    "retired id is an event": (lambda r: r[2]["merged_from"][0].update(event_id="ev0001"),
                               "listed 2 times"),
    "legacy id shared": (lambda r: r[1]["legacy_ids"].append("event:kemu"),
                         "belongs to 2 events"),
    # 2 anchors
    "anchor decided by another": (lambda r: _anchor(r, 0, "ps:psa.42.1").update(
        decided_by="ai"), "decided_by 'ai'"),
    "anchor keys not the passage's": (lambda r: _anchor(r, 0, "ps:psa.42.1").update(
        end_key="psa.42.2", end_slot="psa.42.2"), "keys and slots"),
    "anchor in another pericope": (lambda r: _anchor(r, 0, "ps:psa.42.1").update(
        pericope_id="pc:mat.18.1"), "is not pc:psa.42.1"),
    "fragment heading as evidence": (lambda r: _anchor(r, 2, "ps:act.9.1")["evidence"].update(
        heading_id="hd:act.9.3b#1"), "is not a heading of pc:act.9.1"),
    "quote outside its pericope": (lambda r: _anchor(r, 3, "ps:sng.1.1")["evidence"]["quote"]
                                   .update(unit_key="eph.6.1"), "is not in pc:sng.1.1"),
    "quote not in its unit": (lambda r: _anchor(r, 3, "ps:sng.1.1")["evidence"]["quote"]
                              .update(text="渴慕"), "is not in sng.1.1"),
    "anchors out of canon order": (lambda r: r[2]["anchors"].reverse(), "canon order"),
    # 3 completeness
    "continuation passage dropped": (lambda r: r[2]["anchors"].pop(), "but not its passages"),
    # 4 name
    "name is not its heading": (lambda r: r[0].update(name="渴慕"), "is not the text of"),
    "name heading of another passage": (lambda r: r[1].update(
        name="渴慕上帝", name_heading_id="hd:psa.42.1#1"), "not a heading of its anchors"),
    # 5 pdf_terms
    "pdf_term decided by another": (lambda r: r[0]["pdf_terms"][0].update(decided_by="ai"),
                                    "decided_by 'ai'"),
    "pdf_term outside its anchors": (lambda r: _add_term(r, 1, "門徒", "act.9.1"),
                                     "outside the event's anchors"),
    "pdf_term not at its location": (lambda r: r[0]["pdf_terms"][1].update(text="渴想"),
                                     "not a substring of psa.42.1"),
    "pdf_term at a missing unit": (lambda r: r[0]["pdf_terms"][1].update(at="psa.42.9"),
                                   "not in the text layer"),
    # 6 external aliases
    "alias with a blank note": (lambda r: r[1]["external_aliases"][0].update(note=" "),
                                "blank source or note"),
    # 7 triggers
    "ASCII alias": (lambda r: _add_alias(r, 1, "Kingdom"), "Latin letters"),
    "one-character trigger": (lambda r: _add_alias(r, 1, "國"), "one character"),
    "trigger given to two events": (lambda r: _add_alias(r, 1, "保羅歸主"),
                                    "belongs to ev0002, ev0003"),
}


@pytest.mark.parametrize("case", sorted(MUTATIONS))
def test_each_rule_turns_g_event_red(case):
    mutate, reason = MUTATIONS[case]
    rows = copy.deepcopy(mini_kg.events())
    mutate(rows)
    result, _ = _gate(rows, v2_doc(rows, STRUCT))
    assert not result.passed and any(reason in d for d in result.details), result.details


def test_a_pdf_term_may_quote_the_pdf_text_of_an_erratum():
    rows = copy.deepcopy(mini_kg.events())
    _add_term(rows, 2, "詵過小河", "act.9.3")     # text_pdf; the corrected text has 蹚
    _add_term(rows, 2, "蹚過小河", "act.9.3")
    result, _ = _gate(rows)
    assert result.passed, result.details


def test_the_contract_file_must_follow_the_records():
    v2 = v2_doc(mini_kg.events(), STRUCT)
    v2["retired"][0].pop("merged_into")
    result, _ = _gate(v2=v2)
    assert "does not follow the event records" in " ".join(result.details)
    assert not _gate(v2=v2_doc(mini_kg.events(), "struct@333333333333"))[0].passed


@pytest.mark.parametrize("where", [
    lambda e: e, lambda e: e["anchors"][0], lambda e: e["pdf_terms"][0],
])
@pytest.mark.parametrize("legacy", ["external_legacy", "legacy_tuned"])
def test_the_contract_refuses_legacy_provenance_anywhere(where, legacy):
    event = copy.deepcopy(mini_kg.events()[0])
    where(event)["provenance_class"] = legacy
    with pytest.raises(ContractError, match="provenance_class"):
        parse_record("events", event)


@pytest.mark.parametrize("mutate, message", [
    (lambda e: e.update(legacy_triggers=[]), "unknown"),
    (lambda e: e.update(name_source="curated"), "name_heading_id iff"),
    (lambda e: e["pdf_terms"].append(dict(e["pdf_terms"][0])), "trigger texts repeat"),
    (lambda e: e["anchors"][0]["evidence"].update(quote={"unit_key": "psa.42.1", "text": "x"}),
     "exactly one"),
    (lambda e: e["pdf_terms"][0].update(at="pc:psa.42.1"), "heading id or a unit key"),
    (lambda e: e.update(merged_from=[{"event_id": "ev0009", "legacy_ids": ["event:x"]}]),
     "merged event's legacy ids"),
])
def test_the_event_record_contract(mutate, message):
    event = copy.deepcopy(mini_kg.events()[0])
    mutate(event)
    with pytest.raises(ContractError, match=message):
        parse_record("events", event)


def test_g_prov_takes_a_curated_event_row_s_coordinate_from_its_anchors():
    event = copy.deepcopy(mini_kg.events()[3])
    assert check_prov({"events.jsonl": [event]}).passed
    for a in event["anchors"]:
        a.update(passage_id=None, start_slot=None)
    assert "curated_human needs coordinate" in " ".join(
        check_prov({"events.jsonl": [event]}).details)


def test_events_layer_has_one_record_type():
    assert record_type_for_file("events.jsonl").layer == "events"
    assert record_type_for_file("anchor_changes.jsonl") is None

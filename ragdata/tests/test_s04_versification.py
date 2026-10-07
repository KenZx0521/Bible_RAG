"""S4 ref_aliases: external verse numbers without a PDF slot, checked against the text layer."""

from __future__ import annotations

import pytest
import yaml

from ragdata.contract import parse_record
from ragdata.stages.s04_overlay import versification as vs
from ragdata.stages.s04_overlay.errata import OverlayError

ALIAS = {"external_ref": "jhn.7.53", "relation": "contained_in", "target": "jhn.8.1",
         "target_starts_with": "於是各人都回家去了；", "note": "PDF 把 7:53 併進 8:1"}


def _rows(max_verse=52, first="於是各人都回家去了；耶穌卻往橄欖山去，", status="present"):
    return {
        "chapters": [{"chapter_key": "jhn.7", "max_verse": max_verse},
                     {"chapter_key": "jhn.8", "max_verse": 59}],
        "verse_slots": [{"slot_key": "jhn.8.1", "unit_key": "jhn.8.1", "status": status}],
        "verse_units": [{"unit_key": "jhn.8.1", "text_pdf": first}],
    }


def _load(tmp_path, aliases=(ALIAS,)):
    path = tmp_path / "versification.yaml"
    doc = {"schema": "ragdata.versification.v1", "aliases": list(aliases)}
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return vs.load_aliases(path)


def test_an_alias_whose_evidence_holds_becomes_a_ref_aliases_row(tmp_path):
    rows = vs.alias_rows(_rows(), _load(tmp_path), {"jhn"})
    assert rows == ({"external_ref": "jhn.7.53", "relation": "contained_in", "target": "jhn.8.1",
                     "note": "PDF 把 7:53 併進 8:1", "provenance_class": "external_reference"},)
    parse_record("ref_aliases", rows[0])


def test_aliases_of_books_outside_the_build_are_skipped(tmp_path):
    assert vs.alias_rows(_rows(), _load(tmp_path), {"mat"}) == ()


@pytest.mark.parametrize("rows, message", [
    (_rows(max_verse=53), "is a PDF slot"),
    (_rows(first="耶穌卻往橄欖山去，"), "does not start"),
    (_rows(status="omitted_variant"), "not a present slot"),
    ({**_rows(), "verse_slots": []}, "not a present slot"),
    ({**_rows(), "chapters": []}, "no chapter"),
    ({**_rows(), "verse_units": []}, "no unit"),
], ids=["slot exists", "text", "omitted", "missing slot", "missing chapter", "missing unit"])
def test_an_alias_the_text_layer_contradicts_is_refused(tmp_path, rows, message):
    with pytest.raises(OverlayError, match=message):
        vs.alias_rows(rows, _load(tmp_path), {"jhn"})


@pytest.mark.parametrize("alias, message", [
    ({**ALIAS, "relation": "same_as"}, "relation"),
    ({**ALIAS, "external_ref": "jhn.7"}, "slot key"),
    ({**ALIAS, "target_starts_with": ""}, "target_starts_with"),
], ids=["relation", "external ref", "evidence"])
def test_a_malformed_alias_is_refused(tmp_path, alias, message):
    with pytest.raises(OverlayError, match=message):
        _load(tmp_path, [alias])


def test_a_duplicate_alias_is_refused(tmp_path):
    with pytest.raises(OverlayError, match="twice"):
        _load(tmp_path, [ALIAS, ALIAS])


def test_the_registry_in_config_loads():
    assert vs.load_aliases()


def test_an_alias_that_is_not_a_mapping_is_refused(tmp_path):
    with pytest.raises(OverlayError, match="mapping"):
        _load(tmp_path, ["jhn.7.53"])

"""S4 normalization registry: the rules are declared, counted and never rewrite text."""

from __future__ import annotations

import pytest
import yaml

from ragdata.stages.s04_overlay import normalization as nm
from ragdata.stages.s04_overlay.errata import OverlayError

DOC = {
    "schema": "ragdata.normalization.v1",
    "rules": [
        {"id": "N1", "stage": "S2", "what": "換行空白", "applies_to": ["verse_units"],
         "reversible_by": "verse_units.line_breaks"},
        {"id": "N3", "stage": "S4", "what": "NFC", "applies_to": ["verse_units"],
         "reversible_by": "不改寫"},
    ],
    "ascii_allowed": {"verse_units": {"chars": ".*", "why": "刪節號"}},
}


def _load(tmp_path, doc=DOC):
    path = tmp_path / "normalization.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return nm.load_normalization(path)


def test_the_allow_list_is_a_set_of_characters_per_record_type(tmp_path):
    norm = _load(tmp_path)
    assert norm.ascii_allowed == {"verse_units": frozenset(".*")}
    assert [r.id for r in norm.rules] == ["N1", "N3"]


def test_the_report_counts_each_rule_on_the_built_rows(tmp_path):
    rows = {"verse_units": [{"text_pdf": "甲乙", "text": "甲乙",
                             "line_breaks": [{"offset": 1, "kind": "soft"}]}],
            "footnotes": [{"text_pdf": "註", "text": "註"}]}
    report = nm.report(_load(tmp_path), rows)
    assert [(r["id"], r["applied"]) for r in report["rules"]] == [("N1", 1), ("N3", 0)]
    assert report["ascii_allowed"] == {"verse_units": "*."}


def test_a_non_nfc_string_is_counted_not_rewritten(tmp_path):
    rows = {"verse_units": [{"text_pdf": "Á", "text": "Á", "line_breaks": []}]}
    report = nm.report(_load(tmp_path), rows)
    assert report["rules"][1]["applied"] == 1 and rows["verse_units"][0]["text"] == "Á"


def _bad(**changes):
    doc = yaml.safe_load(yaml.safe_dump(DOC, allow_unicode=True))
    doc.update(changes)
    return doc


@pytest.mark.parametrize("doc, message", [
    (_bad(schema="x"), "schema"),
    (_bad(rules=[{**DOC["rules"][0], "id": "N9"}]), "N9"),
    (_bad(rules=[DOC["rules"][0], DOC["rules"][0]]), "twice"),
    (_bad(rules=[{"id": "N1"}]), "reversible_by"),
    (_bad(ascii_allowed={"verse_units": {"chars": "。", "why": "x"}}), "ASCII"),
    (_bad(ascii_allowed={"nope": {"chars": ".", "why": "x"}}), "nope"),
    (_bad(ascii_allowed={"verse_units": {"chars": "."}}), "why"),
    (_bad(rules=["N1"]), "mapping"),
], ids=["schema", "unknown rule", "duplicate", "incomplete", "non-ascii", "type", "no why",
        "rule not a mapping"])
def test_a_malformed_registry_is_refused(tmp_path, doc, message):
    with pytest.raises(OverlayError, match=message):
        _load(tmp_path, doc)


def test_the_registry_in_config_loads():
    assert nm.load_normalization().rules

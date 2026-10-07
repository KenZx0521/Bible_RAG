"""S4 as one step: errata, ref_aliases and the normalization record over the S2 rows."""

from __future__ import annotations

import hashlib

import yaml

from ragdata.stages import s04_overlay


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _registries(tmp_path):
    docs = {
        "errata.yaml": {"schema": "ragdata.errata.v1", "class": "big5_e04x_misglyph",
                        "decided_by": "claude", "not_errata": {},
                        "misglyphs": {"詵": {"big5": "E04D", "status": "apply", "corrected": "蹚",
                                             "word": "蹚水", "why": "涉水"}},
                        "entries": [{"id": "er:0001", "container": "jhn.8.2", "offset": 0,
                                     "pdf": "詵", "fix": "蹚"}]},
        "versification.yaml": {"schema": "ragdata.versification.v1", "aliases": [
            {"external_ref": "jhn.7.53", "relation": "contained_in", "target": "jhn.8.1",
             "target_starts_with": "於是", "note": "併入 8:1"}]},
        "normalization.yaml": {"schema": "ragdata.normalization.v1", "rules": [
            {"id": "N1", "stage": "S2", "what": "換行空白", "applies_to": ["verse_units"],
             "reversible_by": "line_breaks"}], "ascii_allowed": {}},
    }
    for name, doc in docs.items():
        (tmp_path / name).write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _rows():
    units = [{"unit_key": k, "book_id": "jhn", "text_pdf": t, "text": t, "text_sha256": _sha(t),
              "errata_ids": [], "line_breaks": [{"offset": 1, "kind": "soft"}]}
             for k, t in (("jhn.8.1", "於是各人"), ("jhn.8.2", "詵過水"))]
    return {"books": [{"book_id": "jhn"}],
            "chapters": [{"chapter_key": "jhn.7", "max_verse": 52},
                         {"chapter_key": "jhn.8", "max_verse": 2}],
            "verse_slots": [{"slot_key": "jhn.8.1", "unit_key": "jhn.8.1", "status": "present"}],
            "verse_units": units, "footnotes": [], "headings": [], "chapter_texts": [],
            "speakers": [], "parallel_refs": []}


def test_the_overlay_finalises_the_text_rows(tmp_path):
    rows = _rows()
    result = s04_overlay.overlay(rows, _registries(tmp_path))
    unit = result.rows["verse_units"][1]
    assert (unit["text_pdf"], unit["text"], unit["errata_ids"]) == ("詵過水", "蹚過水",
                                                                    ["er:0001"])
    assert [e["errata_id"] for e in result.rows["errata_applied"]] == ["er:0001"]
    assert [a["external_ref"] for a in result.rows["ref_aliases"]] == ["jhn.7.53"]
    assert rows["verse_units"][1]["text"] == "詵過水"


def test_the_report_records_errata_rules_and_aliases(tmp_path):
    result = s04_overlay.overlay(_rows(), _registries(tmp_path))
    report = result.report
    assert report["schema"] == s04_overlay.REPORT_SCHEMA
    assert report["errata"]["applied"] == 1 and report["ref_aliases"] == {"declared": 1,
                                                                         "emitted": 1}
    assert report["normalization"]["rules"][0]["applied"] == 2
    assert result.ascii_allowed == {}
    assert s04_overlay.encode_report(report) == s04_overlay.encode_report(report)

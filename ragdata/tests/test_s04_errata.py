"""S4 errata overlay: registry checks, equal-length application, coverage of every misglyph."""

from __future__ import annotations

import hashlib

import pytest
import yaml

from ragdata.contract import parse_record
from ragdata.stages.s04_overlay import errata as er

REGISTRY = {
    "schema": "ragdata.errata.v1", "class": "big5_e04x_misglyph", "decided_by": "claude",
    "not_errata": {"誆": {"big5": "E046", "why": "誆哄是正確用字"}},
    "misglyphs": {
        "詷": {"big5": "E04A", "status": "apply", "corrected": "秕", "word": "糠秕", "why": "糠秕"},
        "詴": {"big5": "E050", "status": "apply", "corrected": "虻", "word": "牛虻", "why": "牛虻"},
        "誁": {"big5": "E04F", "status": "uncertain", "candidates": ["麅", "狍"],
               "word": "麅子", "why": "字形未定"},
    },
    "entries": [
        {"id": "er:0001", "container": "psa.1.4", "offset": 3, "pdf": "詷", "fix": "秕"},
        {"id": "er:0002", "container": "deu.14.5", "offset": 2, "pdf": "誁", "fix": None},
        {"id": "er:0003", "container": "fn:jer.46.20#1", "offset": 4, "pdf": "詴", "fix": "虻"},
    ],
}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows():
    units = [{"unit_key": k, "book_id": k.split(".")[0], "text_pdf": t, "text": t,
              "text_sha256": _sha(t), "errata_ids": []}
             for k, t in (("deu.14.5", "羚羊誁子"), ("psa.1.4", "乃像糠詷被風吹散"),
                          ("jdg.16.5", "求你誆哄參孫"))]
    notes = [{"fn_id": "fn:jer.46.20#1", "unit_key": "jer.46.20", "text_pdf": "或譯：牛詴",
              "text": "或譯：牛詴", "errata_ids": []}]
    return {"verse_units": units, "footnotes": notes, "headings": [], "chapter_texts": [],
            "speakers": [], "parallel_refs": []}


def _load(tmp_path, doc=None):
    path = tmp_path / "errata.yaml"
    path.write_text(yaml.safe_dump(doc or REGISTRY, allow_unicode=True), encoding="utf-8")
    return er.load_errata(path)


def _apply(tmp_path, rows=None, doc=None, books=("deu", "psa", "jdg", "jer")):
    return er.apply_errata(rows or _rows(), _load(tmp_path, doc), set(books))


def test_applied_errata_change_text_only_at_their_offset(tmp_path):
    result = _apply(tmp_path)
    unit = next(u for u in result.rows["verse_units"] if u["unit_key"] == "psa.1.4")
    assert (unit["text_pdf"], unit["text"]) == ("乃像糠詷被風吹散", "乃像糠秕被風吹散")
    assert unit["errata_ids"] == ["er:0001"] and unit["text_sha256"] == _sha(unit["text"])
    note = result.rows["footnotes"][0]
    assert (note["text"], note["errata_ids"]) == ("或譯：牛虻", ["er:0003"])


def test_uncertain_corrections_are_listed_but_not_applied(tmp_path):
    result = _apply(tmp_path)
    unit = next(u for u in result.rows["verse_units"] if u["unit_key"] == "deu.14.5")
    assert unit["text"] == unit["text_pdf"] and unit["errata_ids"] == []
    assert [e["errata_id"] for e in result.applied] == ["er:0001", "er:0003"]
    assert result.report["uncertain"] == [{"errata_id": "er:0002", "container": "deu.14.5",
                                           "offset": 2, "pdf_char": "誁",
                                           "candidates": ["麅", "狍"]}]


def test_errata_applied_rows_carry_evidence_and_pass_their_contract(tmp_path):
    result = _apply(tmp_path)
    row = result.applied[0]
    assert row["evidence"] == {"big5": "E04A", "word": "糠秕", "pdf_char_occurrences": 1,
                               "corrected_occurrences_in_pdf_text": 0}
    assert row["container_kind"] == "unit" and result.applied[1]["container_kind"] == "footnote"
    for applied in result.applied:
        parse_record("errata_applied", applied)


def test_the_input_rows_are_not_mutated(tmp_path):
    rows = _rows()
    _apply(tmp_path, rows=rows)
    assert rows["verse_units"][1]["text"] == "乃像糠詷被風吹散"


def test_entries_of_books_outside_the_build_are_skipped(tmp_path):
    rows = _rows()
    rows["footnotes"] = []
    result = _apply(tmp_path, rows=rows, books=("deu", "psa", "jdg"))
    assert [e["errata_id"] for e in result.applied] == ["er:0001"]


@pytest.mark.parametrize("change, message", [
    (lambda r: r["verse_units"][1].update(text_pdf="乃像糠秕被風吹散詷"), "has '秕'"),
    (lambda r: r["verse_units"][2].update(text_pdf="詷求你誆哄參孫"), "not listed"),
    (lambda r: r["verse_units"][2].update(text_pdf="求你誆哄參孫秕"), "occurs"),
    (lambda r: r["verse_units"].pop(1), "no container"),
], ids=["wrong char at offset", "unlisted occurrence", "correction in pdf", "missing container"])
def test_a_registry_that_does_not_fit_the_pdf_text_is_refused(tmp_path, change, message):
    rows = _rows()
    change(rows)
    with pytest.raises(er.OverlayError, match=message):
        _apply(tmp_path, rows=rows)


def _with(**changes):
    doc = yaml.safe_load(yaml.safe_dump(REGISTRY, allow_unicode=True))
    for path, value in changes.items():
        node = doc
        *parents, last = path.split("__")
        for step in parents:
            node = node[int(step)] if isinstance(node, list) else node[step]
        node[last] = value
    return doc


@pytest.mark.parametrize("doc, message", [
    (_with(schema="other"), "schema"),
    (_with(entries__0__fix="粃"), "fix"),
    (_with(entries__1__fix="麅"), "uncertain"),
    (_with(entries__0__pdf="誆"), "correct"),
    (_with(entries__1__id="er:0001"), "duplicate"),
    (_with(entries__0__offset=-1), "offset"),
    (_with(misglyphs__詷__status="maybe"), "status"),
    (_with(misglyphs__詷__corrected="秕秕"), "one character"),
    (_with(misglyphs__誁__candidates=[]), "candidates"),
    (_with(entries__0__id="E1"), "er:"),
], ids=["schema", "fix differs", "uncertain fixed", "correct char", "dup id", "offset",
        "status", "long fix", "no candidates", "id shape"])
def test_a_malformed_registry_is_refused(tmp_path, doc, message):
    with pytest.raises(er.OverlayError, match=message):
        _load(tmp_path, doc)


def test_an_unreadable_registry_is_refused(tmp_path):
    with pytest.raises(er.OverlayError, match="unreadable"):
        er.load_errata(tmp_path / "missing.yaml")


def test_errata_in_headings_are_refused(tmp_path):
    doc = _with(entries__0__container="hd:psa.1.4#1")
    with pytest.raises(er.OverlayError, match="heading"):
        _load(tmp_path, doc)


def test_the_registry_in_config_loads():
    errata = er.load_errata(er.DEFAULT_PATH)
    assert errata.entries and set(errata.correct).isdisjoint(errata.misglyphs)

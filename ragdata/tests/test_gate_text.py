"""G-TEXT: clean characters, text = text_pdf except at errata, and errata that hold up."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.gates.text import check_text

ALLOWED = {"verse_units": frozenset(".*"), "footnotes": frozenset(".0123456789"),
           "parallel_refs": frozenset("0123456789")}


def _gate(change=None, allowed=ALLOWED):
    files = mini_build.files("text")
    if change is not None:
        change(files)
    schema, snap = check_schema(files, ("text",))
    assert schema.passed, schema.details  # each case keeps the rows inside their contracts
    return check_text(snap, allowed)


def _row(files, type_name, pk, key):
    return next(r for r in files[f"{type_name}.jsonl"] if r[pk] == key)


def _unit(key, **changes):
    def change(files):
        row = _row(files, "verse_units", "unit_key", key)
        row.update(changes)
        row["text_sha256"] = mini_build.sha(row["text"])
    return change


def _both(type_name, pk, key, text):
    return lambda f: _row(f, type_name, pk, key).update(text_pdf=text, text=text)


def test_the_mini_snapshot_is_clean():
    result = _gate()
    assert result.passed, result.details
    assert (result.name, result.hard) == ("G-TEXT", True)
    assert result.observed["errata"] == 2


CASES = {
    "not NFC": (_unit("act.9.1", text_pdf="Á", text="Á"), "NFC"),
    "control character": (_both("headings", "heading_id", "hd:psa.42.1#1", "渴慕\x07上帝"),
                          "U+0007"),
    "private use": (_both("speakers", "sk_id", "sk:sng.1.1#1", "〔新〕"), "U+E000"),
    "replacement character": (_both("chapter_texts", "id", "sp:psa.42", "可拉�"),
                              "U+FFFD"),
    "ascii outside the allow-list": (_unit("act.9.1", text_pdf="掃羅x", text="掃羅x"),
                                     "'x'"),
    "ascii in a record type with none allowed": (
        _both("headings", "heading_id", "hd:psa.42.1#1", "渴慕."), "'.'"),
    "text differs outside errata": (
        _unit("act.9.3", text=mini_build.ACT_9_3.replace("小河", "大河")), "act.9.3"),
    "heading text differs": (
        lambda f: _row(f, "headings", "heading_id", "hd:psa.42.1#1").update(text="渴慕神明"),
        "hd:psa.42.1#1"),
    "correction occurs in the pdf text": (
        _both("footnotes", "fn_id", "fn:eph.6.1#1", "在主裏：或譯蹚"), "蹚"),
    "misglyph left uncorrected elsewhere": (
        _both("footnotes", "fn_id", "fn:eph.6.1#1", "在主裏：或譯詵"), "fn:eph.6.1#1@6"),
    "book name": (lambda f: _row(f, "books", "book_id", "sng").update(
        name="雅歌書", file_name="雅歌書"), "sng"),
}


@pytest.mark.parametrize("change, needle", CASES.values(), ids=CASES.keys())
def test_each_text_fault_turns_the_gate_red(change, needle):
    result = _gate(change)
    assert not result.passed
    assert any(needle in d for d in result.details), result.details


def test_an_errata_record_whose_text_was_not_changed_is_red():
    def change(files):
        unit = _row(files, "verse_units", "unit_key", "act.9.3")
        unit.update(text=unit["text_pdf"], text_sha256=mini_build.sha(unit["text_pdf"]))
    result = _gate(change)
    assert any("er:0001" in d for d in result.details), result.details


def test_the_allow_list_is_per_record_type():
    change = _both("footnotes", "fn_id", "fn:eph.6.1#1", "在主裏：或譯12")
    assert _gate(change).passed
    assert not _gate(change, allowed={}).passed

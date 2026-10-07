"""S2a records: books, chapters, verse_units and verse_slots built from a BookStream."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.contract import parse_record
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import stream, units

SHA = "ab" * 32


def _records(*lines, book_id="rut", ord_start=1):
    rows = [pl.line(1, 136.8, (pl.TITLE, "路得記", 182.9)), *lines,
            *[r for r in pl.colophon_page(9) if r["k"] == "line"]]
    lines = (layout.to_line(r["p"], r["chars"]) for r in rows)
    parsed = stream.parse_rows(layout.rows_of(lines), "t")
    return units.build_book(parsed, book_id, "路得記", SHA, ord_start)


def _note(y, ref, *runs):
    return pl.line(1, y, (pl.NOTE_REF, f"{ref}:", 70.0), *runs)


def _valid(rec):
    for name, rows in (("books", [rec.book]), ("chapters", rec.chapters),
                       ("verse_units", rec.units), ("verse_slots", rec.slots)):
        for row in rows:
            parse_record(name, row)
    return rec


def test_units_slots_chapters_and_book_follow_the_page():
    rec = _valid(_records(pl.verse(1, 186.2, "1", "當士師秉政的時候"),
                          pl.verse(2, 100.0, "2", "這人名叫"),
                          pl.line(2, 150.0, (pl.CHAPTER, "2", 70.0)),
                          pl.verse(2, 170.0, "1-2", "拿俄米"), ord_start=7))
    assert [(u["unit_key"], u["ord"], u["pages"]) for u in rec.units] == [
        ("rut.1.1", 7, [1]), ("rut.1.2", 8, [2]), ("rut.2.1-2", 9, [2])]
    first = rec.units[0]
    assert first["text_pdf"] == first["text"] == "當士師秉政的時候" and first["errata_ids"] == []
    assert first["prov"] == {"pdf_sha256": SHA, "first_glyph": [96.78, 108.74, 186.2]}
    assert [(s["slot_key"], s["unit_key"], s["status"]) for s in rec.slots] == [
        ("rut.1.1", "rut.1.1", "present"), ("rut.1.2", "rut.1.2", "present"),
        ("rut.2.1", "rut.2.1-2", "merged"), ("rut.2.2", "rut.2.1-2", "merged")]
    assert [(c["chapter_key"], c["unit_count"], c["present_slot_count"], c["max_verse"])
            for c in rec.chapters] == [("rut.1", 2, 2, 2), ("rut.2", 1, 2, 2)]
    assert (rec.book["name"], rec.book["chapter_count"], rec.book["unit_count"],
            rec.book["slot_rows"], rec.book["short_names"]) == ("路得記", 2, 3, 4, [])


def test_an_omitted_slot_points_at_the_variant_footnote_of_the_verse_before():
    rec = _valid(_records(
        pl.verse(1, 100.0, "1", "甲"), pl.verse(1, 120.0, "2", "乙"), pl.verse(1, 140.0, "4", "丁"),
        _note(500.0, "1:2", (pl.NOTE, " 或譯：乙", 95.0)),
        _note(510.0, "1:2", (pl.NOTE, " 有古卷加：", 95.0), (pl.VNUM, "3", 150.0),
              (pl.NOTE, "丙", 160.0))))
    slot = next(s for s in rec.slots if s["slot_key"] == "rut.1.3")
    assert slot == {"slot_key": "rut.1.3", "unit_key": None, "status": "omitted_variant",
                    "variant_footnote_id": "fn:rut.1.2#2", "provenance_class": "pdf_deterministic"}
    assert rec.chapters[0]["omitted_slots"] == ["rut.1.3"] and rec.chapters[0]["slot_rows"] == 4
    assert rec.book["omitted_count"] == 1


@pytest.mark.parametrize("lines, message", [
    ([pl.verse(1, 100.0, "1", "甲"), pl.verse(1, 120.0, "3", "丙")], "rut.1.2"),
    ([pl.verse(1, 100.0, "1", "甲"), _note(500.0, "1:5", (pl.NOTE, " 或譯", 95.0))], "1:5"),
    ([pl.verse(1, 100.0, "2", "乙"), pl.verse(1, 120.0, "1", "甲")], "order"),
    ([pl.verse(1, 100.0, "1", "A B")], "whitespace"),
    ([pl.verse(1, 100.0, "1", "甲（細拉）乙")], "selah"),
], ids=["gap-without-variant", "note-to-nowhere", "out-of-order", "inner-space", "inline-selah"])
def test_text_the_records_cannot_represent_is_a_parse_error(lines, message):
    with pytest.raises(ParseError, match=message):
        _records(*lines)


def test_selah_markers_line_breaks_and_poetry_come_from_the_page():
    rec = _valid(_records(
        pl.verse(1, 100.0, "1", "上帝從提幔而來", x=71.0),
        pl.body(1, 114.0, "（細拉）", x=301.0), pl.body(1, 128.0, "他的榮光", x=70.87),
        pl.line(1, 142.0, (pl.BODY, "遮" * 23, 70.87)), pl.body(1, 156.0, "頌讚", x=83.0),
        pl.verse(1, 180.0, "2", "他的輝煌如同日光")))
    poem, prose = rec.units
    assert poem["markers"] == [{"type": "selah", "start": 7, "end": 11}]
    assert poem["line_breaks"] == [{"offset": 7, "kind": "indent"}, {"offset": 11, "kind": "hard"},
                                   {"offset": 15, "kind": "hard"}, {"offset": 38, "kind": "indent"}]
    assert poem["is_poetry"] is True and prose["is_poetry"] is False


def test_a_line_that_reaches_the_margin_wraps_softly():
    rec = _records(pl.verse(1, 100.0, "1", "遮" * 22), pl.body(1, 114.0, "天"))
    assert rec.units[0]["line_breaks"] == [{"offset": 22, "kind": "soft"}]


def test_superscriptions_and_divisions_mark_their_chapters():
    rec = _valid(_records(pl.line(1, 120.0, (pl.DIVISION, "詩篇卷一", 150.0)),
                          pl.verse(1, 140.0, "1", "甲"), pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0)),
                          pl.body(1, 170.0, "大衛的詩。"), pl.verse(1, 190.0, "1", "乙")))
    assert [(c["has_superscription"], c["book_division_id"]) for c in rec.chapters] == [
        (False, "dv:rut.1"), (True, None)]


def test_footnotes_are_numbered_within_their_unit():
    rec = _records(pl.verse(1, 100.0, "1", "甲"), pl.verse(1, 120.0, "2", "乙"),
                   _note(500.0, "1:2", (pl.NOTE, " 或譯：乙", 95.0)),
                   _note(510.0, "1:1", (pl.NOTE, " 原文是甲", 95.0)),
                   _note(520.0, "1:2", (pl.NOTE, " 原文是乙", 95.0)))
    assert [(fid, note.text) for fid, note in rec.footnotes] == [
        ("fn:rut.1.2#1", "或譯：乙"), ("fn:rut.1.1#1", "原文是甲"), ("fn:rut.1.2#2", "原文是乙")]

"""S2b name spans: every underline stroke is a name in a verse or footnote, or a rule."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragcommon import ids
from ragdata.contract import parse_record
from ragdata.stages import layout, s01_extract
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import names, stream, units
from ragdata.store import encode_jsonl

VERSE_Y, NOTE_Y = 100.0, 500.0
TEXT_X = 96.78           # first character of a verse set by pl.verse at its default x
NOTE_X = 95.0 + 4.485    # first character of a note after its " " (see pl.glyphs)
W, NW = 11.96, 8.97


def _under(x_first, n, y, width=W, page=1):
    return pl.stroke(page, round(x_first, 2), round(x_first + n * width, 2), y + 2.4)


def _containers(s, rec):
    return [*((units.unit_key("eph", v), "body", v.glyphs) for v in s.verses),
            *((fid, "footnote", note.glyphs) for fid, note in rec.footnotes)]


def _split_verse(s, rec):
    """Verse 1 cut into two records after its fifth character."""
    first = s.verses[0].glyphs
    return [("eph.1.1", "body", first[:5]), ("eph.1.2", "body", first[5:])]


def _spans(*extra, verse_text="保羅寫信給以弗所的聖徒", note_text="亞比雅就是父親的意思",
           containers=_containers):
    raw = [pl.page(1), pl.line(1, 60.0, (pl.TITLE, "以弗所書", 182.9)),
           pl.verse(1, VERSE_Y, "1", verse_text), pl.verse(1, VERSE_Y + 20, "2", "願恩惠平安"),
           pl.line(1, NOTE_Y, (pl.NOTE_REF, "1:1:", 70.0), (pl.NOTE, " " + note_text, 95.0)),
           pl.stroke(1, 70.87, 181.98, NOTE_Y - 11.1), *extra, *pl.colophon_page(2),
           pl.stroke(2, 70.87, 348.66, 97.5)]
    book = s01_extract.load_s1(encode_jsonl(raw), "eph")
    rows = layout.rows_of(book.lines)
    s = stream.parse_rows(rows, "eph")
    rec = units.build_book(s, "eph", "以弗所書", "ab" * 32, 1)
    spans = names.name_spans(book, rows, containers(s, rec), "eph")
    for span in spans:
        parse_record("name_spans", span)
    return spans


def test_underlines_become_spans_in_their_verse_or_footnote_and_rules_are_skipped():
    spans = _spans(_under(TEXT_X + 5 * W, 3, VERSE_Y), _under(TEXT_X, 2, VERSE_Y),
                   _under(NOTE_X, 3, NOTE_Y, width=NW))
    assert [(s["span_id"], s["region"], s["start"], s["end"], s["surface"], s["norm_key"])
            for s in spans] == [
        ("ns:eph.1.1@0", "body", 0, 2, "保羅", "保羅"),
        ("ns:eph.1.1@5", "body", 5, 8, "以弗所", "以弗所"),
        ("ns:fn:eph.1.1#1@0", "footnote", 0, 3, "亞比雅", "亞比雅")]
    assert {s["source"] for s in spans} == {"pdf_underline"}


@pytest.mark.parametrize("stroke, message", [
    (pl.stroke(1, 100.0, 120.0, 300.0), "no text above"),
    (pl.stroke(1, 100.0, 120.0, VERSE_Y + 12.4), "no text above"),
    ({"k": "stroke", "p": 1, "lw": 0.3985, "path": [["m", 100, 102], ["l", 110, 104]]},
     "horizontal"),
], ids=["nothing-above", "between-rows", "slanted"])
def test_an_underline_that_marks_no_single_name_is_a_parse_error(stroke, message):
    with pytest.raises(ParseError, match=message):
        _spans(stroke)


def test_an_underline_across_two_records_is_a_parse_error():
    with pytest.raises(ParseError, match="more than one record"):
        _spans(_under(TEXT_X + 3 * W, 4, VERSE_Y), containers=_split_verse)


def test_an_underline_under_a_heading_is_a_parse_error():
    heading = pl.line(1, 80.0, (pl.HEAD, "問候", 88.8))
    with pytest.raises(ParseError, match="neither verse nor footnote"):
        _spans(heading, pl.stroke(1, 88.8, 112.7, 82.4))


def test_overlapping_underlines_are_a_parse_error():
    with pytest.raises(ParseError, match="overlap"):
        _spans(_under(TEXT_X, 2, VERSE_Y), _under(TEXT_X + W, 2, VERSE_Y))


def _span(container, start, surface):
    return {"span_id": ids.name_span_id(container, start), "container_id": container,
            "region": "body", "start": start, "end": start + len(surface), "surface": surface,
            "source": "pdf_underline", "norm_key": surface, "norm_rule_ids": [],
            "merge_group": None, "provenance_class": "pdf_deterministic"}


def test_a_name_split_from_its_generic_noun_is_one_merge_group():
    spans = [_span("ezk.47.8", 3, "鹽"), _span("ezk.47.8", 4, "海"), _span("rut.1.2", 0, "猶大"),
             _span("rut.1.2", 2, "伯利恆"), _span("mal.4.4", 0, "何烈"), _span("mal.4.4", 2, "山"),
             _span("mrk.7.31", 0, "海"), _span("mrk.7.31", 5, "鹽"), _span("mrk.7.31", 6, "海")]
    grouped = names.with_merge_groups(spans)
    salt, horeb = ids.merge_group_id("鹽海", 1), ids.merge_group_id("何烈山", 1)
    assert [s["merge_group"] for s in grouped] == [
        salt, salt, None, None, horeb, horeb, None,
        ids.merge_group_id("鹽海", 2), ids.merge_group_id("鹽海", 2)]
    assert spans[0]["merge_group"] is None

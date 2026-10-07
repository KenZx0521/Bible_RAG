"""S2b heading, parallel-reference and speaker records built from placed navy rows."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.contract import parse_record
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import headings, navy, stream, units


def _records(book, *lines, ord_start=1):
    rows = [pl.line(1, 60.0, (pl.TITLE, "書", 182.9)), *lines, *pl.colophon_page(9)]
    s = stream.parse_rows(layout.rows_of(pl.s1_lines(rows)), book)
    placed = navy.place_navy(s, units.unit_keys(book, s), book)
    recs = headings.navy_records(book, placed, ord_start)
    for name in ("headings", "parallel_refs", "speakers"):
        for row in getattr(recs, name):
            parse_record(name, row)
    return recs


def _head(y, text, x=88.8):
    return pl.line(1, y, (pl.HEAD, text, x))


def _by_id(recs):
    return {h["heading_id"]: h for h in recs.headings}


def test_a_section_heading_stacks_over_the_first_heading_and_contains_the_later_ones():
    recs = _records("ezk", _head(100, "以西結所見的第一個異象"), _head(115, "（1‧1－7‧27）"),
                    _head(130, "上帝的寶座"), pl.verse(1, 145, "1", "當三十年"),
                    pl.verse(1, 160, "2", "正是"), _head(175, "活物的形像"),
                    pl.verse(1, 190, "3", "在迦勒底"), ord_start=40)
    rows = _by_id(recs)
    assert [(h["heading_id"], h["level"], h["parent_heading_id"], h["ord"])
            for h in recs.headings] == [
        ("hd:ezk.1.1#1", 1, None, 40), ("hd:ezk.1.1#2", 2, "hd:ezk.1.1#1", 41),
        ("hd:ezk.1.3#1", 2, "hd:ezk.1.1#1", 42)]
    assert rows["hd:ezk.1.1#2"]["display_title"] == "上帝的寶座"
    (section,) = recs.parallel_refs
    assert (section["heading_id"], section["kind"]) == ("hd:ezk.1.1#1", "section_range")


def test_dash_subheadings_hang_under_the_heading_whose_title_they_complete():
    recs = _records("amo", _head(100, "上帝審判以色列的鄰國"), _head(115, "－亞蘭"),
                    pl.verse(1, 130, "3", "耶和華如此說"), _head(145, "－非利士"),
                    pl.verse(1, 160, "6", "耶和華如此說"), _head(175, "埃及遭災－血災"),
                    pl.verse(1, 190, "9", "耶和華"), _head(205, "－蛙災"),
                    pl.verse(1, 220, "13", "耶和華"))
    assert [(h["heading_id"], h["level"], h["parent_heading_id"], h["display_title"])
            for h in recs.headings] == [
        ("hd:amo.1.3#1", 1, None, "上帝審判以色列的鄰國"),
        ("hd:amo.1.3#2", 2, "hd:amo.1.3#1", "上帝審判以色列的鄰國－亞蘭"),
        ("hd:amo.1.6#1", 2, "hd:amo.1.3#1", "上帝審判以色列的鄰國－非利士"),
        ("hd:amo.1.9#1", 2, None, "埃及遭災－血災"),
        ("hd:amo.1.13#1", 2, "hd:amo.1.9#1", "埃及遭災－蛙災")]


def test_mid_verse_headings_and_speakers_get_half_verse_and_unit_ids():
    recs = _records("sng", pl.verse(1, 100, "2", "願他用口"), _head(115, "〔新娘〕", x=70.87),
                    pl.body(1, 130, "與我親嘴"), _head(145, "求愛"), pl.body(1, 160, "因你的愛情"),
                    _head(175, "〔新郎〕", x=70.87), pl.verse(1, 190, "3", "你的膏油"))
    (heading,) = recs.headings
    assert (heading["heading_id"], heading["anchor_unit_key"], heading["anchor_offset"],
            heading["pos"]) == ("hd:sng.1.2b#1", "sng.1.2", 8, "mid")
    first, last = heading["prov"]["glyph_range"]
    assert heading["prov"]["style_class"] == navy.STYLE_CLASS and last - first == 1
    assert [(s["sk_id"], s["unit_key"], s["offset"], s["pos"], s["text"])
            for s in recs.speakers] == [("sk:sng.1.2#1", "sng.1.2", 4, "mid", "〔新娘〕"),
                                        ("sk:sng.1.3#1", "sng.1.3", 0, "before", "〔新郎〕")]


@pytest.mark.parametrize("lines, message", [
    ([_head(100, "（太1‧1）"), pl.verse(1, 130, "1", "甲")], "no heading"),
    ([_head(100, "〔新娘〕", x=70.87), _head(115, "（太1‧1）"), pl.verse(1, 130, "1", "甲")],
     "no heading"),
    ([_head(100, "標題"), _head(115, "（太1‧1）"), _head(130, "（太2‧1）"),
      pl.verse(1, 145, "1", "甲")], "second reference line"),
    ([_head(100, "－亞蘭"), pl.verse(1, 130, "1", "甲")], "no heading before"),
], ids=["leading", "after-speaker", "two-lines", "orphan-dash"])
def test_navy_rows_the_records_cannot_represent_are_parse_errors(lines, message):
    with pytest.raises(ParseError, match=message):
        _records("amo", *lines)

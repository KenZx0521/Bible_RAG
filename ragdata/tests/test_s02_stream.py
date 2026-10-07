"""S2 row stream: verses with glyph provenance, titles, navy rows, footnotes, divisions."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import stream

TITLE_ROW = pl.line(1, 136.8, (pl.TITLE, "路得記", 182.9))
HEADER_ROW = pl.line(1, 82.8, (pl.HEADER, "路得記 1:1", 70.87))


def _parse(*lines, title=True):
    rows = [*([TITLE_ROW] if title else []), *lines,
            *[r for r in pl.colophon_page(9) if r["k"] == "line"]]
    lines = (layout.to_line(r["p"], r["chars"]) for r in rows)
    return stream.parse_rows(layout.rows_of(lines), "rut")


def test_verses_gather_their_continuation_rows():
    s = _parse(HEADER_ROW, pl.line(1, 175.2, (pl.HEAD, "以利米勒全家遷往摩押", 88.8)),
               pl.verse(1, 186.2, "1", "當 士 師 秉 政"), pl.body(1, 202.2, "國中遭遇饑荒。"),
               pl.verse(1, 227.9, "2", "這人名叫以利米勒"), pl.body(2, 100.0, "他兩個兒子"))
    assert s.book_title == "路得記"
    assert [(v.chapter, v.label, v.text) for v in s.verses] == [
        (1, "1", "當士師秉政國中遭遇饑荒。"), (1, "2", "這人名叫以利米勒他兩個兒子")]
    assert [(ln.start, ln.end, ln.first.page) for ln in s.verses[1].lines] == \
        [(0, 8, 1), (8, 13, 2)]
    assert "".join(g.c for g in s.verses[0].number) == "1"
    assert [e.kind for e in s.events] == ["heading", "verse", "cont", "verse", "cont"]
    heading = s.events[0]
    assert (heading.chapter, heading.verse, heading.offset, heading.text) == \
        (1, None, None, "以利米勒全家遷往摩押")
    assert s.skipped == {"page_header": 10, "book_title": 3}


def test_chapter_numerals_superscriptions_and_merged_labels():
    s = _parse(pl.verse(1, 100.0, "1", "甲"), pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0)),
               pl.body(1, 170.0, "大衛的詩。"), pl.verse(1, 190.0, "1-2", "乙"),
               pl.verse(1, 210.0, "3", "丙"))
    assert [(v.chapter, v.v_start, v.v_end, v.label) for v in s.verses] == [
        (1, 1, 1, "1"), (2, 1, 2, "1-2"), (2, 3, 3, "3")]
    assert s.numerals == {2: "2"}
    assert "".join(g.c for g in s.titles[2]) == "大衛的詩。" and 1 not in s.titles


def test_selah_lines_are_kept_in_the_verse_and_their_offsets_recorded():
    s = _parse(pl.verse(1, 100.0, "3", "從巴蘭山臨到。"), pl.body(1, 114.0, "（細拉）", x=301.0),
               pl.body(1, 128.0, "他的榮光遮蔽諸天"), pl.verse(1, 142.0, "4", "他的輝煌"))
    verse = s.verses[0]
    assert verse.text == "從巴蘭山臨到。（細拉）他的榮光遮蔽諸天" and verse.selah == (7,)


def test_footnotes_split_on_each_caller_and_keep_inline_verse_numbers():
    s = _parse(pl.verse(1, 100.0, "36", "腓利"),
               pl.line(1, 500.0, (pl.NOTE_REF, "8:36:", 70.0), (pl.NOTE, " 有古卷加：", 95.0),
                       (pl.VNUM, "37", 150.0), (pl.NOTE, "腓利說", 160.0)),
               pl.line(1, 510.0, (pl.NOTE, "你若是一心相信", 70.0), (pl.NOTE_REF, "8:39:", 200.0),
                       (pl.NOTE, " 或譯：靈", 225.0)))
    assert [(f.ref, f.text, f.numbers, f.page) for f in s.footnotes] == [
        ("8:36", "有古卷加：37腓利說你若是一心相信", (37,), 1), ("8:39", "或譯：靈", (), 1)]


def test_a_division_belongs_to_the_chapter_that_follows_it():
    s = _parse(pl.line(1, 120.0, (pl.DIVISION, "詩篇卷一", 150.0)), pl.verse(1, 140.0, "1", "甲"),
               pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0)), pl.verse(1, 160.0, "1", "乙"),
               pl.line(1, 170.0, (pl.DIVISION, "詩 篇 卷 二", 150.0)),
               pl.line(1, 190.0, (pl.CHAPTER, "3", 70.0)), pl.verse(1, 210.0, "1", "丙"))
    assert [(e.chapter, e.text) for e in s.events if e.kind == "division"] == [
        (1, "詩篇卷一"), (3, "詩篇卷二")]


def test_a_book_without_a_title_row_is_a_parse_error():
    with pytest.raises(ParseError, match="title"):
        _parse(pl.verse(1, 100.0, "1", "甲"), title=False)


def test_rows_of_no_known_class_are_kept_as_unclassified():
    odd = pl.line(1, 120.0, (pl.ODD, "奇", 70.0), (pl.HEAD, "怪", 90.0))
    s = _parse(pl.verse(1, 100.0, "1", "甲"), odd)
    assert [r.text for r in s.unclassified] == ["奇怪"]
    assert [r.text for r in s.colophon][0] == "新標點和合本"


@pytest.mark.parametrize("lines, message", [
    ([pl.verse(1, 100.0, "x", "甲")], "verse number"),
    ([pl.verse(1, 100.0, "3-2", "甲")], "verse number"),
    ([pl.verse(1, 100.0, "1", "甲"), pl.verse(1, 120.0, "1", "乙")], "twice"),
    ([pl.body(1, 100.0, "甲")], "before the first chapter"),
    ([pl.verse(1, 100.0, "1", "甲"), pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0), (pl.BODY, "乙", 90))],
     "chapter row"),
    ([pl.verse(1, 100.0, "1", "甲"), pl.line(1, 150.0, (pl.CHAPTER, "3", 70.0))], "chapter 3"),
    ([pl.line(1, 500.0, (pl.NOTE, "沒有呼號", 70.0))], "caller"),
    ([pl.line(1, 100.0, (pl.VNUM, "1", 82.8), (pl.BODY, "甲", 90.0), (pl.HEAD, "乙", 110.0))],
     "style"),
    ([pl.line(1, 120.0, (pl.DIVISION, "卷二", 150.0)), pl.line(1, 140.0, (pl.CHAPTER, "1", 70.0)),
      pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0)), pl.verse(1, 160.0, "1", "甲")], "division"),
    ([pl.line(1, 120.0, (pl.DIVISION, "卷二", 150.0))], "division"),
], ids=["letters", "descending", "duplicate", "orphan-body", "numeral-with-text", "skip",
        "orphan-note", "navy-in-verse", "division-elsewhere", "division-at-end"])
def test_structure_the_parser_cannot_place_is_a_parse_error(lines, message):
    with pytest.raises(ParseError, match=message):
        _parse(*lines)

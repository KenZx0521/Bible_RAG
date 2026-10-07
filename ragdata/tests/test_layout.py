"""Style runs, visual rows and row classes of the typeset page (stages.layout)."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.stages import layout


def _rows(*lines):
    return layout.rows_of(layout.to_line(r["p"], r["chars"]) for r in lines)


def test_a_line_becomes_style_runs_ordered_left_to_right():
    raw = pl.line(1, 100.0, (pl.BODY, "後來", 120.0), (pl.VNUM, "3", 82.8), (pl.BODY2, "拿俄米", 150.0))
    (row,) = _rows(raw)
    assert [r.text for r in row.runs] == ["3", "後來", "拿俄米"]
    assert row.runs[0].style == pl.VNUM and row.page == 1
    assert row.runs[1].x0 == 120.0 and row.runs[1].x1 == pytest.approx(120.0 + 2 * 11.96, abs=0.01)


def test_the_row_baseline_is_the_most_common_glyph_baseline():
    raw = pl.line(1, 100.0, (pl.BODY, "甲乙", 70.0))
    raw["chars"][0][3] = 98.0
    raw["chars"].append(["丙", 100.0, 112.0, 98.0] + list(pl.BODY))
    raw["chars"].append(["丁", 112.0, 124.0, 100.0] + list(pl.BODY))
    assert layout.to_line(1, raw["chars"]).y == 98.0


def test_lines_closer_than_four_points_on_one_page_merge_into_one_row():
    number = pl.line(1, 186.2, (pl.VNUM, "1", 82.8))
    text = pl.line(1, 189.2, (pl.BODY, "當士師秉政的時候", 98.5))
    below = pl.line(1, 193.2, (pl.BODY, "國中", 70.87))
    next_page = pl.line(2, 193.2, (pl.BODY, "遭遇", 70.87))
    rows = _rows(number, text, below, next_page)
    assert [r.text for r in rows] == ["1當士師秉政的時候", "國中", "遭遇"]
    assert rows[0].y == 186.2


@pytest.mark.parametrize("raw, kind", [
    (pl.line(1, 82.8, (pl.HEADER, "路得記 1:1", 70.0)), "header"),
    (pl.line(1, 106.7, (pl.COLOPHON, "新標點和合本", 173.9)), "colophon"),
    (pl.line(1, 136.8, (pl.TITLE, "路得記", 182.9)), "booktitle"),
    (pl.line(1, 150.0, (pl.DIVISION, "詩篇卷一", 150.0)), "volume"),
    (pl.line(1, 150.0, (pl.CHAPTER, "2", 70.0)), "chapter"),
    (pl.line(1, 500.0, (pl.NOTE_REF, "1:2:", 70.0), (pl.NOTE, " 或譯", 90.0)), "fnstart"),
    (pl.line(1, 510.0, (pl.NOTE, "續行", 70.0)), "fncont"),
    (pl.line(1, 175.2, (pl.HEAD, "以利米勒全家遷往摩押", 88.8)), "heading"),
    (pl.line(1, 175.2, (pl.HEAD, " （太14‧13）", 88.8)), "paral"),
    (pl.verse(1, 200.0, "2", "這人名叫以利米勒"), "verse"),
    (pl.body(1, 214.0, "兩個兒子"), "body"),
    (pl.line(1, 214.0, (pl.ODD, "奇", 70.0), (pl.HEAD, "怪", 90.0)), "other"),
])
def test_rows_are_classified_by_style_alone(raw, kind):
    (row,) = _rows(raw)
    assert layout.classify(row) == kind


def test_clean_drops_spaces_next_to_han_but_keeps_spaces_between_ascii():
    raw = pl.line(1, 100.0, (pl.BODY, " 這 人 名 叫 A B ", 70.0))
    kept = layout.clean(layout.to_line(1, raw["chars"]).glyphs)
    assert "".join(g.c for g in kept) == "這人名叫A B"
    assert layout.clean_text("  （ 太14‧13 ）") == "（太14‧13）"


def test_nonspace_counts_glyphs_that_are_not_whitespace():
    raw = pl.line(1, 100.0, (pl.BODY, "這 人 \t", 70.0))
    assert layout.nonspace(layout.to_line(1, raw["chars"]).glyphs) == 2


def _book(*extra):
    return [pl.line(1, 136.8, (pl.TITLE, "路得記", 182.9)), pl.verse(1, 200.0, "1", "當士師秉政")] \
        + [r for r in pl.colophon_page(2) if r["k"] == "line"] + list(extra)


def test_the_colophon_page_is_split_off_and_its_page_number_stays_a_header():
    body, colophon = layout.split_colophon(_rows(*_book()), "rut")
    assert [layout.classify(r) for r in body] == ["booktitle", "verse", "header"]
    assert [r.text for r in colophon] == ["新標點和合本", "Public Domain",
                                          "c03bb35c-f042-59c2-88d7-1111d9a01842"]


@pytest.mark.parametrize("rows, message", [
    ([pl.verse(1, 200.0, "1", "當士師秉政")], "no colophon"),
    (_book(pl.body(3, 100.0, "多出來的一頁")), "after the colophon"),
    ([pl.line(2, 90.0, (pl.SMALL, "前言", 70.87))] + _book()[2:], "before the colophon"),
], ids=["missing", "page-after", "text-before-on-its-page"])
def test_a_colophon_that_is_not_alone_on_the_last_page_is_a_parse_error(rows, message):
    with pytest.raises(layout.ParseError, match=message):
        layout.split_colophon(_rows(*rows), "rut")

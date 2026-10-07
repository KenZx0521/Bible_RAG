"""S2b navy rows: headings, parallel-reference lines and speakers, typed and placed."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import navy, stream, units

TITLE_ROW = pl.line(1, 60.0, (pl.TITLE, "阿摩司書", 182.9))


def _stream(*lines):
    rows = [TITLE_ROW, *lines, *pl.colophon_page(9)]
    return stream.parse_rows(layout.rows_of(pl.s1_lines(rows)), "amo")


def _placed(*lines):
    s = _stream(*lines)
    return navy.place_navy(s, units.unit_keys("amo", s), "amo")


def _head(y, text, x=88.8, style=pl.HEAD):
    return pl.line(1, y, (style, text, x))


def _summary(placed):
    return [(p.line.kind, p.line.text, p.unit_key, p.offset, p.pos) for p in placed]


def test_headings_and_speakers_stand_before_the_verse_that_follows_them():
    placed = _placed(_head(100, "上帝審判以色列的鄰國"), _head(115, "－亞蘭"),
                     pl.verse(1, 130, "1", "耶和華如此說"), _head(145, "〔新娘〕", x=70.87),
                     pl.verse(1, 160, "2", "願他用口與我親嘴"))
    assert _summary(placed) == [
        ("heading", "上帝審判以色列的鄰國", "amo.1.1", 0, "before"),
        ("heading", "－亞蘭", "amo.1.1", 0, "before"),
        ("speaker", "〔新娘〕", "amo.1.2", 0, "before")]
    assert placed[0].line.glyphs[0].style == pl.HEAD and placed[0].line.page == 1


def test_a_navy_row_between_two_lines_of_a_verse_stands_inside_it():
    placed = _placed(pl.verse(1, 100, "19", "吃過飯就健壯了"), _head(115, "掃羅在大馬士革傳道"),
                     pl.body(1, 130, "掃羅和門徒同住"), _head(145, "〔新郎〕", x=70.87),
                     pl.body(1, 160, "幾天"), pl.verse(1, 175, "20", "就在各會堂"))
    assert _summary(placed) == [
        ("heading", "掃羅在大馬士革傳道", "amo.1.19", 7, "mid"),
        ("speaker", "〔新郎〕", "amo.1.19", 14, "mid")]


def test_a_heading_above_a_superscription_stands_before_the_first_verse():
    placed = _placed(pl.line(1, 90, (pl.CHAPTER, "1", 70.0)), _head(100, "求上帝保護"),
                     pl.body(1, 115, "大衛的詩。"), pl.verse(1, 130, "1", "耶和華啊"))
    assert _summary(placed) == [("heading", "求上帝保護", "amo.1.1", 0, "before")]


@pytest.mark.parametrize("rows, text", [
    ([pl.line(1, 115, (pl.HEAD, "（可11‧1－11；約", 88.8)),
      pl.line(1, 130, (pl.ITALIC, "12‧12－19）", 70.87))], "（可11‧1－11；約12‧12－19）"),
    ([pl.line(1, 115, (pl.ITALIC, "*", 88.8), (pl.HEAD2, "王下20‧1－3；賽", 95.0)),
      pl.line(1, 130, (pl.HEAD2, "38‧1－3", 70.87), (pl.ITALIC, "*", 120.0))], "*王下20‧1－3；賽38‧1－3*"),
    ([pl.line(1, 115, (pl.HEAD, "（太26‧69－70)", 88.8))], "（太26‧69－70)"),
], ids=["wrapped", "asterisks", "ascii-close"])
def test_a_reference_line_runs_until_its_brackets_close(rows, text):
    placed = _placed(_head(100, "潔淨聖殿"), *rows, pl.verse(1, 150, "1", "耶穌進了聖殿"))
    assert [(p.line.kind, p.line.text) for p in placed] == [("heading", "潔淨聖殿"),
                                                            ("parallel", text)]


@pytest.mark.parametrize("rows, message", [
    ([pl.line(1, 115, (pl.ITALIC, "12‧12－19）", 70.87))], "not a heading"),
    ([_head(115, "從12‧12起", style=pl.ITALIC)], "not a heading"),
    ([_head(115, "上帝（的寶座")], "not a heading"),
    ([_head(115, "〔新娘〕")], "not a heading"),
    ([_head(115, "（可11‧1－11；約"), _head(130, "12‧12－19）")], "continues"),
    ([_head(115, "（可11‧1－11；約")], "never closes"),
], ids=["fragment-at-margin", "italic-digits", "unbalanced", "speaker-at-indent",
        "continuation-indented", "unclosed"])
def test_navy_rows_that_are_not_headings_are_parse_errors(rows, message):
    with pytest.raises(ParseError, match=message):
        _placed(_head(100, "潔淨聖殿"), *rows, pl.verse(1, 150, "1", "耶穌進了聖殿"))


def test_a_navy_row_with_no_verse_after_it_is_a_parse_error():
    with pytest.raises(ParseError, match="no verse"):
        _placed(pl.verse(1, 100, "1", "甲"), _head(115, "結語"))

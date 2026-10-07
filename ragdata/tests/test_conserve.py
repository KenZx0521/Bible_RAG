"""G-CONSERVE: every glyph of the page lands in exactly one record or dropped category."""

from __future__ import annotations

import pytest

import pdf_lines as pl
from ragdata.gates.conserve import check_conserve
from ragdata.stages import layout, s01_extract
from ragdata.stages.s02_parse import conserve, parse_book
from ragdata.store import encode_jsonl

FULL = [
    pl.line(1, 82.8, (pl.HEADER, "詩篇 1:1", 70.0)), pl.line(1, 136.8, (pl.TITLE, "詩篇", 182.9)),
    pl.line(1, 150.0, (pl.DIVISION, "詩篇卷一", 150.0)), pl.verse(1, 170.0, "1", "不從惡人的計謀"),
    pl.line(1, 190.0, (pl.CHAPTER, "2", 70.0)), pl.line(1, 205.0, (pl.HEAD, "大衛的詩", 88.8)),
    pl.line(1, 220.0, (pl.HEAD, "（撒下15‧13）", 88.8)), pl.body(1, 235.0, "大衛逃避押沙龍"),
    pl.verse(1, 250.0, "1-2", "耶和華啊"), pl.body(1, 264.0, "（細拉）", x=301.0),
    pl.line(1, 280.0, (pl.HEAD, "〔新娘〕", 70.87)), pl.verse(1, 295.0, "3", "我的上帝"),
    pl.line(1, 500.0, (pl.NOTE_REF, "2:1-2:", 70.0), (pl.NOTE, " 或譯：神", 100.0)),
]


def _book(lines):
    return s01_extract.load_s1(encode_jsonl([pl.page(1), *lines, *pl.colophon_page(2)]), "psa")


def _parsed(lines=FULL):
    return parse_book(_book(lines), "psa", "詩篇", "0" * 64, 1)


def test_every_category_balances_and_is_counted_from_the_records():
    tally = _parsed().tally
    assert tally.source == tally.output
    assert tally.source == {"page_header": 5 + 4, "book_title": 2, "division": 4, "verse_number": 5,
                            "body": 7 + 7 + 8 + 4, "chapter_number": 1, "navy": 4 + 9 + 4,
                            "footnote": 6 + 4, "colophon": 6 + 12 + 36, "unclassified": 0}
    assert tally.glyphs == sum(tally.source.values())
    result = check_conserve({"psa": tally}, {"body": 26, "navy": 17, "footnote": 10, "division": 4})
    assert result.name == "G-CONSERVE" and result.passed, result.details


@pytest.mark.parametrize("record_type, category", [
    ("verse_units", "body"), ("chapter_texts", "division"), ("headings", "navy"),
    ("parallel_refs", "navy"), ("speakers", "navy"), ("footnotes", "footnote"),
])
def test_a_record_missing_from_the_output_leaves_a_residual(record_type, category):
    book = _book(FULL)
    parsed = parse_book(book, "psa", "詩篇", "0" * 64, 1)
    rows = {**parsed.rows, record_type: parsed.rows[record_type][1:]}
    tally = conserve.book_tally(book.lines, layout.rows_of(book.lines), parsed.stream, rows)
    result = check_conserve({"psa": tally}, {})
    assert not result.passed and any(f"psa {category}" in d for d in result.details)


def test_glyphs_lost_before_classification_turn_the_gate_red():
    book = _book(FULL)
    parsed = parse_book(book, "psa", "詩篇", "0" * 64, 1)
    tally = conserve.book_tally(book.lines, layout.rows_of(book.lines[1:]), parsed.stream,
                                parsed.rows)
    result = check_conserve({"psa": tally}, {})
    assert not result.passed and any("glyphs" in d for d in result.details)


def test_an_unclassified_row_turns_the_gate_red():
    odd = pl.line(1, 300.0, (pl.ODD, "奇", 70.0), (pl.HEAD, "怪", 90.0))
    tally = _parsed([*FULL[:4], odd]).tally
    result = check_conserve({"psa": tally}, {})
    assert tally.source["unclassified"] == 2 and not result.passed
    assert any("unclassified" in d for d in result.details)


def test_category_totals_must_equal_the_expectations():
    result = check_conserve({"psa": _parsed().tally}, {"body": 27})
    assert not result.passed and any("body" in d and "27" in d for d in result.details)


def test_gate_time_verse_numbers_are_counted_from_the_stored_labels():
    book = _book(FULL)
    rows = parse_book(book, "psa", "詩篇", "0" * 64, 1).rows
    assert check_conserve({"psa": conserve.stored_tally(book.lines, rows)}, {}).passed
    relabelled = [{**u, "label": "13"} if u["label"] == "3" else u for u in rows["verse_units"]]
    tally = conserve.stored_tally(book.lines, {**rows, "verse_units": relabelled})
    result = check_conserve({"psa": tally}, {})
    assert not result.passed and any("psa verse_number" in d for d in result.details)

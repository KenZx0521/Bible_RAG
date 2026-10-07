"""G-CONSERVE: every glyph of the page lands in exactly one category, none is lost."""

from __future__ import annotations

import pdf_lines as pl
from ragdata.gates.conserve import check_conserve
from ragdata.stages import layout
from ragdata.stages.s02_parse import conserve, stream, units

FULL = [
    pl.line(1, 82.8, (pl.HEADER, "詩篇 1:1", 70.0)), pl.line(1, 136.8, (pl.TITLE, "詩篇", 182.9)),
    pl.line(1, 150.0, (pl.DIVISION, "詩篇卷一", 150.0)), pl.verse(1, 170.0, "1", "不從惡人的計謀"),
    pl.line(1, 190.0, (pl.CHAPTER, "2", 70.0)), pl.line(1, 205.0, (pl.HEAD, "大衛的詩", 88.8)),
    pl.line(1, 220.0, (pl.HEAD, "（撒下15‧13）", 88.8)), pl.body(1, 235.0, "大衛逃避押沙龍"),
    pl.verse(1, 250.0, "1-2", "耶和華啊"), pl.body(1, 264.0, "（細拉）", x=301.0),
    pl.line(1, 500.0, (pl.NOTE_REF, "2:1-2:", 70.0), (pl.NOTE, " 或譯：神", 100.0)),
]


def _tally(lines, drop_unit=False, drop_line=False):
    rows_in = [*lines, *[r for r in pl.colophon_page(2) if r["k"] == "line"]]
    s1_lines = [layout.to_line(r["p"], r["chars"]) for r in rows_in]
    rows = layout.rows_of(s1_lines[1:] if drop_line else s1_lines)
    parsed = stream.parse_rows(rows, "psa")
    recs = units.build_book(parsed, "psa", "詩篇", "0" * 64, 1)
    kept = recs.units[1:] if drop_unit else recs.units
    return conserve.book_tally(s1_lines, rows, parsed, kept)


def test_every_category_balances_and_unparsed_ones_are_counted_as_pending():
    tally = _tally(FULL)
    assert tally.source == tally.output
    assert tally.source == {"page_header": 5 + 4, "book_title": 2, "division": 4, "verse_number": 4,
                            "body": 7 + 7 + 8, "chapter_number": 1, "navy": 4 + 9,
                            "footnote": 6 + 4, "colophon": 6 + 12 + 36, "unclassified": 0}
    assert tally.pending == {"superscription": 7, "navy": 13, "footnote": 10, "division": 4}
    assert tally.glyphs == sum(tally.source.values())
    result = check_conserve({"psa": tally}, {"body": 22, "navy": 13, "footnote": 10, "division": 4})
    assert result.name == "G-CONSERVE" and result.passed, result.details
    assert result.observed["pending_s2b"] == tally.pending


def test_a_unit_missing_from_the_records_leaves_a_body_residual():
    result = check_conserve({"psa": _tally(FULL, drop_unit=True)}, {})
    assert not result.passed and any("body" in d and "psa" in d for d in result.details)


def test_glyphs_lost_before_classification_turn_the_gate_red():
    result = check_conserve({"psa": _tally(FULL, drop_line=True)}, {})
    assert not result.passed and any("glyphs" in d for d in result.details)


def test_an_unclassified_row_turns_the_gate_red():
    odd = pl.line(1, 300.0, (pl.ODD, "奇", 70.0), (pl.HEAD, "怪", 90.0))
    tally = _tally([*FULL[:4], odd])
    result = check_conserve({"psa": tally}, {})
    assert tally.source["unclassified"] == 2 and not result.passed
    assert any("unclassified" in d for d in result.details)


def test_category_totals_must_equal_the_expectations():
    result = check_conserve({"psa": _tally(FULL)}, {"body": 23})
    assert not result.passed and any("body" in d and "23" in d for d in result.details)

"""S2b chapter texts: Psalm superscriptions (with their order) and book divisions."""

from __future__ import annotations

import pdf_lines as pl
from ragdata.contract import parse_record
from ragdata.stages import layout
from ragdata.stages.s02_parse import chapter_texts, stream


def _rows(*lines):
    rows = [pl.line(1, 60.0, (pl.TITLE, "詩篇", 182.9)), *lines, *pl.colophon_page(9)]
    s = stream.parse_rows(layout.rows_of(pl.s1_lines(rows)), "psa")
    out = chapter_texts.chapter_text_rows("psa", s)
    for row in out:
        parse_record("chapter_texts", row)
    return out


def _chapter(y, n):
    return pl.line(1, y, (pl.CHAPTER, str(n), 70.0))


def test_superscriptions_record_whether_they_stand_before_or_after_the_heading():
    rows = _rows(pl.line(1, 80, (pl.DIVISION, "詩 篇 卷 一", 150.0)), pl.verse(1, 100, "1", "甲"),
                 _chapter(120, 2), pl.line(1, 135, (pl.HEAD, "大衛的祈禱", 88.8)),
                 pl.body(1, 150, "大衛的詩，"), pl.body(2, 100, "交給聖詠團長。"),
                 pl.verse(2, 115, "1", "乙"),
                 _chapter(130, 3), pl.body(2, 145, "大衛逃避押沙龍的時候作的詩。"),
                 pl.line(2, 160, (pl.HEAD, "晨禱", 88.8)), pl.verse(2, 175, "1", "丙"),
                 _chapter(190, 4), pl.body(2, 205, "可拉後裔的詩。"), pl.verse(2, 220, "1", "丁"))
    assert [(r["id"], r["kind"], r["text_pdf"], r["order"], r["pages"]) for r in rows] == [
        ("dv:psa.1", "book_division", "詩篇卷一", None, [1]),
        ("sp:psa.2", "superscription", "大衛的詩，交給聖詠團長。", "after_heading", [1, 2]),
        ("sp:psa.3", "superscription", "大衛逃避押沙龍的時候作的詩。", "before_heading", [2]),
        ("sp:psa.4", "superscription", "可拉後裔的詩。", "no_heading", [2])]
    assert all(r["text"] == r["text_pdf"] for r in rows)


def test_a_book_without_superscriptions_or_divisions_has_no_chapter_texts():
    assert _rows(pl.verse(1, 100, "1", "甲"), _chapter(120, 2), pl.verse(1, 140, "1", "乙")) == ()

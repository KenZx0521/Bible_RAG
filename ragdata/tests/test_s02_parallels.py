"""S2b parallel references: segments resolved to PDF slot ranges with ragcommon.refs."""

from __future__ import annotations

import pytest

from ragdata.contract import parse_record
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse import parallels


def _rows(raw, book="mat", anchor="mat.21.1", heading="hd:mat.21.1#1"):
    rows = parallels.parse_line(heading, raw, book, anchor)
    for row in rows:
        parse_record("parallel_refs", row)
    return rows


def _targets(row):
    return [(t["start_slot"], t["end_slot"]) for t in row["targets"]]


def test_each_segment_resolves_to_slot_ranges():
    raw = "（可11‧1－11；路19‧28－40；約12‧12－19）"
    rows = _rows(raw)
    assert [(r["pr_id"], r["seg_idx"], r["kind"], r["raw"]) for r in rows] == [
        ("pr:hd:mat.21.1#1#1", 0, "parallel", raw), ("pr:hd:mat.21.1#1#2", 1, "parallel", raw),
        ("pr:hd:mat.21.1#1#3", 2, "parallel", raw)]
    assert [_targets(r) for r in rows] == [[("mrk.11.1", "mrk.11.11")],
                                          [("luk.19.28", "luk.19.40")],
                                          [("jhn.12.12", "jhn.12.19")]]
    assert rows[0]["targets"][0]["book_id"] == "mrk"
    assert rows[0]["parse_rule"] == "abbr+n‧n－n"


def test_a_segment_without_a_book_continues_the_book_and_chapter_before_it():
    rows = _rows("*王下18‧13－37；19‧14－19，35－37；賽36‧1－22；37‧8－38*", "2ch", "2ch.32.1",
                 "hd:2ch.32.1#1")
    assert [_targets(r) for r in rows] == [
        [("2ki.18.13", "2ki.18.37")], [("2ki.19.14", "2ki.19.19"), ("2ki.19.35", "2ki.19.37")],
        [("isa.36.1", "isa.36.22")], [("isa.37.8", "isa.37.38")]]
    assert rows[1]["parse_rule"] == "n‧n－n，n－n"
    assert _targets(_rows("（路6‧27－28；32－36）")[1]) == [("luk.6.32", "luk.6.36")]


def test_a_same_book_range_over_the_heading_itself_is_a_section_range():
    (section,) = _rows("（1‧1－7‧27）", "ezk", "ezk.1.1", "hd:ezk.1.1#1")
    assert section["kind"] == "section_range"
    assert _targets(section) == [("ezk.1.1", "ezk.7.27")]
    (inner,) = _rows("（33‧1－9）", "ezk", "ezk.3.16", "hd:ezk.3.16#1")
    assert inner["kind"] == "parallel"
    (other_book,) = _rows("（太1‧1－2‧5）", "mat", "mat.1.1", "hd:mat.1.1#1")
    assert other_book["kind"] == "parallel"


def test_a_whole_chapter_reference_spans_the_chapter():
    (row,) = _rows("（詩18）", "2sa", "2sa.22.1", "hd:2sa.22.1#1")
    assert _targets(row) == [("psa.18.1", "psa.18.50")] and row["parse_rule"] == "abbr+n"


@pytest.mark.parametrize("raw, message", [
    ("（路99‧1）", "hd:mat.21.1#1"),
    ("（路6‧27－28；32－36", "bracket"),
    ("（可1‧1；；路1‧1）", "empty"),
    ("（可1‧1；路X）", "路X"),
], ids=["no-such-chapter", "unclosed", "empty-segment", "garbage"])
def test_a_reference_that_does_not_resolve_is_a_parse_error(raw, message):
    with pytest.raises(ParseError, match=message):
        parallels.parse_line("hd:mat.21.1#1", raw, "mat", "mat.21.1")

"""S5 segmentation: pericopes open at headings, passages are cut at chapter ends."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gates import check_schema
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import segment
from ragdata.stages.s05_struct.view import key_range, text_view


def _view(text=None):
    rows = mini_build.text_layer() if text is None else text
    schema, snap = check_schema({f"{k}.jsonl": v for k, v in rows.items()}, ("text",))
    assert schema.passed, schema.details
    return text_view(snap)


def _spans(section):
    return [(p.unit.unit_key, p.start, p.end) for p in section.pieces]


def test_every_heading_position_opens_a_section_and_book_openings_without_one_do_too():
    view = _view()
    found = {b.book_id: [(s.pericope_id, s.title) for s in segment.sections(view, b.book_id)]
             for b in view.books}
    assert found == {
        "psa": [("pc:psa.42.1", "渴慕上帝")],
        "sng": [("pc:sng.1.1", None)],
        "mat": [("pc:mat.18.1", "天國裏誰是最大的")],
        "act": [("pc:act.9.1", "掃羅歸主－在路上"), ("pc:act.9.3b", "天上的光")],
        "eph": [("pc:eph.6.1", "兒女和父母")],
    }


def test_a_mid_verse_heading_cuts_its_unit_between_two_sections():
    first, second = segment.sections(_view(), "act")
    assert _spans(first) == [("act.9.1", 0, None), ("act.9.2", 0, None),
                             ("act.9.3", 0, mini_build.ACT_MID)]
    assert _spans(second) == [("act.9.3", mini_build.ACT_MID, None), ("act.10.1", 0, None)]


def test_stacked_headings_merge_into_one_section_under_the_lowest_heading():
    first = segment.sections(_view(), "act")[0]
    assert first.heading.heading_id == "hd:act.9.1#2"
    assert first.section_heading_id == "hd:act.9.1#1"
    assert [h.heading_id for h in first.headings] == ["hd:act.9.1#1", "hd:act.9.1#2"]


def test_a_stack_whose_upper_heading_is_not_the_parent_is_refused():
    rows = mini_build.text_layer()
    lower = next(h for h in rows["headings"] if h["heading_id"] == "hd:act.9.1#2")
    lower["parent_heading_id"] = None
    with pytest.raises(StageError, match="hd:act.9.1#1"):
        segment.sections(_view(rows), "act")


def test_a_heading_at_the_end_of_its_unit_is_refused():
    rows = mini_build.text_layer()
    mid = next(h for h in rows["headings"] if h["heading_id"] == "hd:act.9.3b#1")
    mid["anchor_offset"] = len(mini_build.ACT_9_3)
    with pytest.raises(StageError, match="act.9.3"):
        segment.sections(_view(rows), "act")


def test_passages_cut_a_section_at_chapter_ends():
    second = segment.sections(_view(), "act")[1]
    cut = [[p.unit.unit_key for p in pieces] for pieces in segment.passage_pieces(second)]
    assert cut == [["act.9.3"], ["act.10.1"]]


@pytest.mark.parametrize("pieces, expected", [
    ([("act.9.1", 0, None), ("act.9.3", 0, 5)], ("act.9.1", "act.9.3", "1-3")),
    ([("act.9.3", 5, None)], ("act.9.3b", "act.9.3b", "3")),
    ([("eph.6.2-3", 0, None)], ("eph.6.2", "eph.6.3", "2-3")),
])
def test_key_range_spells_the_verses_with_b_on_a_second_half(pieces, expected):
    view = _view()
    assert key_range([segment.Piece(view.unit[k], a, b) for k, a, b in pieces]) == expected

"""The GT v2 change log: every edit is replayable on v1 and reversible."""

from __future__ import annotations

import pytest

from ragdata.gt.changes import (
    Change, ChangeError, Edit, apply_changes, apply_edits, change_from_json, get_field,
    revert_changes,
)

Q = {"question_id": "Q1", "question": "問題", "reference_answer": "神照著自己的形像造人，著實好。",
     "expected_answer_points": ["神照著自己的形像造人", "造男造女"]}


def test_edits_apply_right_to_left_and_log_offsets_valid_at_their_turn():
    value = Q["reference_answer"]
    new, changes = apply_edits("Q1", "reference_answer", value,
                               [Edit(0, 1, "上帝", "gen.1.27"), Edit(2, 3, "着", None)],
                               rule="r")
    assert new == "上帝照着自己的形像造人，著實好。"
    assert [(c.offset, c.before, c.after) for c in changes] == [(2, "著", "着"), (0, "神", "上帝")]
    replayed = apply_changes([Q], changes)
    assert replayed[0]["reference_answer"] == new
    assert revert_changes(replayed, changes) == [Q]


def test_overlapping_edits_are_refused():
    with pytest.raises(ChangeError, match="overlap"):
        apply_edits("Q1", "reference_answer", "abcdef",
                    [Edit(0, 3, "x", None), Edit(2, 4, "y", None)], rule="r")


def test_list_fields_are_addressed_by_index_and_inputs_are_not_mutated():
    change = Change("Q1", "expected_answer_points[1]", 0, "造男", "造男人", "r", None)
    out = apply_changes([Q], [change])
    assert out[0]["expected_answer_points"] == ["神照著自己的形像造人", "造男人造女"]
    assert Q["expected_answer_points"][1] == "造男造女"
    assert get_field(out[0], "expected_answer_points[1]") == "造男人造女"


def test_a_new_field_is_added_and_removed_again():
    change = Change("Q1", "family", None, None, "legacy_head", "legacy_family", None)
    out = apply_changes([Q], [change])
    assert out[0]["family"] == "legacy_head"
    assert "family" not in revert_changes(out, [change])[0]


@pytest.mark.parametrize("change, message", [
    (Change("Q1", "reference_answer", 0, "上帝", "神", "r", None), "does not hold"),
    (Change("Q9", "reference_answer", 0, "神", "上帝", "r", None), "Q9"),
    (Change("Q1", "expected_answer_points[5]", 0, "神", "上帝", "r", None), r"\[5\]"),
    (Change("Q1", "question", 0, "問", "答", "r", None), "not an answer field"),
    (Change("Q1", "reference_answer", None, "神", "上帝", "r", None), "needs offset"),
])
def test_a_change_that_does_not_fit_raises(change, message):
    with pytest.raises(ChangeError, match=message):
        apply_changes([Q], [change])


def test_adding_a_field_that_is_already_there_raises():
    change = Change("Q1", "family", None, None, "x", "legacy_family", None)
    with pytest.raises(ChangeError, match="already"):
        apply_changes([{**Q, "family": "x"}], [change])


def test_json_round_trip_keeps_every_field():
    change = Change("Q1", "reference_answer", 3, "著", "着", "corpus_orthography", None)
    assert change.to_json() == {"qid": "Q1", "field": "reference_answer", "offset": 3,
                                "before": "著", "after": "着", "rule": "corpus_orthography",
                                "evidence_slot": None}
    assert change_from_json(change.to_json()) == change
    with pytest.raises(ChangeError, match="keys"):
        change_from_json({"qid": "Q1"})

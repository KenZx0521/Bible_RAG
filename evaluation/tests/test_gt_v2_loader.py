"""Loading GT v2: only the frozen bytes load, and items carry structured refs and slots."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.gt_v2 import GtV2Error, load_ground_truth_v2

QUESTION = {
    "question_id": "VERSE_LOOKUP_001", "question": "q", "question_type": "VERSE_LOOKUP",
    "book_name": "馬太福音", "reference": "馬太福音 18:1-4", "expected_answer_points": ["a"],
    "reference_answer": "r", "family": "legacy_head",
    "refs": [{"book_id": "mat", "ch": 18, "v_start": 1, "v_end": 4, "ch_end": 18}],
    "gold_slots": ["mat.18.1", "mat.18.2", "mat.18.4"], "omitted_slots": ["mat.18.3"],
}
META = {"gt_version": "v2", "slot_universe": "text@ddb48c599861",
        "kay_review": [{"qid": "VERSE_LOOKUP_001", "issue": "i", "detail": "d"}]}


def _write(tmp_path, doc=None, freeze=None):
    data = (json.dumps(doc or {"metadata": META, "questions": [QUESTION]}, ensure_ascii=False)
            + "\n").encode()
    gt = tmp_path / "ground_truth.v2.json"
    gt.write_bytes(data)
    record = {"sha256": hashlib.sha256(data).hexdigest(), "slot_universe": META["slot_universe"]}
    fz = tmp_path / "gt_v2_freeze.json"
    fz.write_text(json.dumps(record if freeze is None else {**record, **freeze}))
    return gt, fz


def test_frozen_file_loads_with_refs_slots_and_header(tmp_path):
    gt = load_ground_truth_v2(*_write(tmp_path))
    item = gt.items[0]
    assert (item.refs[0].book_id, item.refs[0].v_end) == ("mat", 4)
    assert item.gold_slots == ["mat.18.1", "mat.18.2", "mat.18.4"]
    assert item.omitted_slots == ["mat.18.3"]
    assert gt.slot_universe == "text@ddb48c599861"
    assert gt.kay_review == ("VERSE_LOOKUP_001",)
    assert len(gt.sha256) == 64


@pytest.mark.parametrize("freeze, message", [
    ({"sha256": "0" * 64}, "sha256"),
    ({"slot_universe": "text@000000000000"}, "slot_universe"),
])
def test_bytes_or_universe_other_than_the_freeze_are_refused(tmp_path, freeze, message):
    with pytest.raises(GtV2Error, match=message):
        load_ground_truth_v2(*_write(tmp_path, freeze=freeze))


def test_a_missing_freeze_is_refused(tmp_path):
    gt, fz = _write(tmp_path)
    fz.unlink()
    with pytest.raises(GtV2Error, match="freeze"):
        load_ground_truth_v2(gt, fz)


def test_a_v1_file_is_refused(tmp_path):
    doc = {"metadata": {"total_questions": 1}, "questions": [QUESTION]}
    with pytest.raises(GtV2Error, match="gt_version"):
        load_ground_truth_v2(*_write(tmp_path, doc=doc))


def test_an_item_without_gold_slots_is_refused(tmp_path):
    bad = {k: v for k, v in QUESTION.items() if k != "gold_slots"}
    with pytest.raises(GtV2Error, match="gold_slots"):
        load_ground_truth_v2(*_write(tmp_path, doc={"metadata": META, "questions": [bad]}))

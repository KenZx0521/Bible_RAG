"""quick_retrieval_eval: GT choice, build provenance and the slot ruler reach every output."""

import json
import sys

import pytest

import quick_retrieval_eval as qre
from src.data_loader import load_gt
from src.models import EvalSample, SourceInfo
from src.provenance import ProvenanceError
from src.slot_coverage import SlotCoverageError

FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}, "reranker": None}


def _main(monkeypatch, tmp_path, argv, health=None, samples=None):
    seen = {}

    async def fake_collect(gts, *args, **kwargs):
        seen["gts"] = gts
        return samples(gts), {}, {}, {}

    monkeypatch.setattr(qre, "collect", fake_collect)
    monkeypatch.setattr(qre, "fetch_health", lambda url: health or {"status": "ok"})
    monkeypatch.setattr(qre, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["quick_retrieval_eval.py", "--label", "t", *argv])
    assert qre.main() == 0
    return json.loads((tmp_path / "t.json").read_text(encoding="utf-8")), seen


def _ghost_answer(gts):
    """EVENT_QUESTION_041 (約翰福音 5:1-18) answered by its whole chapter 5 pericope."""
    gt = next(g for g in gts if g.question_id == "EVENT_QUESTION_041")
    source = SourceInfo(id="jhn:5:0", book="約翰福音", chapter=5, verse_range="1-18")
    return [EvalSample(question_id=gt.question_id, question=gt.question,
                       question_type=gt.question_type, sources=[source], ground_truth=gt)]


def test_v2_run_scores_on_slots_and_records_build_gt_and_encoder(monkeypatch, tmp_path):
    out, seen = _main(monkeypatch, tmp_path, ["--gt", "v2"],
                      health={"encoder": FINGERPRINT}, samples=_ghost_answer)

    assert len(seen["gts"]) == 500
    assert out["meta"] == {"data_build_id": "legacy-20261004", "gt_version": "v2",
                           "gt_sha": load_gt("v2").sha256, "encoder_fingerprint": FINGERPRINT}
    assert out["per_question"]["EVENT_QUESTION_041"]["verse_recall_at_k"] == 1.0


def test_v1_run_keeps_the_chapter_table_and_records_its_gt(monkeypatch, tmp_path):
    out, _ = _main(monkeypatch, tmp_path, ["--gt", "v1"], samples=_ghost_answer)

    assert out["meta"]["gt_version"] == "v1" and out["meta"]["gt_sha"] == load_gt("v1").sha256
    assert out["meta"]["encoder_fingerprint"] is None
    # v1 gold still holds the ghost verse 5:4, which the legacy pericope covers too
    assert out["per_question"]["EVENT_QUESTION_041"]["verse_recall_at_k"] == 1.0


def test_a_new_build_is_refused_against_gt_v1(monkeypatch, tmp_path):
    with pytest.raises(ProvenanceError, match="--gt v2"):
        _main(monkeypatch, tmp_path, ["--gt", "v1"],
              health={"build_id": "b20261008_0000abcd"}, samples=_ghost_answer)


def test_legacy_answers_labelled_by_a_contracts_dir_do_not_score(monkeypatch, tmp_path,
                                                                 write_contracts):
    """BACKEND_URL left on legacy prod (silent /health) while --contracts-dir names a build."""
    contracts = str(write_contracts(tmp_path / "contracts"))
    with pytest.raises(SlotCoverageError, match="legacy source"):
        _main(monkeypatch, tmp_path, ["--gt", "v2", "--contracts-dir", contracts],
              samples=_ghost_answer)


def test_a_legacy_health_handshake_is_not_relabelled_by_a_contracts_dir(monkeypatch, tmp_path,
                                                                         write_contracts):
    contracts = str(write_contracts(tmp_path / "contracts"))
    with pytest.raises(ProvenanceError, match="legacy-20261004.*holds"):
        _main(monkeypatch, tmp_path, ["--gt", "v2", "--contracts-dir", contracts],
              health={"build_id": "legacy-20261004"}, samples=_ghost_answer)


def test_from_raw_takes_the_build_from_the_checkpoints_run_meta(monkeypatch, tmp_path):
    raw_dir = tmp_path / "results"
    raw_dir.mkdir()
    (raw_dir / "raw_responses.json").write_text(json.dumps([{
        "question_id": "EVENT_QUESTION_041", "question": "q",
        "sources": [{"id": "jhn:5:0", "book": "約翰福音", "chapter": 5, "verse_range": "4"}]}]))
    (raw_dir / "run_meta.json").write_text(json.dumps(
        {"data_build_id": "legacy-20261004", "encoder_fingerprint": FINGERPRINT}))
    monkeypatch.setattr(qre, "fetch_health", lambda url: pytest.fail("from-raw must not ask /health"))
    monkeypatch.setattr(qre, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["quick_retrieval_eval.py", "--label", "t", "--gt", "v2",
                                      "--from-raw", str(raw_dir / "raw_responses.json")])

    assert qre.main() == 0
    out = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert out["meta"]["encoder_fingerprint"] == FINGERPRINT
    # the ghost verse alone covers no v2 gold
    assert out["per_question"]["EVENT_QUESTION_041"]["verse_recall_at_k"] == 0.0

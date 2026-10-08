"""quick_faithfulness_eval: the checkpoint's build picks what GT may judge it; meta records the run."""

import json
import sys

import pytest

import quick_faithfulness_eval as qfe
from src.data_loader import load_gt
from src.gt_v2 import GroundTruthItemV2
from src.models import MetricResult
from src.provenance import ProvenanceError

BUILD = "b20261008_0000abcd"
FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}}


def _checkpoint(directory, build_id=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_responses.json").write_text(json.dumps([{
        "question_id": "VERSE_LOOKUP_001", "question": "q", "rag_answer": "a", "contexts": ["c"],
        "context_source": "backend", "sources": []}]))
    if build_id is not None:
        (directory / "run_meta.json").write_text(json.dumps(
            {"data_build_id": build_id, "encoder_fingerprint": FINGERPRINT}))
    return directory


def _main(monkeypatch, tmp_path, results_dir, argv):
    judged = []

    def fake_judge(samples):
        judged.extend(samples)
        return {s.question_id: [MetricResult(name="ragas_faithfulness", value=1.0,
                                             category="llm_judge")] for s in samples}, {}

    monkeypatch.setattr(qfe, "_judge", fake_judge)
    monkeypatch.setattr(sys, "argv", ["quick_faithfulness_eval.py", "--no-rebuild",
                                      "--results-dir", str(results_dir),
                                      "--out", str(tmp_path / "out.json"), *argv])
    qfe.main()
    return json.loads((tmp_path / "out.json").read_text(encoding="utf-8")), judged


def test_meta_records_the_checkpoints_build_the_gt_and_the_encoder(monkeypatch, tmp_path):
    results = _checkpoint(tmp_path / "run", "legacy-20261004")

    out, judged = _main(monkeypatch, tmp_path, results, ["--gt", "v2"])

    assert {k: out["meta"][k] for k in ("data_build_id", "gt_version", "gt_sha",
                                        "encoder_fingerprint")} == {
        "data_build_id": "legacy-20261004", "gt_version": "v2",
        "gt_sha": load_gt("v2").sha256, "encoder_fingerprint": FINGERPRINT}
    assert isinstance(judged[0].ground_truth, GroundTruthItemV2)
    assert out["overall"]["ragas_faithfulness"] == 1.0


def test_a_checkpoint_before_run_meta_is_the_legacy_build(monkeypatch, tmp_path):
    out, _ = _main(monkeypatch, tmp_path, _checkpoint(tmp_path / "run"), ["--gt", "v1"])

    assert out["meta"]["data_build_id"] == "legacy-20261004"
    assert out["meta"]["gt_sha"] == load_gt("v1").sha256
    assert out["meta"]["encoder_fingerprint"] is None


def test_a_new_build_checkpoint_is_refused_against_gt_v1(monkeypatch, tmp_path):
    results = _checkpoint(tmp_path / "run", BUILD)

    with pytest.raises(ProvenanceError, match="--gt v2"):
        _main(monkeypatch, tmp_path, results, ["--gt", "v1"])


def test_a_new_build_checkpoint_is_judged_with_gt_v2_and_its_contracts(monkeypatch, tmp_path,
                                                                        write_contracts):
    results = _checkpoint(tmp_path / "run", BUILD)
    contracts = str(write_contracts(tmp_path / "contracts"))

    out, _ = _main(monkeypatch, tmp_path, results, ["--gt", "v2", "--contracts-dir", contracts])

    assert out["meta"]["data_build_id"] == BUILD and out["meta"]["gt_version"] == "v2"


@pytest.mark.parametrize("argv", [["--ids", "NOPE_001"], ["--limit", "1", "--ids", "NOPE_001"]],
                         ids=["unknown_ids", "empty_selection"])
def test_unknown_ids_or_nothing_to_judge_exit_non_zero(monkeypatch, tmp_path, argv):
    results = _checkpoint(tmp_path / "run")

    with pytest.raises(SystemExit) as exited:
        _main(monkeypatch, tmp_path, results, ["--gt", "v1", *argv])
    assert exited.value.code != 0


def test_tally_groups_scores_and_pairs_stored_ones_only_where_the_judge_scored():
    from src.models import EvalSample, GroundTruthItem, Rationale

    def sample(qid, qtype, family=""):
        gt = GroundTruthItem(question_id=qid, question="q", question_type=qtype, book_name="b",
                             family=family)
        return EvalSample(question_id=qid, question="q", question_type=qtype, ground_truth=gt)

    def faith(value, strict):
        return [MetricResult(name="ragas_faithfulness", value=value, category="llm_judge"),
                MetricResult(name="ragas_faithfulness_strict", value=strict, category="llm_judge")]

    samples = [sample("A", "T1"), sample("B", "T1", "fam"), sample("C", "T2")]
    metrics = {"A": faith(1.0, 0.5), "B": faith(0.5, 0.5)}
    rationales = {"A": Rationale(faithfulness_statements=[{"verdict": 1}, {"verdict": 0}])}

    tally = qfe._tally(samples, metrics, rationales, {"A": 0.25, "C": 0.0})

    assert (tally["n_scored"], tally["n_paired"]) == (2, 1)
    assert tally["overall"] == {"ragas_faithfulness": 0.75, "ragas_faithfulness_strict": 0.5,
                                "stored_faithfulness": 0.25}
    assert tally["by_type"] == {"T1": tally["overall"]}
    assert set(tally["by_family"]) == {"legacy_head", "fam"}
    assert [r["n_statements"] for r in tally["rows"]] == [2, 0, 0]
    assert tally["rows"][2]["stored_faithfulness"] == 0.0

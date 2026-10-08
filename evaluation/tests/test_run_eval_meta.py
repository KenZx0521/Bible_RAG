"""Full pipeline: the checkpoint keeps the build (run_meta.json), the report records the run meta."""

import asyncio
import json
import sys
from dataclasses import replace

import run_eval
from src import collector, evaluator
from src.data_loader import load_gt
from src.gt_v2 import GroundTruthItemV2
from src.models import EvalSample, SourceInfo
from src.provenance import Provenance, make_context

FINGERPRINT = {"embedder": {"tokenizer_sha": "a"}}


def _no_backend(monkeypatch, tmp_path):
    async def answer(*args, **kwargs):
        return {"answer": "a", "sources": [], "retrieval_stats": {"route_used": "R1"}}

    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def no_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr(collector, "query_rag", answer)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(type(collector.settings), "results_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)


def test_collection_asks_the_runs_gt_and_records_the_build_beside_the_checkpoint(monkeypatch, tmp_path):
    _no_backend(monkeypatch, tmp_path)
    ctx = make_context(load_gt("v2"), Provenance("legacy-20261004", FINGERPRINT))
    ctx = replace(ctx, gt=replace(ctx.gt, items=ctx.gt.items[:1]))

    samples, _ = asyncio.run(evaluator.run_collection(ctx))

    assert isinstance(samples[0].ground_truth, GroundTruthItemV2)
    assert json.loads((tmp_path / "run_meta.json").read_text()) == {
        "data_build_id": "legacy-20261004", "encoder_fingerprint": FINGERPRINT}


def test_report_meta_records_build_gt_and_encoder_and_scores_v2_on_slots(monkeypatch, tmp_path):
    ctx = make_context(load_gt("v2"), Provenance("legacy-20261004", FINGERPRINT))
    gt = ctx.gt.by_id()["EVENT_QUESTION_041"]
    sample = EvalSample(question_id=gt.question_id, question=gt.question,
                        question_type=gt.question_type, ground_truth=gt,
                        sources=[SourceInfo(id="jhn:5:0", book="約翰福音", chapter=5,
                                            verse_range="4")])
    for name in ("compute_semantic_similarity", "compute_coverage_metrics"):
        monkeypatch.setattr(evaluator, name, lambda samples: {})
    monkeypatch.setattr(evaluator, "compute_ragas_metrics", lambda samples: ({}, {}))
    monkeypatch.setattr(evaluator, "_save_results", lambda report: tmp_path / "r.json")

    report = evaluator.run_evaluation([sample], ctx)

    assert {k: report.meta[k] for k in ("data_build_id", "gt_version", "encoder_fingerprint")} == {
        "data_build_id": "legacy-20261004", "gt_version": "v2", "encoder_fingerprint": FINGERPRINT}
    assert report.meta["gt_sha"] == ctx.gt.sha256
    assert report.overall["verse_recall_at_k"] == 0.0   # the ghost verse is no v2 gold


def test_eval_only_reads_the_checkpoint_build_and_the_chosen_gt(monkeypatch, tmp_path):
    (tmp_path / "raw_responses.json").write_text(json.dumps([{
        "question_id": "VERSE_LOOKUP_001", "question": "q", "rag_answer": "a", "contexts": ["c"],
        "context_source": "backend", "sources": []}]))
    (tmp_path / "run_meta.json").write_text(json.dumps(
        {"data_build_id": "legacy-20261004", "encoder_fingerprint": None}))
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--eval-only", "--gt", "v2"])

    ctx = run_eval._run_context(run_eval._parse_args(), live=False)
    samples = evaluator.load_samples_from_checkpoint(gt=ctx.gt)

    assert ctx.meta()["gt_version"] == "v2" and ctx.ruler is not None
    assert isinstance(samples[0].ground_truth, GroundTruthItemV2)

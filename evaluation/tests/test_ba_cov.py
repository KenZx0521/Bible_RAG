"""book_anchor ablation coverage-only judge (experiments/2026-10-15_book_anchor/ba_cov.py).

prereg §5 量尺 / §9 3.8: an exported ans/ directory is loaded as quick_faithfulness_eval
loads it, only coverage is judged (the judge LLM is stubbed), the per-point verdicts land in
the JSON, a generation failure is null and invalid, and the meta carries generator_blocks.
"""

import json
import sys
import types
from pathlib import Path

import pytest

_EXP = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_export as bex  # noqa: E402
import _ba_io as bio  # noqa: E402
import ba_cov  # noqa: E402
import quick_faithfulness_eval as qfe  # noqa: E402
from src.data_loader import load_gt  # noqa: E402
from src.metrics import coverage_eval  # noqa: E402

GT = load_gt("v2")
Q1, Q2 = "VERSE_LOOKUP_001", "VERSE_LOOKUP_002"
META = {"kind": "meta", "mode": "retrieve", "build_id": "b20261008_e05d3e55",
        "encoder_fingerprint": {"embedder": {"x": 1}, "reranker": {"y": 2}}}


def ans_dir(tmp_path):
    rows = {}
    for qid in (Q1, Q2):
        results = [{"id": "ps:jhn.3.16", "book_name": "約翰福音", "chapter_num": 3, "title": "t",
                    "verse_range": "16", "content": "上帝愛世人", "source_strategy": "semantic",
                    "fused_score": 0.5}]
        rec = {"results": results, "ctx_sha": bio.ctx_sha(results, bex.host_blocks),
               "stats": {"route_used": "R5", "strategy_errors": {}}}
        rows[qid] = {"qid": qid, "question": GT.by_id()[qid].question,
                     "arms": {"ctrl": rec, "nopin": None, "off": None}, "arms_skipped": "x"}
    plan = [{"qid": q, "arm": "ctrl", "rep": 1, "ctx_sha": rows[q]["arms"]["ctrl"]["ctx_sha"]}
            for q in (Q1, Q2)]
    gens = [{"kind": "gen", "qid": Q1, "arm": "ctrl", "rep": 1, "answer": "上帝愛世人。",
             "ctx_sha": plan[0]["ctx_sha"]},
            {"kind": "gen", "qid": Q2, "arm": "ctrl", "rep": 1, "answer": "生成回答時發生錯誤。",
             "ctx_sha": plan[1]["ctx_sha"]}]
    return bex.export_ans([META], rows, gens, plan, tmp_path / "ans")["ctrl_r1"]


def test_coverage_only_with_point_verdicts(monkeypatch, tmp_path):
    directory = ans_dir(tmp_path)
    n_points = len(GT.by_id()[Q1].expected_answer_points)
    reply = json.dumps({"verdicts": [{"index": i, "verdict": "partial" if i == 1 else "covered"}
                                     for i in range(1, n_points + 1)]})
    calls = []

    async def judge(prompt, **kwargs):
        calls.append(prompt)
        return reply

    monkeypatch.setattr(coverage_eval, "judge_completion", judge)
    monkeypatch.setattr(qfe, "_judge", lambda s: (_ for _ in ()).throw(AssertionError("faith")))
    monkeypatch.setattr(qfe, "_run_context", lambda args, d: types.SimpleNamespace(
        gt=GT, meta=lambda: {"data_build_id": "b20261008_e05d3e55", "gt_version": "v2"}))
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps([Q1, Q2]))
    out = tmp_path / "ctrl_r1.cov.json"
    assert ba_cov.main(["--results-dir", str(directory), "--ids-file", str(ids), "--gt", "v2",
                        "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    rows = {r["question_id"]: r for r in doc["samples"]}
    want = round((n_points - 0.5) / n_points, 4)
    assert rows[Q1]["coverage"] == want and rows[Q1]["invalid"] is None
    assert rows[Q1]["judge"]["status"] == "judged"
    assert rows[Q1]["judge"]["verdicts"]["1"] == "partial"
    assert rows[Q2]["coverage"] is None and rows[Q2]["invalid"] == "generation"
    assert doc["meta"]["context_format"] == "generator_blocks"
    assert doc["meta"]["context_sources"] == {"backend": 2}
    assert doc["meta"]["coverage_only"] is True and doc["meta"]["gt_version"] == "v2"
    assert len(calls) == 2         # the judge saw both; the generation failure is voided
    assert [x.name for x in tmp_path.glob("*.tmp")] == []   # written to .tmp, then replaced


def test_a_judge_that_fails_leaves_no_output(monkeypatch, tmp_path):
    directory = ans_dir(tmp_path)

    def boom(samples):
        raise RuntimeError("judge down")

    monkeypatch.setattr(qfe, "_coverage", boom)
    monkeypatch.setattr(qfe, "_run_context", lambda args, d: types.SimpleNamespace(
        gt=GT, meta=lambda: {"data_build_id": "b20261008_e05d3e55", "gt_version": "v2"}))
    out = tmp_path / "ctrl_r1.cov.json"
    with pytest.raises(RuntimeError, match="judge down"):
        ba_cov.main(["--results-dir", str(directory), "--gt", "v2", "--out", str(out)])
    assert not out.exists() and not list(tmp_path.glob("*.tmp"))


def test_collector_records_failures():
    handler = ba_cov.VerdictCollector()
    log = __import__("logging").getLogger("ba_cov_test")
    log.addHandler(handler)
    log.setLevel("INFO")
    log.error("[Coverage] %s judge call failed: %s", "Q", RuntimeError("down"))
    log.info("[Coverage] %s => 0.000 (empty/refused answer)", "E")
    log.info("unrelated %s", "X")
    assert handler.by_qid == {"Q": {"status": "judge_failed", "error": "down"},
                              "E": {"status": "empty_answer"}}

"""evaluation_results.json / .csv as a self-contained record (2026-10-28 P0).

meta: invalid_counts / invalid_ids per metric, eval_run (when, which code, argv), the
checkpoint's run_meta.json sections, the judge models the APIs said they served.
samples: intent, mode, and the coverage audit (coverage_points, coverage_error, ...).
Every judge is stubbed; git is refused (conftest).
"""

import csv
import json
import sys
from datetime import datetime

import pytest

from src import evaluator
from src.data_loader import load_gt
from src.llm.served_models import served_models
from src.metrics.coverage_eval import CoverageOutcome
from src.models import (AggregatedReport, EvalReport, EvalSample, GroundTruthItem, MetricResult,
                        Rationale, SourceInfo)
from src.provenance import RUN_META, Provenance, make_context, write_run_meta

GT = load_gt("v2")
INTENT = {"type": "verse_lookup", "entities": [], "verse_refs": ["約翰福音3:16"], "rejected_refs": []}
POINT = {"index": 1, "point": "上帝愛世人", "verdict": "covered", "reason": "明載"}


def _sample(qid, intent=None, mode=None):
    gt = GT.by_id()[qid]
    return EvalSample(question_id=qid, question=gt.question, question_type=gt.question_type,
                      ground_truth=gt, rag_answer="a", contexts=["c"], intent=intent, mode=mode,
                      sources=[SourceInfo(id="jhn:3:16", book="約翰福音", chapter=3,
                                          verse_range="16")])


def _metric(name, value, valid=True):
    return MetricResult(name=name, value=value, category="llm_judge", valid=valid)


def _stub_judges(monkeypatch, tmp_path):
    """RAGAS: Q1 relevancy fails; coverage: Q2 incomplete twice. Results land in tmp_path."""
    q1, q2 = "VERSE_LOOKUP_001", "VERSE_LOOKUP_002"

    def ragas(samples):
        served_models.add("claude-haiku-5-5-20261001")
        return ({q1: [_metric("ragas_faithfulness", 1.0), _metric("ragas_answer_relevancy", 0.0, False)],
                 q2: [_metric("ragas_faithfulness", 0.5), _metric("ragas_answer_relevancy", 0.9)]},
                {q1: Rationale(faithfulness="1/1 statements supported",
                               errors={"ragas_answer_relevancy": "TimeoutError: "})})

    def coverage(samples):
        good = CoverageOutcome(q1, _metric("answer_coverage", 1.0), points=(POINT,), attempts=1)
        bad = CoverageOutcome(q2, _metric("answer_coverage", 0.0, False),
                              points=({**POINT, "verdict": None, "reason": ""},),
                              error="incomplete_verdicts: point 1 has no legal verdict",
                              raw='{"verdicts": []}', attempts=2)
        return {q1: [good.result], q2: [bad.result]}, {q1: good, q2: bad}

    monkeypatch.setattr(evaluator, "compute_semantic_similarity", lambda samples: {})
    monkeypatch.setattr(evaluator, "compute_ragas_metrics", ragas)
    monkeypatch.setattr(evaluator, "compute_coverage", coverage)
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))
    return q1, q2


def _ctx():
    return make_context(GT, Provenance("legacy-20261004"))


def _evaluate(monkeypatch, tmp_path):
    q1, q2 = _stub_judges(monkeypatch, tmp_path)
    samples = [_sample(q1, INTENT, "graph"), _sample(q2)]
    report = evaluator.run_evaluation(samples, _ctx())
    saved = json.loads((tmp_path / "evaluation_results.json").read_text(encoding="utf-8"))
    return q1, q2, report, saved


def test_meta_counts_and_lists_invalid_questions_per_metric(monkeypatch, tmp_path):
    q1, q2, _, saved = _evaluate(monkeypatch, tmp_path)

    meta = saved["meta"]
    assert meta["invalid_counts"]["ragas_answer_relevancy"] == 1
    assert meta["invalid_ids"]["ragas_answer_relevancy"] == [q1]
    assert meta["invalid_counts"]["answer_coverage"] == 1 and meta["invalid_ids"]["answer_coverage"] == [q2]
    assert meta["invalid_counts"]["ragas_faithfulness"] == 0 and meta["invalid_ids"]["ragas_faithfulness"] == []


def test_samples_carry_coverage_points_errors_intent_and_mode(monkeypatch, tmp_path):
    q1, q2, _, saved = _evaluate(monkeypatch, tmp_path)

    rows = {s["question_id"]: s for s in saved["samples"]}
    assert rows[q1]["rationale"]["coverage_points"] == [POINT]
    assert rows[q1]["rationale"]["faithfulness"] == "1/1 statements supported"
    assert rows[q1]["rationale"]["errors"] == {"ragas_answer_relevancy": "TimeoutError: "}
    assert (rows[q1]["intent"], rows[q1]["mode"]) == (INTENT, "graph")
    assert (rows[q2]["intent"], rows[q2]["mode"]) == (None, None)
    bad = rows[q2]["rationale"]
    assert bad["coverage_error"].startswith("incomplete_verdicts")
    assert (bad["coverage_raw"], bad["coverage_attempts"]) == ('{"verdicts": []}', 2)


def test_eval_run_records_when_which_code_and_argv(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--eval-only"])
    _, _, _, saved = _evaluate(monkeypatch, tmp_path)

    run = saved["meta"]["eval_run"]
    assert datetime.fromisoformat(run["started_at"]) <= datetime.fromisoformat(run["finished_at"])
    assert datetime.fromisoformat(run["started_at"]).tzinfo is not None
    assert run["argv"] == ["run_eval.py", "--eval-only"]
    assert run["git_head"] is None and run["git_dirty"] is None and "git_error" in run


def test_eval_run_reads_git_when_it_answers(monkeypatch, tmp_path):
    from src import run_record

    monkeypatch.setattr(run_record, "_run", lambda cmd, timeout: "abc123\n" if "rev-parse" in cmd
                        else " M evaluation/src/evaluator.py\n")
    _, _, _, saved = _evaluate(monkeypatch, tmp_path)

    run = saved["meta"]["eval_run"]
    assert (run["git_head"], run["git_dirty"]) == ("abc123", True)
    assert run["dirty_paths"] == ["evaluation/src/evaluator.py"] and "git_error" not in run


def test_the_checkpoints_run_meta_is_embedded(monkeypatch, tmp_path):
    record = {"run_meta_version": 2, "collection": {"mode": "graph", "started_at": "t"},
              "eval_code": {"error": "git"}, "backend_runtime": {"image": "bible_rag-backend:r5"},
              "generator": {"provider": "ollama", "digest": "d1"}, "backend_health": {"ok": True}}
    write_run_meta(tmp_path, Provenance("legacy-20261004"), record)

    _, _, _, saved = _evaluate(monkeypatch, tmp_path)

    assert saved["meta"]["run_meta"] == record
    assert saved["meta"]["data_build_id"] == "legacy-20261004"      # existing fields unchanged


def test_an_old_checkpoint_embeds_null(monkeypatch, tmp_path):
    _, _, _, saved = _evaluate(monkeypatch, tmp_path)

    assert saved["meta"]["run_meta"] is None


def test_judge_served_models_are_counted_when_the_api_says(monkeypatch, tmp_path):
    _, _, _, saved = _evaluate(monkeypatch, tmp_path)

    assert saved["meta"]["judge_served_models"] == {"claude-haiku-5-5-20261001": 1}


def test_no_served_model_no_field(monkeypatch, tmp_path):
    q1, q2 = _stub_judges(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluator, "compute_ragas_metrics", lambda samples: ({}, {}))

    report = evaluator.run_evaluation([_sample(q1)], _ctx())

    assert "judge_served_models" not in report.meta


def test_csv_appends_intent_type_and_mode_after_every_existing_column(monkeypatch, tmp_path):
    _, _, report, _ = _evaluate(monkeypatch, tmp_path)

    path = evaluator.export_csv(report)

    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    assert header[:5] == ["question_id", "question_type", "family", "route_used", "strategies_used"]
    assert header[-2:] == ["intent_type", "mode"]
    assert rows[1][-2:] == ["verse_lookup", "graph"] and rows[2][-2:] == ["", ""]


def test_report_samples_carry_the_samples_strategy_errors(monkeypatch, tmp_path):
    q1, _ = _stub_judges(monkeypatch, tmp_path)
    sample = _sample(q1).model_copy(update={"strategy_errors": {"event_registry": "ConnectError()"}})

    report = evaluator.run_evaluation([sample], _ctx())

    assert report.samples[0].strategy_errors == {"event_registry": "ConnectError()"}


def test_load_samples_reads_intent_and_mode_from_the_checkpoint(monkeypatch, tmp_path):
    (tmp_path / "raw_responses.json").write_text(json.dumps([
        {"question_id": "VERSE_LOOKUP_001", "rag_answer": "a", "contexts": ["c"],
         "context_source": "backend", "sources": [], "intent": INTENT, "mode": "semantic"},
        {"question_id": "VERSE_LOOKUP_002", "rag_answer": "a", "contexts": ["c"],
         "context_source": "backend", "sources": []}]), encoding="utf-8")
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))

    samples = evaluator.load_samples_from_checkpoint(gt=GT)

    assert [(s.intent, s.mode) for s in samples] == [(INTENT, "semantic"), (None, None)]


# --- B6: the new fields survive a pydantic round trip -------------------------------------

def test_new_fields_round_trip_through_the_models():
    gt = GroundTruthItem(question_id="Q", question="q", question_type="T", book_name="b", family="fam")
    sample = EvalSample(question_id="Q", question="q", question_type="T", ground_truth=gt,
                        intent=INTENT, mode="graph")
    rationale = Rationale(coverage_points=[POINT], coverage_error="unparseable",
                          coverage_raw="raw", coverage_attempts=2, errors={"ragas_x": "e"},
                          coverage_problems=["index 1 given twice (the last kept)"],
                          coverage_salvaged=True,
                          coverage_retry={"why": "unparseable", "same_reply": False})
    report = AggregatedReport(meta={"m": 1}, samples=[EvalReport(
        question_id="Q", question_type="T", family="fam", rationale=rationale, intent=INTENT,
        mode="graph", strategy_errors={"s": "e"})])

    assert EvalSample.model_validate(sample.model_dump()) == sample
    again = AggregatedReport.model_validate(json.loads(json.dumps(report.model_dump())))
    assert again == report
    assert again.samples[0].rationale.coverage_points == [POINT]
    assert again.samples[0].rationale.coverage_retry == {"why": "unparseable", "same_reply": False}
    assert again.samples[0].rationale.coverage_salvaged is True
    assert again.samples[0].family == "fam" and again.samples[0].mode == "graph"


@pytest.mark.parametrize("model, field", [
    (EvalSample, "intent"), (EvalSample, "mode"), (EvalReport, "intent"), (EvalReport, "mode"),
    (Rationale, "coverage_points"), (Rationale, "coverage_error"), (Rationale, "coverage_raw"),
    (Rationale, "coverage_attempts"), (Rationale, "errors"), (Rationale, "coverage_problems"),
    (Rationale, "coverage_salvaged"), (Rationale, "coverage_retry")])
def test_new_fields_are_declared_not_left_to_extra_ignore(model, field):
    assert field in model.model_fields


def test_load_results_keeps_the_new_fields(monkeypatch, tmp_path):
    _, _, report, _ = _evaluate(monkeypatch, tmp_path)

    loaded = evaluator.load_results()

    assert loaded.samples == report.samples
    assert loaded.meta["invalid_counts"] == report.meta["invalid_counts"]


# --- review fixes (2026-10-28): every expected metric is accounted for --------------------

def test_a_failed_ragas_run_still_lists_every_ragas_metric_as_unscored(monkeypatch, tmp_path):
    q1, q2 = _stub_judges(monkeypatch, tmp_path)
    monkeypatch.setattr(evaluator, "compute_ragas_metrics", lambda samples: (
        {}, {q: Rationale(errors={"ragas": "evaluate() failed: RuntimeError()"}) for q in (q1, q2)}))

    report = evaluator.run_evaluation([_sample(q1), _sample(q2)], _ctx())

    meta = report.meta
    for name in ("ragas_faithfulness", "ragas_answer_relevancy", "ragas_context_recall",
                 "ragas_answer_correctness"):
        assert meta["invalid_counts"][name] == 0 and meta["unscored_ids"][name] == [q1, q2], name
    assert meta["unscored_ids"]["answer_coverage"] == []


def test_a_question_ragas_skipped_is_unscored_not_silently_absent(monkeypatch, tmp_path):
    q1, q2, _, saved = _evaluate(monkeypatch, tmp_path)

    meta = saved["meta"]
    assert meta["unscored_ids"]["ragas_faithfulness"] == []
    assert meta["unscored_ids"]["ragas_context_recall"] == [q1, q2]     # the stub scored none


def test_invalid_summary_counts_expected_metrics_no_report_has():
    from src.result_audit import invalid_summary

    reports = [EvalReport(question_id="A", question_type="T", metrics=[_metric("m", 1.0)]),
               EvalReport(question_id="B", question_type="T", metrics=[_metric("m", 0.0, False)])]

    out = invalid_summary(reports, expected=["m", "ragas_x"])

    assert out["invalid_counts"] == {"m": 1, "ragas_x": 0}
    assert out["invalid_ids"] == {"m": ["B"], "ragas_x": []}
    assert out["unscored_ids"] == {"m": [], "ragas_x": ["A", "B"]}


def test_a_scored_reply_with_defects_keeps_them_in_the_results(monkeypatch, tmp_path):
    q1, q2 = _stub_judges(monkeypatch, tmp_path)

    def coverage(samples):
        out = CoverageOutcome(q1, _metric("answer_coverage", 1.0), points=(POINT,), attempts=1,
                              raw="{broken", problems=("invalid JSON: 1 index/verdict pair(s) read by pattern",),
                              salvaged=True)
        return {q1: [out.result]}, {q1: out}

    monkeypatch.setattr(evaluator, "compute_coverage", coverage)
    evaluator.run_evaluation([_sample(q1)], _ctx())
    saved = json.loads((tmp_path / "evaluation_results.json").read_text(encoding="utf-8"))

    rationale = saved["samples"][0]["rationale"]
    assert rationale["coverage_salvaged"] is True and rationale["coverage_raw"] == "{broken"
    assert rationale["coverage_problems"] == ["invalid JSON: 1 index/verdict pair(s) read by pattern"]
    assert rationale["coverage_retry"] is None

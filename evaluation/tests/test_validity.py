"""Infrastructure failures (no sources because a retriever raised) are not
retrieval misses: their metrics must be flagged invalid so aggregates skip them
instead of averaging in a 0 (VERSE_LOOKUP_035 in Round 3: ConnectTimeout,
0 sources, every metric recorded as a valid 0)."""

import pytest

from src.evaluator import _aggregate
from src.models import EvalSample, GroundTruthItem, MetricResult, SourceInfo
from src.validity import (
    answer_failure, invalidate_answer_failures, invalidate_infra_failures, is_infra_failure,
)


def _sample(qid: str, sources=(), errors=None) -> EvalSample:
    gt = GroundTruthItem(question_id=qid, question="q", question_type="VERSE_LOOKUP", book_name="b")
    return EvalSample(
        question_id=qid, question="q", question_type="VERSE_LOOKUP", ground_truth=gt,
        sources=[SourceInfo(id=s, book="b") for s in sources],
        strategy_errors=errors or {},
    )


def _metrics(value: float) -> list[MetricResult]:
    return [
        MetricResult(name="verse_recall_at_k", value=value, category="retrieval"),
        MetricResult(name="answer_coverage", value=value, category="llm_judge"),
    ]


def test_no_sources_with_errors_is_infra_failure():
    assert is_infra_failure(_sample("Q", errors={"hybrid": "ConnectTimeout()"}))


def test_no_sources_without_errors_is_a_genuine_miss():
    assert not is_infra_failure(_sample("Q"))


def test_partial_strategy_failure_with_sources_is_not_infra_failure():
    assert not is_infra_failure(_sample("Q", sources=["gen:1:0"], errors={"graph_event": "boom"}))


def test_invalidate_flags_every_metric_of_failed_samples_only():
    samples = [_sample("OK", sources=["gen:1:0"]), _sample("BAD", errors={"hybrid": "x"})]
    metrics = {"OK": _metrics(1.0), "BAD": _metrics(0.0)}

    out = invalidate_infra_failures(samples, metrics)

    assert all(m.valid for m in out["OK"])
    assert not any(m.valid for m in out["BAD"])
    # input left untouched
    assert all(m.valid for m in metrics["BAD"])


def test_aggregate_excludes_infra_failures_from_means():
    samples = [_sample("OK", sources=["gen:1:0"]), _sample("BAD", errors={"hybrid": "x"})]
    metrics = {"OK": _metrics(1.0), "BAD": _metrics(0.0)}

    report = _aggregate(samples, metrics)

    assert report.overall["verse_recall_at_k"] == 1.0
    assert report.overall["answer_coverage"] == 1.0
    bad = next(r for r in report.samples if r.question_id == "BAD")
    assert not any(m.valid for m in bad.metrics)


def _src(cid: str, strategy: str) -> SourceInfo:
    return SourceInfo(id=cid, book="b", strategy=strategy)


def test_appended_passages_alone_do_not_hide_a_failed_core():
    sample = _sample("Q", errors={"semantic": "ConnectTimeout()"})
    sample.sources = [_src("act:9:0", "event_registry")]
    assert is_infra_failure(sample)


def test_failed_auxiliary_lane_is_an_infra_failure():
    """The registry anchor could not be fetched: the treatment was not applied."""
    sample = _sample("Q", sources=["gen:1:0"], errors={"event_registry": "pg down"})
    assert is_infra_failure(sample)


GENERATION_ERRORS = ("生成回答時發生錯誤：ReadTimeout('')", "生成回答時發生錯誤。")


@pytest.mark.parametrize("answer", GENERATION_ERRORS, ids=["raised", "empty"])
def test_backend_generation_error_is_an_answer_failure(answer):
    """backend/utils/generator.py answers HTTP 200 with this text beside normal sources."""
    sample = _sample("Q", sources=["gen:1:0"]).model_copy(update={"rag_answer": answer})

    assert answer_failure(sample) == "generation"
    assert not is_infra_failure(sample)  # retrieval worked; only answer metrics are void


def test_answer_failure_reasons():
    assert answer_failure(_sample("OK", sources=["gen:1:0"])) is None
    assert answer_failure(_sample("Q", errors={"request": "HTTP 500"})) == "infra"
    assert answer_failure(_sample("Q", sources=["gen:1:0"], errors={"event_registry": "x"})) == "infra"


def test_invalidate_answer_failures_flags_generation_failures_too():
    gen = _sample("GEN", sources=["gen:1:0"]).model_copy(update={"rag_answer": GENERATION_ERRORS[0]})
    samples = [_sample("OK", sources=["gen:1:0"]), gen, _sample("BAD", errors={"hybrid": "x"})]
    metrics = {"OK": _metrics(1.0), "GEN": _metrics(0.0), "BAD": _metrics(0.0)}

    out = invalidate_answer_failures(samples, metrics)

    assert all(m.valid for m in out["OK"])
    assert not any(m.valid for m in out["GEN"] + out["BAD"])
    assert all(m.valid for m in invalidate_infra_failures(samples, metrics)["GEN"])


def test_csv_leaves_invalid_metrics_blank(tmp_path, monkeypatch):
    from src import evaluator
    samples = [_sample("OK", sources=["gen:1:0"]), _sample("BAD", errors={"hybrid": "x"})]
    report = _aggregate(samples, {"OK": _metrics(1.0), "BAD": _metrics(0.0)})
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))

    out = evaluator.export_csv(report)

    lines = out.read_text(encoding="utf-8").splitlines()
    bad = next(l for l in lines if l.startswith("BAD"))
    assert bad.endswith(",,")  # verse_recall_at_k and answer_coverage blank


def test_dashboard_marks_invalid_samples():
    from src.visualizer import _make_question_detail_table
    samples = [_sample("OK", sources=["gen:1:0"]), _sample("BAD", errors={"hybrid": "x"})]
    report = _aggregate(samples, {"OK": _metrics(1.0), "BAD": _metrics(0.0)})

    rows = {r["question_id"]: r for r in _make_question_detail_table(report)}

    assert rows["BAD"]["status"] == "invalid"
    assert rows["BAD"]["avg_score"] is None


def test_collector_marks_failed_requests_and_records_them(tmp_path, monkeypatch):
    """A request that fails every retry must come out invalid in both the live
    run and an --eval-only rerun from raw_responses.json."""
    import asyncio
    from src import collector
    from src.data_loader import load_ground_truth

    async def boom(*args, **kwargs):
        raise RuntimeError("HTTP 500")

    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def no_sleep(*args, **kwargs):
        pass

    raw = tmp_path / "raw_responses.json"
    monkeypatch.setattr(collector, "query_rag", boom)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(collector, "_raw_responses_path", lambda: raw)
    monkeypatch.setattr(collector, "_clear_previous_results", lambda: None)
    monkeypatch.setattr(type(collector.settings), "results_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)

    samples, _ = asyncio.run(collector.collect_responses([load_ground_truth()[0]]))

    assert is_infra_failure(samples[0])
    import json
    saved = json.loads(raw.read_text(encoding="utf-8"))
    assert saved[0]["sources"] == [] and "request" in saved[0]["strategy_errors"]

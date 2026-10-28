"""RAGAS per-question failures are auditable (2026-10-28 P0).

RAGAS catches every exception a metric raises for a row, logs it and scores the row NaN
(ragas.executor wrap_callable_with_index); ragas_eval turns NaN into valid=False. The
reason now lands in that question's rationale.errors. ``ragas.evaluate`` is replaced by a
stand-in that drives the metrics the way RAGAS does; no LLM is reached.
"""

import asyncio
import math
from types import SimpleNamespace

import pandas as pd
import pytest

import ragas
from src.metrics import ragas_eval as re_
from src.models import EvalSample, GroundTruthItem


class _Metric:
    """A RAGAS-like metric: single_turn_ascore(sample, callbacks, timeout=...)."""

    def __init__(self, name, outcome):
        self.name = name
        self._outcome = outcome            # float, NaN, an exception, or {question: one of those}

    async def single_turn_ascore(self, sample, callbacks=None, timeout=None):
        out = self._outcome.get(sample.user_input) if isinstance(self._outcome, dict) else self._outcome
        if isinstance(out, BaseException):
            raise out
        return out


def _fake_evaluate(dataset, metrics, **kwargs):
    """What ragas.evaluate does with per-row failures: NaN, logged, never raised."""
    async def score(metric, sample):
        try:
            return await metric.single_turn_ascore(sample, None, timeout=1)
        except Exception:
            return float("nan")

    async def all_rows():
        return [{m.name: await score(m, s) for m in metrics} for s in dataset.samples]

    rows = asyncio.run(all_rows())
    return SimpleNamespace(to_pandas=lambda: pd.DataFrame(rows), traces=[])


def _sample(qid, question):
    gt = GroundTruthItem(question_id=qid, question=question, question_type="T", book_name="b")
    return EvalSample(question_id=qid, question=question, question_type="T", ground_truth=gt,
                      rag_answer="答", contexts=["[1] 約翰福音 第3章\n16 上帝愛世人"])


@pytest.fixture
def offline_ragas(monkeypatch):
    monkeypatch.setattr(ragas, "evaluate", _fake_evaluate)
    monkeypatch.setattr(re_, "create_langchain_llm", lambda **kwargs: SimpleNamespace(temperature=None))


def test_a_failed_metric_records_why_and_valid_scores_are_untouched(offline_ragas):
    samples = [_sample("A", "qa"), _sample("B", "qb")]
    metrics = [_Metric("faithfulness", 0.75),
               _Metric("answer_relevancy", {"qa": 0.5, "qb": TimeoutError("job timed out")}),
               _Metric("context_recall", {"qa": ValueError("Failed to parse output"), "qb": 1.0})]

    results, rationales = re_._run_ragas(samples, metrics,
                                         ["faithfulness", "answer_relevancy", "context_recall"])

    by = {qid: {m.name: (m.value, m.valid) for m in ms} for qid, ms in results.items()}
    assert by["A"] == {"ragas_faithfulness": (0.75, True), "ragas_answer_relevancy": (0.5, True),
                       "ragas_context_recall": (0.0, False)}
    assert by["B"]["ragas_answer_relevancy"] == (0.0, False)
    assert rationales["A"].errors == {"ragas_context_recall": "ValueError: Failed to parse output"}
    assert rationales["B"].errors == {"ragas_answer_relevancy": "TimeoutError: job timed out"}


def test_nan_without_an_exception_is_named_as_such(offline_ragas):
    samples = [_sample("A", "qa")]

    results, rationales = re_._run_ragas(samples, [_Metric("faithfulness", math.nan)], ["faithfulness"])

    assert results["A"][0].valid is False
    assert rationales["A"].errors["ragas_faithfulness"].startswith("NaN without an exception")


def test_no_error_when_everything_scored(offline_ragas):
    _, rationales = re_._run_ragas([_sample("A", "qa")], [_Metric("faithfulness", 1.0)], ["faithfulness"])

    assert rationales["A"].errors == {}


def test_a_whole_run_failure_is_recorded_on_every_judged_question(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ragas, "evaluate", boom)
    monkeypatch.setattr(re_, "create_langchain_llm", lambda **kwargs: SimpleNamespace(temperature=None))
    samples = [_sample("A", "qa"), _sample("B", "qb").model_copy(update={"contexts": []})]

    results, rationales = re_._run_ragas(samples, [_Metric("faithfulness", 1.0)], ["faithfulness"])

    assert results == {}
    assert set(rationales) == {"A"}           # B never reached RAGAS (no contexts)
    assert rationales["A"].errors == {"ragas": "evaluate() failed: RuntimeError('rate limited')"}


def test_the_error_log_wraps_a_metric_and_re_raises():
    log = re_.MetricErrorLog()
    metric = log.watch(_Metric("context_recall", KeyError("reference")))
    sample = SimpleNamespace(user_input="q", response="a", retrieved_contexts=["c"])

    with pytest.raises(KeyError):
        asyncio.run(metric.single_turn_ascore(sample, None, timeout=1))

    assert log.errors_for("q", "a", ["c"]) == {"context_recall": "KeyError: 'reference'"}
    assert log.errors_for("q", "a", ["other"]) == {}

"""
Sample validity: tell infrastructure failures apart from genuine misses.

A sample with no sources is a real retrieval miss when every retriever ran
and found nothing, but an infrastructure failure when it is empty because a
retriever raised (Round 3 VERSE_LOOKUP_035: Qdrant ConnectTimeout, 0 sources,
every metric stored as a valid 0 and averaged into the run). Failed samples
keep their metric values but are flagged invalid so aggregates skip them.

Answer metrics have one more failure: the backend's generator catches LLM
errors and answers HTTP 200 with its error message beside normal sources
(backend/utils/generator.py), which a judge would otherwise score as a valid
answer (R1 prereg G-ANS counts it as 生成失敗 in n_invalid).
"""

from __future__ import annotations

from .models import EvalSample, MetricResult


# Sources appended after the top-k (graph auxiliary lanes); they say nothing
# about whether core retrieval worked.
AUXILIARY_STRATEGIES = frozenset({"event_registry"})

# backend/utils/generator.py: "生成回答時發生錯誤：{e}" when the LLM call raised,
# "生成回答時發生錯誤。" when it came back empty.
GENERATION_ERROR_PREFIX = "生成回答時發生錯誤"


def is_infra_failure(sample: EvalSample) -> bool:
    """The pipeline failed, not retrieval.

    * no core sources (appended auxiliary passages aside) and a strategy error;
    * or an auxiliary lane raised: the treatment under test was not applied.
    """
    errors = sample.strategy_errors
    if any(name in AUXILIARY_STRATEGIES for name in errors):
        return True
    core = [s for s in sample.sources if s.strategy not in AUXILIARY_STRATEGIES]
    return not core and bool(errors)


def is_generation_failure(sample: EvalSample) -> bool:
    """The answer is the backend's generation-error message, not an answer."""
    return sample.rag_answer.startswith(GENERATION_ERROR_PREFIX)


def answer_failure(sample: EvalSample) -> str | None:
    """Why the answer cannot be judged: "infra", "generation", or None when it can."""
    if is_infra_failure(sample):
        return "infra"
    return "generation" if is_generation_failure(sample) else None


def _invalidate(
    metrics: dict[str, list[MetricResult]], failed: set[str],
) -> dict[str, list[MetricResult]]:
    return {
        qid: [m.model_copy(update={"valid": False}) for m in ms] if qid in failed else list(ms)
        for qid, ms in metrics.items()
    }


def invalidate_infra_failures(
    samples: list[EvalSample],
    metrics: dict[str, list[MetricResult]],
) -> dict[str, list[MetricResult]]:
    """Return a copy of ``metrics`` with every metric of failed samples marked invalid."""
    return _invalidate(metrics, {s.question_id for s in samples if is_infra_failure(s)})


def invalidate_answer_failures(
    samples: list[EvalSample],
    metrics: dict[str, list[MetricResult]],
) -> dict[str, list[MetricResult]]:
    """Same, for answer metrics: generation failures are invalid too (answer_failure)."""
    return _invalidate(metrics, {s.question_id for s in samples if answer_failure(s)})

"""
Sample validity: tell infrastructure failures apart from genuine misses.

A sample with no sources is a real retrieval miss when every retriever ran
and found nothing, but an infrastructure failure when it is empty because a
retriever raised (Round 3 VERSE_LOOKUP_035: Qdrant ConnectTimeout, 0 sources,
every metric stored as a valid 0 and averaged into the run). Failed samples
keep their metric values but are flagged invalid so aggregates skip them.
"""

from __future__ import annotations

from .models import EvalSample, MetricResult


# Sources appended after the top-k (graph auxiliary lanes); they say nothing
# about whether core retrieval worked.
AUXILIARY_STRATEGIES = frozenset({"event_registry"})


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


def invalidate_infra_failures(
    samples: list[EvalSample],
    metrics: dict[str, list[MetricResult]],
) -> dict[str, list[MetricResult]]:
    """Return a copy of ``metrics`` with every metric of failed samples marked invalid."""
    failed = {s.question_id for s in samples if is_infra_failure(s)}
    return {
        qid: [m.model_copy(update={"valid": False}) for m in ms] if qid in failed else list(ms)
        for qid, ms in metrics.items()
    }

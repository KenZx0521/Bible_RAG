"""
RAGAS framework evaluation using the configured eval LLM provider as judge.

Metrics:
  - Faithfulness         zh judge: sees the user question and the header-bearing
                         context blocks the generator saw (main reading)
  - Faithfulness strict  RAGAS default NLI prompt on the same context (gate);
                         optional via EVAL_FAITHFULNESS_STRICT
  - Answer Relevancy
  - Context Recall
  - Answer Correctness

Faithfulness rationale comes from our own verdict log (every statement, both
judges); the other metrics' reasoning is extracted from RAGAS traces
(https://github.com/explodinggradients/ragas/issues/2296).

Failures: RAGAS catches whatever a metric raises for a row (judge timeout, an
unparseable reply, ...), only logs it, and scores the row NaN, which becomes
valid=False here. ``metric_errors`` keeps each such exception per row, so the
question's rationale.errors says why ({"ragas_<metric>": "TimeoutError: ..."}; a
NaN without an exception is named as such). Valid scores are untouched.

Judge temperature: RAGAS 0.4.3 overrides the LangChain model temperature on
every call (0.01 for single completions), so the value set in
``langchain_factory`` never reaches the judge. Claude is the exception: its
4.7+ models (Haiku 5.5 included) reject `temperature`, so the override is
bypassed (``_wrap_judge_llm``) and the judge samples at the model default.
"""

from __future__ import annotations

import asyncio
import logging
import typing as t

from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult, Rationale
from ..llm import create_langchain_llm
from ..llm.served_models import ServedModelCallback
from .faithfulness_zh import (
    STRICT_METRIC_NAME,
    ZH_METRIC_NAME,
    FaithfulnessStrict,
    FaithfulnessZh,
    build_faithfulness_rationale,
    log_key,
    statement_cache,
    verdict_log,
)

console = Console()
logger = logging.getLogger(__name__)

_ERROR_LIMIT = 500
NAN_WITHOUT_EXCEPTION = ("NaN without an exception: the metric returned no score "
                         "(e.g. nothing to judge, such as no statements decomposed)")
NO_SCORE_COLUMN = "no score: RAGAS returned no column for this metric"


class MetricErrorLog:
    """Per-row exceptions each metric raised, keyed like faithfulness_zh's verdict log."""

    def __init__(self) -> None:
        self._log: dict[t.Hashable, dict[str, str]] = {}

    def reset(self) -> None:
        self._log = {}

    def record(self, metric_name: str, key: t.Hashable, exc: BaseException) -> None:
        self._log.setdefault(key, {})[metric_name] = f"{type(exc).__name__}: {exc}"[:_ERROR_LIMIT]

    def errors_for(self, question: str, answer: str, contexts: list[str]) -> dict[str, str]:
        return dict(self._log.get(log_key(question, answer, list(contexts)), {}))

    def watch(self, metric):
        """Wrap ``metric.single_turn_ascore`` (what RAGAS's executor calls per row) to record
        an exception before re-raising it; returns the metric."""
        inner = metric.single_turn_ascore

        async def single_turn_ascore(sample, *args, **kwargs):
            try:
                return await inner(sample, *args, **kwargs)
            except BaseException as exc:
                key = log_key(sample.user_input, sample.response, list(sample.retrieved_contexts or []))
                self.record(metric.name, key, exc)
                raise

        metric.single_turn_ascore = single_turn_ascore
        return metric


metric_errors = MetricErrorLog()


def _extract_reason_from_trace(trace: dict, metric_key: str) -> str:
    """
    Extract reasoning from a single trace for a specific metric.

    Based on: https://github.com/explodinggradients/ragas/issues/2296

    RAGAS trace structure:
    - trace[metric_key][prompt_name]['output'] -> Pydantic object
    - For Faithfulness: NLIStatementOutput.statements -> list[StatementFaithfulnessAnswer]
    - For AnswerCorrectness: ClassificationWithReason.TP/FP/FN -> list[StatementsWithReason]
    - Each has: statement, reason, verdict
    """
    if not trace or metric_key not in trace:
        return ""

    metric_trace = trace[metric_key]
    reasons = []

    for prompt_name, prompt_data in metric_trace.items():
        if not isinstance(prompt_data, dict):
            continue

        output = prompt_data.get('output')
        if output is None:
            continue

        # Handle Pydantic objects (RAGAS returns these)

        # 1. Try 'statements' attribute (for Faithfulness, ContextPrecision, etc.)
        statements = getattr(output, 'statements', None)
        if statements and isinstance(statements, list):
            for stmt in statements:
                reason = getattr(stmt, 'reason', None) or getattr(stmt, 'reasoning', None)
                if reason:
                    reasons.append(str(reason))
            continue

        # 2. Try TP/FP/FN attributes (for AnswerCorrectness)
        for attr in ['TP', 'FP', 'FN']:
            items = getattr(output, attr, None)
            if items and isinstance(items, list):
                for item in items:
                    reason = getattr(item, 'reason', None)
                    if reason:
                        reasons.append(str(reason))

        # 3. Try direct 'reason' attribute
        reason = getattr(output, 'reason', None) or getattr(output, 'reasoning', None)
        if reason:
            reasons.append(str(reason))
            continue

        # 4. Fallback: try dict access
        if isinstance(output, dict):
            reason = output.get('reason', '') or output.get('reasoning', '')
            if reason:
                reasons.append(str(reason))
        elif isinstance(output, list):
            for item in output:
                if hasattr(item, 'reason'):
                    reasons.append(str(item.reason))
                elif isinstance(item, dict):
                    reason = item.get('reason', '') or item.get('reasoning', '')
                    if reason:
                        reasons.append(str(reason))

    # Deduplicate and limit length
    unique_reasons = list(dict.fromkeys(reasons))  # preserve order, remove duplicates
    return " | ".join(unique_reasons[:5]) if unique_reasons else ""  # limit to 5 reasons


# compute_ragas_metrics scores these beside faithfulness (zh, and strict per settings).
OTHER_RAGAS_METRICS = ("answer_relevancy", "context_recall", "answer_correctness")


def expected_metric_names() -> list[str]:
    """Every ragas_* metric compute_ragas_metrics scores (the audit's per-metric denominators)."""
    faith = [ZH_METRIC_NAME, *([STRICT_METRIC_NAME] if settings.eval_faithfulness_strict else [])]
    return [f"ragas_{name}" for name in (*faith, *OTHER_RAGAS_METRICS)]


def faithfulness_metrics() -> list:
    """The faithfulness metric instances for this run (zh always; strict per settings)."""
    metrics = [FaithfulnessZh()]
    if settings.eval_faithfulness_strict:
        metrics.append(FaithfulnessStrict())
    return metrics


def build_run_config():
    """RAGAS RunConfig tuned per provider (Ollama serializes inference)."""
    from ragas.run_config import RunConfig

    # Ollama serializes inference per model. max_workers=1 prevents the second
    # worker's asyncio.wait_for clock from starting while it sits in the semaphore
    # queue. timeout covers multi-call metrics (Faithfulness chains 2 LLM calls,
    # ContextPrecision fires one per retrieved context). max_retries=1 because
    # retrying a 30-minute-worst-case slow judge only compounds the delay.
    is_ollama = settings.eval_llm_provider.lower() == "ollama"
    return RunConfig(
        timeout=1800 if is_ollama else settings.eval_ragas_timeout,
        max_workers=1 if is_ollama else settings.eval_ragas_workers,
        max_retries=1 if is_ollama else 3,
        max_wait=30,
    )


def _wrap_judge_llm(llm, run_config):
    """The judge as evaluate() would wrap it, minus RAGAS's temperature override for Claude.

    RAGAS sets temperature=0.01 on every async call, which Claude 4.7+ models
    (Haiku 5.5 included) reject with a 400.
    """
    from ragas.llms import LangchainLLMWrapper

    return LangchainLLMWrapper(
        llm,
        run_config=run_config,
        bypass_temperature=settings.eval_llm_provider.lower() == "claude",
    )


def build_ragas_dataset(samples: list[EvalSample]):
    """RAGAS EvaluationDataset over samples that have an answer and contexts."""
    from ragas import EvaluationDataset, SingleTurnSample

    ragas_samples = []
    valid_ids = []
    for sample in samples:
        if not sample.rag_answer or not sample.contexts:
            continue
        ragas_samples.append(
            SingleTurnSample(
                user_input=sample.question,
                response=sample.rag_answer,
                retrieved_contexts=sample.contexts,
                reference=sample.reference_answer or "",
            )
        )
        valid_ids.append(sample.question_id)
    dataset = EvaluationDataset(samples=ragas_samples) if ragas_samples else None
    return dataset, valid_ids


def _faithfulness_rationale_fields(sample: EvalSample) -> dict:
    """Rationale fields for one sample from the faithfulness verdict log ("" for a judge that did not run)."""
    entries = verdict_log.entries(log_key(sample.question, sample.rag_answer, sample.contexts))
    return {
        "faithfulness": build_faithfulness_rationale(entries, "verdict", "reason"),
        "faithfulness_strict": build_faithfulness_rationale(entries, "strict_verdict", "strict_reason"),
        "faithfulness_statements": entries,
    }


def _metric_result(name: str, val, errors: dict[str, str], sample_errors: dict[str, str]) -> MetricResult:
    """One RAGAS score; NaN / missing is invalid and its reason goes into ``errors``."""
    is_nan = isinstance(val, float) and val != val
    is_valid = val is not None and not is_nan
    if not is_valid:
        errors[f"ragas_{name}"] = sample_errors.get(name) or (
            NO_SCORE_COLUMN if val is None else NAN_WITHOUT_EXCEPTION)
    return MetricResult(name=f"ragas_{name}", value=round(float(val), 4) if is_valid else 0.0,
                        category="llm_judge", valid=is_valid)


def _run_failed(valid_ids: list[str], error: BaseException) -> tuple[dict, dict[str, Rationale]]:
    """No scores; every question RAGAS was given says why in rationale.errors."""
    message = f"evaluate() failed: {error!r}"[:_ERROR_LIMIT]
    return {}, {qid: Rationale(errors={"ragas": message}) for qid in valid_ids}


def _run_ragas(
    samples: list[EvalSample],
    metrics: list,
    metric_names: list[str],
    embeddings=None,
) -> tuple[dict[str, list[MetricResult]], dict[str, Rationale]]:
    """Shared engine: evaluate `metrics` over samples and extract rationales."""
    from ragas import evaluate

    provider = settings.eval_llm_provider
    logger.info("[RAGAS] Initializing LangChain LLM (provider=%s)", provider)
    llm = create_langchain_llm(callbacks=[ServedModelCallback()])

    dataset, valid_ids = build_ragas_dataset(samples)
    if dataset is None:
        console.print("[yellow]No valid samples for RAGAS evaluation.[/yellow]")
        return {}, {}
    by_id = {s.question_id: s for s in samples}
    logger.info("[RAGAS] Built dataset with %d valid samples (skipped %d)",
                len(valid_ids), len(samples) - len(valid_ids))

    run_config = build_run_config()
    logger.info("[RAGAS] Starting evaluation with %d metrics (%s; timeout=%ds, workers=%d)...",
                len(metrics), ", ".join(metric_names), run_config.timeout, run_config.max_workers)

    # One statement decomposition per row is shared by both faithfulness
    # metrics; the verdict log feeds the rationale. Both are per-run state.
    statement_cache.reset()
    verdict_log.reset()
    metric_errors.reset()

    try:
        result = evaluate(
            dataset=dataset,
            metrics=[metric_errors.watch(m) for m in metrics],
            llm=_wrap_judge_llm(llm, run_config),
            embeddings=embeddings,
            run_config=run_config,
        )
    except (Exception, asyncio.CancelledError) as e:
        # CancelledError (BaseException) can escape evaluate() when a per-job
        # timeout cancels a shared coroutine; treat it like any judge failure.
        logger.error("[RAGAS] Evaluation failed: %r", e, exc_info=True)
        console.print(f"[red]RAGAS evaluation failed: {e!r}[/red]")
        return _run_failed(valid_ids, e)

    df = result.to_pandas()
    all_columns = list(df.columns)
    logger.info("[RAGAS] DataFrame columns: %s", all_columns)
    traces = getattr(result, 'traces', None) or []

    def get_df_reason(row, metric_name: str) -> str:
        for col in (f"{metric_name}_reason", f"{metric_name}_reasoning"):
            if col in all_columns:
                val = row.get(col, "")
                if val and isinstance(val, str):
                    return val
        return ""

    results: dict[str, list[MetricResult]] = {}
    rationales: dict[str, Rationale] = {}

    for i, qid in enumerate(valid_ids):
        if i >= len(df):
            break
        row = df.iloc[i]
        sample = by_id[qid]

        # Timeout / LLM failure surfaces as NaN in the DataFrame; tag those with
        # valid=False so aggregation can skip them instead of coercing to 0.0,
        # and keep why (the exception the metric raised, if any).
        sample_errors = metric_errors.errors_for(sample.question, sample.rag_answer, sample.contexts)
        errors: dict[str, str] = {}
        metric_results = [_metric_result(name, row.get(name, None), errors, sample_errors)
                          for name in metric_names]
        results[qid] = metric_results

        trace = traces[i] if i < len(traces) else {}
        fields = _faithfulness_rationale_fields(sample)
        if not fields["faithfulness"]:
            fields["faithfulness"] = (
                get_df_reason(row, "faithfulness")
                or _extract_reason_from_trace(trace, "faithfulness")
            )
        rationales[qid] = Rationale(
            relevance=get_df_reason(row, "answer_relevancy") or _extract_reason_from_trace(trace, "answer_relevancy"),
            context=get_df_reason(row, "context_recall") or _extract_reason_from_trace(trace, "context_recall"),
            overall=get_df_reason(row, "answer_correctness") or _extract_reason_from_trace(trace, "answer_correctness"),
            errors=errors,
            **fields,
        )
        logger.info("[RAGAS] %s => %s", qid, {m.name: m.value for m in metric_results})

    console.print(f"[green]RAGAS evaluation complete for {len(results)} samples.[/green]")
    has_rationale_count = sum(
        1 for r in rationales.values()
        if r.faithfulness or r.relevance or r.context or r.overall
    )
    logger.info("[RAGAS] %d/%d samples have reasoning.", has_rationale_count, len(rationales))
    if has_rationale_count == 0:
        console.print("[yellow]Warning: No reasoning extracted from RAGAS.[/yellow]")
    return results, rationales


def compute_ragas_metrics(
    samples: list[EvalSample],
) -> tuple[dict[str, list[MetricResult]], dict[str, Rationale]]:
    """
    Run the full RAGAS metric set on all samples.

    Returns: (
        { question_id: [MetricResult, ...] },
        { question_id: Rationale }
    )
    """
    from ragas.metrics import ResponseRelevancy, LLMContextRecall, AnswerCorrectness
    from langchain_huggingface import HuggingFaceEmbeddings

    console.print(f"[bold]Running RAGAS evaluation with {settings.eval_llm_provider}...[/bold]")
    logger.info("[RAGAS] Initializing HuggingFaceEmbeddings model=BAAI/bge-m3 (device=cpu)")
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3", model_kwargs={"device": "cpu"})

    faith = faithfulness_metrics()
    metrics = [*faith, ResponseRelevancy(), LLMContextRecall(), AnswerCorrectness()]
    metric_names = [m.name for m in faith] + list(OTHER_RAGAS_METRICS)
    return _run_ragas(samples, metrics, metric_names, embeddings=embeddings)


def compute_faithfulness_only(
    samples: list[EvalSample],
) -> tuple[dict[str, list[MetricResult]], dict[str, Rationale]]:
    """Faithfulness (zh + strict) only — the quick re-judge loop for prompt/context A/B."""
    console.print(f"[bold]Running faithfulness-only RAGAS evaluation with {settings.eval_llm_provider}...[/bold]")
    faith = faithfulness_metrics()
    return _run_ragas(samples, faith, [m.name for m in faith])

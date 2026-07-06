"""
RAGAS framework evaluation using the configured eval LLM provider as judge.

Metrics:
  - Faithfulness
  - Answer Relevancy
  - Context Recall
  - Answer Correctness

Extracts reasoning from:
  1. DataFrame columns (*_reason)
  2. results.traces for detailed prompt outputs
"""

from __future__ import annotations

import logging

from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult, Rationale
from ..llm import create_langchain_llm

console = Console()
logger = logging.getLogger(__name__)


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


def compute_ragas_metrics(
    samples: list[EvalSample],
) -> tuple[dict[str, list[MetricResult]], dict[str, Rationale]]:
    """
    Run RAGAS evaluation on all samples using Claude as judge.
    Extracts reasoning from traces for rationale.

    Returns: (
        { question_id: [MetricResult, ...] },
        { question_id: Rationale }
    )
    """
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        Faithfulness,
        ResponseRelevancy,
        LLMContextRecall,
        AnswerCorrectness,
    )
    from ragas.run_config import RunConfig
    from langchain_huggingface import HuggingFaceEmbeddings

    provider = settings.eval_llm_provider
    console.print(f"[bold]Running RAGAS evaluation with {provider}...[/bold]")

    # Setup LLM and embeddings
    logger.info("[RAGAS] Initializing LangChain LLM (provider=%s)", provider)
    llm = create_langchain_llm()
    logger.info("[RAGAS] Initializing HuggingFaceEmbeddings model=BAAI/bge-m3 (device=cpu)")
    embeddings = HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={"device": "cpu"},
    )

    # Build RAGAS dataset
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

    if not ragas_samples:
        console.print("[yellow]No valid samples for RAGAS evaluation.[/yellow]")
        return {}, {}

    logger.info("[RAGAS] Built dataset with %d valid samples (skipped %d)",
                len(ragas_samples), len(samples) - len(ragas_samples))
    dataset = EvaluationDataset(samples=ragas_samples)

    metrics = [
        Faithfulness(),
        ResponseRelevancy(),
        LLMContextRecall(),
        AnswerCorrectness(),
    ]

    metric_names = [
        "faithfulness",
        "answer_relevancy",
        "context_recall",
        "answer_correctness",
    ]

    # Column mapping for scores
    col_map = {
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
        "context_recall": "context_recall",
        "answer_correctness": "answer_correctness",
    }

    # Trace keys mapping
    trace_keys = {
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
        "context_recall": "context_recall",
        "answer_correctness": "answer_correctness",
    }

    # Ollama serializes inference per model. max_workers=1 prevents the second
    # worker's asyncio.wait_for clock from starting while it sits in the semaphore
    # queue. timeout covers multi-call metrics (Faithfulness chains 2 LLM calls,
    # ContextPrecision fires one per retrieved context). max_retries=1 because
    # retrying a 30-minute-worst-case slow judge only compounds the delay.
    is_ollama = settings.eval_llm_provider.lower() == "ollama"
    run_config = RunConfig(
        timeout=1800 if is_ollama else settings.eval_ragas_timeout,
        max_workers=1 if is_ollama else settings.eval_ragas_workers,
        max_retries=1 if is_ollama else 3,
        max_wait=30,
    )
    logger.info("[RAGAS] Starting evaluation with %d metrics (timeout=%ds, workers=%d)...",
                len(metrics), run_config.timeout, run_config.max_workers)

    try:
        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
            run_config=run_config,
        )

        df = result.to_pandas()
        all_columns = list(df.columns)
        logger.info("[RAGAS] DataFrame columns: %s", all_columns)

        # Method 1: Check for reason columns in DataFrame
        reason_columns = [col for col in all_columns if 'reason' in col.lower()]
        logger.info("[RAGAS] Reason columns found: %s", reason_columns)

        # Method 2: Check for traces
        traces = getattr(result, 'traces', None)
        has_traces = traces is not None and len(traces) > 0
        logger.info("[RAGAS] Traces available: %s (count: %d)",
                    has_traces, len(traces) if traces else 0)

        if has_traces and traces:
            sample_trace = traces[0]
            logger.info("[RAGAS] Sample trace keys: %s", list(sample_trace.keys()))
            # Log structure of first metric trace for debugging
            for key in list(sample_trace.keys())[:1]:
                metric_trace = sample_trace[key]
                logger.info("[RAGAS] Trace '%s' prompts: %s", key, list(metric_trace.keys()) if isinstance(metric_trace, dict) else type(metric_trace))

        results: dict[str, list[MetricResult]] = {}
        rationales: dict[str, Rationale] = {}

        for i, qid in enumerate(valid_ids):
            if i >= len(df):
                break
            row = df.iloc[i]

            # Extract scores. Timeout / LLM failure surfaces as NaN in the
            # DataFrame; we tag those with valid=False so aggregation can skip
            # them instead of coercing to 0.0 (which would drag category means).
            metric_results = []
            for name in metric_names:
                col = col_map.get(name, name)
                val = row.get(col, None)
                is_nan = isinstance(val, float) and val != val
                is_valid = val is not None and not is_nan
                metric_results.append(
                    MetricResult(
                        name=f"ragas_{name}",
                        value=round(float(val), 4) if is_valid else 0.0,
                        category="llm_judge",
                        valid=is_valid,
                    )
                )
            results[qid] = metric_results

            # Extract reasoning - Method 1: DataFrame reason columns
            def get_df_reason(metric_name: str) -> str:
                possible_cols = [
                    f"{metric_name}_reason",
                    f"{col_map.get(metric_name, metric_name)}_reason",
                    f"{metric_name}_reasoning",
                ]
                for col in possible_cols:
                    if col in all_columns:
                        val = row.get(col, "")
                        if val and isinstance(val, str):
                            return val
                return ""

            # Extract reasoning - Method 2: Traces
            trace = traces[i] if has_traces and i < len(traces) else {}

            # Combine both methods
            faithfulness_reason = (
                get_df_reason("faithfulness") or
                _extract_reason_from_trace(trace, trace_keys["faithfulness"])
            )
            relevance_reason = (
                get_df_reason("answer_relevancy") or
                _extract_reason_from_trace(trace, trace_keys["answer_relevancy"])
            )
            context_reason = (
                get_df_reason("context_recall") or
                _extract_reason_from_trace(trace, trace_keys["context_recall"])
            )
            overall_reason = (
                get_df_reason("answer_correctness") or
                _extract_reason_from_trace(trace, trace_keys["answer_correctness"])
            )

            rationales[qid] = Rationale(
                faithfulness=faithfulness_reason,
                relevance=relevance_reason,
                context=context_reason,
                overall=overall_reason,
            )

            logger.info("[RAGAS] %s => %s", qid, {m.name: m.value for m in metric_results})

        console.print(f"[green]RAGAS evaluation complete for {len(results)} samples.[/green]")

        # Statistics
        has_rationale_count = sum(
            1 for r in rationales.values()
            if r.faithfulness or r.relevance or r.context or r.overall
        )
        logger.info("[RAGAS] %d/%d samples have reasoning.", has_rationale_count, len(rationales))

        if has_rationale_count == 0:
            console.print("[yellow]Warning: No reasoning extracted from RAGAS.[/yellow]")

        return results, rationales

    except Exception as e:
        logger.error("[RAGAS] Evaluation failed: %s", e, exc_info=True)
        console.print(f"[red]RAGAS evaluation failed: {e}[/red]")
        return {}, {}

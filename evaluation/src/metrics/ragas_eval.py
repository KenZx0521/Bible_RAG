"""
RAGAS framework evaluation using Claude as the LLM judge.

Metrics:
  - Faithfulness
  - Answer Relevancy
  - Context Precision
  - Context Recall
  - Answer Correctness
"""

from __future__ import annotations

import logging

from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult

console = Console()
logger = logging.getLogger(__name__)


def compute_ragas_metrics(samples: list[EvalSample]) -> dict[str, list[MetricResult]]:
    """
    Run RAGAS evaluation on all samples using Claude as judge.

    Returns: { question_id: [MetricResult, ...] }
    """
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        Faithfulness,
        ResponseRelevancy,
        LLMContextPrecisionWithoutReference,
        LLMContextRecall,
        AnswerCorrectness,
    )
    from langchain_anthropic import ChatAnthropic
    from langchain_huggingface import HuggingFaceEmbeddings

    console.print("[bold]Running RAGAS evaluation with Claude...[/bold]")

    # Setup LLM and embeddings
    logger.info("[RAGAS] Initializing ChatAnthropic  model=%s", settings.claude_model)
    llm = ChatAnthropic(
        model=settings.claude_model,
        anthropic_api_key=settings.anthropic_api_key,
        temperature=0.0,
        max_tokens=10000,
    )
    logger.info("[RAGAS] Initializing HuggingFaceEmbeddings  model=BAAI/bge-m3")
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

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
        return {}

    logger.info("[RAGAS] Built dataset with %d valid samples (skipped %d)",
                len(ragas_samples), len(samples) - len(ragas_samples))
    dataset = EvaluationDataset(samples=ragas_samples)

    metrics = [
        Faithfulness(),
        ResponseRelevancy(),
        LLMContextPrecisionWithoutReference(),
        LLMContextRecall(),
        AnswerCorrectness(),
    ]

    metric_names = [
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "answer_correctness",
    ]

    logger.info("[RAGAS] Starting evaluation with %d metrics (Claude API calls will follow)...",
                len(metrics))

    try:
        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
        )

        df = result.to_pandas()
        logger.info("[RAGAS] DataFrame columns: %s", list(df.columns))
        results: dict[str, list[MetricResult]] = {}

        # Map RAGAS column names
        col_map = {
            "faithfulness": "faithfulness",
            "answer_relevancy": "answer_relevancy",
            "context_precision": "llm_context_precision_without_reference",
            "context_recall": "context_recall",
            "answer_correctness": "answer_correctness",
        }

        for i, qid in enumerate(valid_ids):
            if i >= len(df):
                break
            row = df.iloc[i]
            metric_results = []
            for name in metric_names:
                col = col_map.get(name, name)
                val = row.get(col, 0.0)
                if val is None or (isinstance(val, float) and val != val):  # NaN check
                    val = 0.0
                metric_results.append(
                    MetricResult(name=f"ragas_{name}", value=round(float(val), 4), category="llm_judge")
                )
            results[qid] = metric_results
            logger.info("[RAGAS] %s => %s",
                        qid, {m.name: m.value for m in metric_results})

        console.print(f"[green]RAGAS evaluation complete for {len(results)} samples.[/green]")
        logger.info("[RAGAS] Evaluation complete. %d samples evaluated.", len(results))
        return results

    except Exception as e:
        logger.error("[RAGAS] Evaluation failed: %s", e, exc_info=True)
        console.print(f"[red]RAGAS evaluation failed: {e}[/red]")
        return {}

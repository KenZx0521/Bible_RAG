"""
Custom LLM-as-Judge evaluation using the configured eval LLM provider.

Metrics:
  - Answer Point Coverage: checks if each expected_answer_point is covered by the RAG answer

Provides both:
  - evaluate_point_coverage_async() — for inline per-question use during collection
  - compute_llm_judge_metrics()     — for batch use (wraps the async version)
"""

from __future__ import annotations

import asyncio
import logging

from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult
from ..llm import judge_completion

console = Console()
logger = logging.getLogger(__name__)


async def _judge_point_coverage(
    question: str,
    rag_answer: str,
    point: str,
) -> bool:
    """Ask the eval LLM to judge if a single answer point is covered."""
    prompt = f"""你是一個嚴格的評估員。請判斷以下 RAG 系統的回答是否涵蓋了指定的答案要點。

問題：{question}

RAG 回答：{rag_answer}

答案要點：{point}

請只回答 "YES" 或 "NO"。
- YES：回答中明確包含或實質涵蓋了這個要點的核心意思
- NO：回答中未包含這個要點，或只是模糊提及"""

    try:
        logger.info("[Eval LLM] Judging point: %r", point[:40])
        answer = await judge_completion(prompt, max_tokens=10, temperature=0.0)
        covered = answer.upper().startswith("YES")
        logger.info("[Eval LLM] answer=%s  covered=%s", answer, covered)
        return covered
    except Exception as e:
        logger.error("[Eval LLM] Judge request failed: %s", e)
        return False


async def evaluate_point_coverage_async(sample: EvalSample) -> float:
    """
    Compute the fraction of expected answer points covered by the RAG answer.

    This is the per-question async entry point, called inline during collection.
    """
    points = sample.ground_truth.expected_answer_points
    if not points or not sample.rag_answer:
        return 0.0

    provider = settings.eval_llm_provider
    logger.info("[%s] Evaluating %d answer points with %s", sample.question_id, len(points), provider)
    results: list[bool] = []
    for i, point in enumerate(points, 1):
        result = await _judge_point_coverage(sample.question, sample.rag_answer, point)
        results.append(result)

    covered = sum(results)
    score = covered / len(points)
    logger.info("[%s] Point coverage: %d/%d = %.2f", sample.question_id, covered, len(points), score)
    return score


def compute_llm_judge_metrics(samples: list[EvalSample]) -> dict[str, list[MetricResult]]:
    """
    Batch entry point — compute Answer Point Coverage for all samples.

    Returns: { question_id: [MetricResult, ...] }
    """
    provider = settings.eval_llm_provider
    console.print(f"[bold]Running Answer Point Coverage evaluation with {provider}...[/bold]")

    async def _run_all() -> dict[str, float]:
        scores: dict[str, float] = {}
        for sample in samples:
            score = await evaluate_point_coverage_async(sample)
            scores[sample.question_id] = score
            await asyncio.sleep(0.5)
        return scores

    scores = asyncio.run(_run_all())

    results: dict[str, list[MetricResult]] = {}
    for sample in samples:
        coverage = scores.get(sample.question_id, 0.0)
        results[sample.question_id] = [
            MetricResult(
                name="answer_point_coverage",
                value=round(coverage, 4),
                category="llm_judge",
            )
        ]

    console.print(f"[green]LLM Judge evaluation complete for {len(results)} samples.[/green]")
    return results

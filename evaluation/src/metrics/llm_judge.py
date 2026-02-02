"""
Custom LLM-as-Judge evaluation using Anthropic SDK directly.

Metrics:
  - Answer Point Coverage: checks if each expected_answer_point is covered by the RAG answer

Provides both:
  - evaluate_point_coverage_async() — for inline per-question use during collection
  - compute_llm_judge_metrics()     — for batch use (wraps the async version)
"""

from __future__ import annotations

import asyncio
import logging
import time

import anthropic
from rich.console import Console

from ..config import settings
from ..models import EvalSample, MetricResult

console = Console()
logger = logging.getLogger(__name__)


async def _judge_point_coverage(
    client: anthropic.AsyncAnthropic,
    question: str,
    rag_answer: str,
    point: str,
) -> bool:
    """Ask Claude to judge if a single answer point is covered."""
    prompt = f"""你是一個嚴格的評估員。請判斷以下 RAG 系統的回答是否涵蓋了指定的答案要點。

問題：{question}

RAG 回答：{rag_answer}

答案要點：{point}

請只回答 "YES" 或 "NO"。
- YES：回答中明確包含或實質涵蓋了這個要點的核心意思
- NO：回答中未包含這個要點，或只是模糊提及"""

    try:
        logger.info("[Claude API] POST messages  model=%s  point=%r",
                     settings.claude_model, point[:40])
        t0 = time.perf_counter()
        raw_resp = await client.messages.with_raw_response.create(
            model=settings.claude_model,
            max_tokens=10,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.perf_counter() - t0
        resp = raw_resp.parse()
        answer = resp.content[0].text.strip().upper()
        covered = answer.startswith("YES")
        logger.info("[Claude API] %d  %.2fs  answer=%s  usage: in=%d out=%d",
                     raw_resp.status_code, elapsed, answer,
                     resp.usage.input_tokens, resp.usage.output_tokens)
        return covered
    except anthropic.APIStatusError as e:
        logger.error("[Claude API] %d  %s", e.status_code, e.message)
        return False
    except Exception as e:
        logger.error("[Claude API] Request failed: %s", e)
        return False


async def evaluate_point_coverage_async(sample: EvalSample) -> float:
    """
    Compute the fraction of expected answer points covered by the RAG answer.

    This is the per-question async entry point, called inline during collection.
    """
    points = sample.ground_truth.expected_answer_points
    if not points or not sample.rag_answer:
        return 0.0

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    logger.info("[%s] Evaluating %d answer points with Claude", sample.question_id, len(points))
    results: list[bool] = []
    for i, point in enumerate(points, 1):
        result = await _judge_point_coverage(client, sample.question, sample.rag_answer, point)
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
    console.print("[bold]Running Answer Point Coverage evaluation with Claude...[/bold]")

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

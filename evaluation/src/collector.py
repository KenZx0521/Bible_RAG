"""
Collector: send questions to RAG API, fetch contexts, evaluate per-question with Claude.

Each execution starts fresh (no resume). After each RAG response, immediately calls
Claude API for Answer Point Coverage so both API calls are logged together.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
from rich.console import Console

from .config import settings
from .models import EvalSample, GroundTruthItem, MetricResult, SourceInfo
from .rag_client import query_rag, parse_sources
from .content_fetcher import get_pool, fetch_contexts
from .metrics.llm_judge import evaluate_point_coverage_async

console = Console()
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
RAW_RESPONSES_PATH = RESULTS_DIR / "raw_responses.json"


def _clear_previous_results() -> None:
    """Delete previous run's checkpoint so we always start fresh."""
    if RAW_RESPONSES_PATH.exists():
        RAW_RESPONSES_PATH.unlink()
        logger.info("Cleared previous raw_responses.json")


def _save_responses(collected: list[dict]) -> None:
    """Persist collected responses."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_RESPONSES_PATH, "w", encoding="utf-8") as f:
        json.dump(collected, f, ensure_ascii=False, indent=2)


async def collect_responses(
    questions: list[GroundTruthItem],
) -> tuple[list[EvalSample], dict[str, list[MetricResult]]]:
    """
    For each ground truth question:
      1. Call the RAG API
      2. Fetch context content from PostgreSQL
      3. Immediately call Claude API for Answer Point Coverage
      4. Build an EvalSample

    Always starts fresh. Saves raw_responses.json after each question.

    Returns: (samples, inline_metrics)
      - inline_metrics: { question_id: [MetricResult] } for point coverage
    """
    _clear_previous_results()

    pool = await get_pool()
    samples: list[EvalSample] = []
    collected_raw: list[dict] = []
    inline_metrics: dict[str, list[MetricResult]] = {}
    total = len(questions)

    logger.info("Starting fresh collection for %d questions", total)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for idx, gt in enumerate(questions, 1):
            console.rule(f"[bold cyan][{idx}/{total}] {gt.question_id}")
            console.print(f"  [dim]Q:[/dim] {gt.question[:80]}")

            try:
                # --- Step 1: Call RAG API ---
                resp = await query_rag(gt.question, client=client)
                answer = resp.get("answer", "")
                sources = parse_sources(resp.get("sources", []))

                # --- Step 2: Fetch context from PostgreSQL ---
                source_ids = [s.id for s in sources]
                contexts = await fetch_contexts(pool, source_ids)
                logger.info("[%s] RAG done: %d sources, %d contexts, answer_len=%d",
                            gt.question_id, len(sources), len(contexts), len(answer))

                sample = EvalSample(
                    question_id=gt.question_id,
                    question=gt.question,
                    question_type=gt.question_type,
                    rag_answer=answer,
                    contexts=contexts,
                    sources=sources,
                    ground_truth=gt,
                    reference_answer=gt.reference_answer,
                )
                samples.append(sample)

                # --- Step 3: Immediately evaluate with Claude API ---
                coverage = await evaluate_point_coverage_async(sample)
                inline_metrics[gt.question_id] = [
                    MetricResult(
                        name="answer_point_coverage",
                        value=round(coverage, 4),
                        category="llm_judge",
                    )
                ]
                console.print(
                    f"  [green]=> Point coverage: {coverage:.2%}[/green]"
                )

                # Save raw response
                collected_raw.append({
                    "question_id": gt.question_id,
                    "question": gt.question,
                    "rag_answer": answer,
                    "contexts": contexts,
                    "sources": [s.model_dump() for s in sources],
                })
                _save_responses(collected_raw)

            except Exception as e:
                logger.error("[%s] Failed: %s", gt.question_id, e)
                console.print(f"  [red]Error: {e}[/red]")
                samples.append(EvalSample(
                    question_id=gt.question_id,
                    question=gt.question,
                    question_type=gt.question_type,
                    ground_truth=gt,
                    reference_answer=gt.reference_answer,
                ))

            # Rate-limit between questions
            await asyncio.sleep(settings.request_delay)

    await pool.close()
    console.print(f"\n[bold green]Collected and evaluated {len(samples)}/{total} responses.[/bold green]")
    return samples, inline_metrics

"""
Collector: send questions to RAG API and fetch contexts.

Each execution starts fresh (no resume). Saves raw_responses.json after each
question for crash recovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
from rich.console import Console

from .config import settings
from .context_blocks import (
    CONTEXT_SOURCE_BACKEND,
    CONTEXT_SOURCE_REBUILT,
    contexts_from_raw_item,
)
from .models import EvalSample, GroundTruthItem, MetricResult, SourceInfo
from .provenance import Provenance, write_run_meta
from .rag_client import query_rag, parse_sources
from .content_fetcher import get_pool, fetch_context_blocks

console = Console()
logger = logging.getLogger(__name__)


def _raw_responses_path() -> Path:
    """Resolve the raw_responses.json path based on current graph mode."""
    return settings.results_dir / "raw_responses.json"


def _clear_previous_results() -> None:
    """Delete previous run's checkpoint so we always start fresh.

    Refuses to delete an archive written before per-strategy graph gating
    (records carry no `graph_strategies`): those are the Round 3 run-of-record
    files, and `--graph` no longer means every graph strategy, so a rerun would
    silently replace them with a different condition. Move or commit it first.
    """
    path = _raw_responses_path()
    if not path.exists():
        return
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"{path} is unreadable ({e}); move it aside before a new run") from e
    if records and not any("graph_strategies" in r for r in records):
        raise RuntimeError(
            f"{path} predates graph_strategies (pre-2026-10 archive, every graph "
            "strategy on); move or commit it before collecting into this directory"
        )
    path.unlink()
    logger.info("Cleared previous raw_responses.json at %s", path)


def _save_responses(collected: list[dict]) -> None:
    """Persist collected responses."""
    results_dir = settings.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(_raw_responses_path(), "w", encoding="utf-8") as f:
        json.dump(collected, f, ensure_ascii=False, indent=2)


async def collect_responses(
    questions: list[GroundTruthItem],
    use_graph: bool | None = None,
    semantic_only: bool = False,
    graph_strategies: list[str] | None = None,
    provenance: Provenance | None = None,
) -> tuple[list[EvalSample], dict[str, list[MetricResult]]]:
    """
    For each ground truth question:
      1. Call the RAG API
      2. Fetch context content from PostgreSQL
      3. Build an EvalSample

    Always starts fresh. Saves raw_responses.json after each question.

    Args:
        use_graph: Per-request override for backend graph retrieval.
            None = use backend RAG_USE_GRAPH env default.
            True/False = force graph on/off for every request in this run.
        semantic_only: When True, bypass backend routing / SQL / graph /
            cross-ref and run pure semantic retrieval only.
        graph_strategies: Per-request override for which graph strategies run
            (["all"] = every one, the pre-2026-10 behaviour). None = backend
            RAG_GRAPH_STRATEGIES default.
        provenance: The backend's build and encoder (from /health), written
            to run_meta.json beside the checkpoint for --eval-only reruns.

    Returns: (samples, inline_metrics)
      - inline_metrics: kept as empty dict for run_evaluation() signature compat.
    """
    _clear_previous_results()
    if provenance is not None:
        write_run_meta(settings.results_dir, provenance)

    pool = await get_pool()
    samples: list[EvalSample] = []
    collected_raw: list[dict] = []
    inline_metrics: dict[str, list[MetricResult]] = {}
    total = len(questions)

    logger.info("Starting fresh collection for %d questions "
                "(use_graph=%s, semantic_only=%s, graph_strategies=%s)",
                total, use_graph, semantic_only, graph_strategies)

    async with httpx.AsyncClient(timeout=120.0) as client:
        for idx, gt in enumerate(questions, 1):
            console.rule(f"[bold cyan][{idx}/{total}] {gt.question_id}")
            console.print(f"  [dim]Q:[/dim] {gt.question[:80]}")

            try:
                # --- Step 1: Call RAG API (retry up to 3 times) ---
                max_retries = 3
                resp = None
                for attempt in range(1, max_retries + 1):
                    try:
                        resp = await query_rag(
                            gt.question, client=client,
                            use_graph=use_graph, semantic_only=semantic_only,
                            graph_strategies=graph_strategies,
                        )
                        break
                    except Exception as e:
                        logger.warning("[%s] RAG API attempt %d/%d failed: %s",
                                       gt.question_id, attempt, max_retries, e)
                        console.print(f"  [yellow]RAG API attempt {attempt}/{max_retries} failed: {e}[/yellow]")
                        if attempt < max_retries:
                            await asyncio.sleep(2 * attempt)
                        else:
                            raise

                answer = resp.get("answer", "")
                sources = parse_sources(resp.get("sources", []))

                # Extract routing info from retrieval_stats
                stats = resp.get("retrieval_stats", {})
                route_used = stats.get("route_used", "")
                strategies_used = stats.get("strategies_used", [])
                strategy_errors = stats.get("strategy_errors", {}) or {}

                # --- Step 2: Judge context = the generator's context blocks ---
                # Preferred: the backend returned each block (include_context).
                # Fallback (older backend): rebuild header + text from PostgreSQL.
                contexts = contexts_from_raw_item({"sources": [s.model_dump() for s in sources]})
                context_source = CONTEXT_SOURCE_BACKEND
                if contexts is None:
                    if sources:
                        logger.warning("[%s] backend returned no context blocks; rebuilding from DB",
                                       gt.question_id)
                    contexts = await fetch_context_blocks(pool, sources)
                    context_source = CONTEXT_SOURCE_REBUILT
                logger.info("[%s] RAG done: %d sources, %d contexts (%s), answer_len=%d",
                            gt.question_id, len(sources), len(contexts), context_source, len(answer))

                sample = EvalSample(
                    question_id=gt.question_id,
                    question=gt.question,
                    question_type=gt.question_type,
                    rag_answer=answer,
                    contexts=contexts,
                    sources=sources,
                    context_source=context_source,
                    ground_truth=gt,
                    reference_answer=gt.reference_answer,
                    route_used=route_used,
                    strategies_used=strategies_used,
                    strategy_errors=strategy_errors,
                )
                samples.append(sample)

                if route_used:
                    strats = ", ".join(strategies_used) if strategies_used else "none"
                    console.print(
                        f"  [dim]Route: {route_used} | Strategies: {strats}[/dim]"
                    )

                # Save raw response. `contexts` holds the generator blocks once;
                # `context_source` tells readers they carry headers.
                collected_raw.append({
                    "question_id": gt.question_id,
                    "question": gt.question,
                    "rag_answer": answer,
                    "contexts": contexts,
                    "context_source": context_source,
                    "sources": [s.model_dump(exclude={"context"}) for s in sources],
                    "route_used": route_used,
                    "strategies_used": strategies_used,
                    "strategy_errors": strategy_errors,
                    "use_graph": stats.get("use_graph", True),
                    "graph_strategies": stats.get("graph_strategies"),
                })
                _save_responses(collected_raw)

            except Exception as e:
                logger.error("[%s] Failed: %s", gt.question_id, e)
                console.print(f"  [red]Error: {e}[/red]")
                # Recorded as an infrastructure failure (validity.is_infra_failure)
                # here and in raw_responses.json, so --eval-only reruns also
                # leave it out of the averages instead of scoring it 0.
                errors = {"request": repr(e)[:200]}
                samples.append(EvalSample(
                    question_id=gt.question_id,
                    question=gt.question,
                    question_type=gt.question_type,
                    ground_truth=gt,
                    reference_answer=gt.reference_answer,
                    strategy_errors=errors,
                ))
                collected_raw.append({
                    "question_id": gt.question_id,
                    "question": gt.question,
                    "rag_answer": "",
                    "contexts": [],
                    "context_source": "",
                    "sources": [],
                    "route_used": "",
                    "strategies_used": [],
                    "strategy_errors": errors,
                    "use_graph": use_graph,
                    "graph_strategies": graph_strategies,
                })
                _save_responses(collected_raw)

            # Rate-limit between questions
            await asyncio.sleep(settings.request_delay)

    await pool.close()
    console.print(f"\n[bold green]Collected and evaluated {len(samples)}/{total} responses.[/bold green]")
    return samples, inline_metrics

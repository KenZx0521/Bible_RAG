"""
Collector: send questions to RAG API and fetch contexts.

Each execution starts fresh (no resume). Saves raw_responses.json after each
question for crash recovery.

Each raw record also keeps (2026-10-28) what the backend said about the question
(intent, fusion_alpha, total_candidates, reranked_top_k, event_registry_events), the
arm it was asked under (``mode``, from the CLI flags), ``collected_at``, ``latency_ms``
and ``request_attempts``; ``use_graph`` is what the backend reported (null when it did
not say). run_meta.json v2 (src/run_record.py) is written when collection starts and
completed when it ends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from .config import settings
from .context_blocks import (
    CONTEXT_SOURCE_BACKEND,
    CONTEXT_SOURCE_REBUILT,
    aux_context_block,
    contexts_from_raw_item,
)
from .models import EvalSample, GroundTruthItem, MetricResult
from .provenance import Provenance, write_run_meta
from .rag_client import NO_KEEPALIVE, parse_sources, query_rag, response_audit_fields
from .content_fetcher import get_pool, fetch_context_blocks
from .run_record import (CollectionInputs, collection_mode, finish_record, now_iso,
                         start_record)

console = Console()
logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


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


async def _query_with_retries(gt: GroundTruthItem, client: httpx.AsyncClient,
                             request: dict[str, Any]) -> tuple[dict, int]:
    """The backend's answer and the attempt that got it; after the last attempt its error is raised."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await query_rag(gt.question, client=client, **request), attempt
        except Exception as e:
            logger.warning("[%s] RAG API attempt %d/%d failed: %s",
                           gt.question_id, attempt, _MAX_RETRIES, e)
            console.print(f"  [yellow]RAG API attempt {attempt}/{_MAX_RETRIES} failed: {e}[/yellow]")
            if attempt == _MAX_RETRIES:
                raise
            await asyncio.sleep(2 * attempt)
    raise AssertionError("unreachable")


def _timing(started: float, attempts: int) -> dict[str, Any]:
    """When the record was made, the question's request time (retries included) and attempts."""
    return {"collected_at": now_iso(),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "request_attempts": attempts}


async def _judge_contexts(gt: GroundTruthItem, sources: list, pool) -> tuple[list[str], str]:
    """Judge context = the generator's context blocks.

    Preferred: the backend returned each block (include_context).
    Fallback (older backend): rebuild header + text from PostgreSQL.
    """
    contexts = contexts_from_raw_item({"sources": [s.model_dump() for s in sources]})
    if contexts is not None:
        return contexts, CONTEXT_SOURCE_BACKEND
    if sources:
        logger.warning("[%s] backend returned no context blocks; rebuilding from DB", gt.question_id)
    return await fetch_context_blocks(pool, sources), CONTEXT_SOURCE_REBUILT


async def _answered(gt: GroundTruthItem, resp: dict, pool, mode: str,
                    timing: dict[str, Any]) -> tuple[EvalSample, dict]:
    """The sample and raw record of an answered question."""
    answer = resp.get("answer", "")
    sources = parse_sources(resp.get("sources", []))
    stats = resp.get("retrieval_stats", {})
    route_used = stats.get("route_used", "")
    strategies_used = stats.get("strategies_used", [])
    strategy_errors = stats.get("strategy_errors", {}) or {}
    contexts, context_source = await _judge_contexts(gt, sources, pool)
    aux_card = resp.get("aux_card")
    contexts = [*contexts, *aux_context_block(aux_card)]
    logger.info("[%s] RAG done: %d sources, %d contexts (%s), answer_len=%d",
                gt.question_id, len(sources), len(contexts), context_source, len(answer))
    audit = response_audit_fields(resp)
    sample = EvalSample(
        question_id=gt.question_id, question=gt.question, question_type=gt.question_type,
        rag_answer=answer, contexts=contexts, sources=sources, context_source=context_source,
        ground_truth=gt, reference_answer=gt.reference_answer, route_used=route_used,
        strategies_used=strategies_used, strategy_errors=strategy_errors,
        intent=audit["intent"] if isinstance(audit["intent"], dict) else None, mode=mode,
    )
    if route_used:
        strats = ", ".join(strategies_used) if strategies_used else "none"
        console.print(f"  [dim]Route: {route_used} | Strategies: {strats}[/dim]")
    # `contexts` holds the generator blocks once; `context_source` tells readers they carry headers.
    raw = {
        "question_id": gt.question_id, "question": gt.question, "rag_answer": answer,
        "contexts": contexts, "context_source": context_source,
        "sources": [s.model_dump(exclude={"context"}) for s in sources],
        "route_used": route_used, "strategies_used": strategies_used,
        "strategy_errors": strategy_errors,
        # As reported (null if absent). Not an arm label: a semantic_only request carries
        # no use_graph, so the backend reports RAG_USE_GRAPH (true). `mode` names the arm.
        "use_graph": stats.get("use_graph"),
        "graph_strategies": stats.get("graph_strategies"), "aux_card": aux_card,
        "mode": mode, **audit, **timing,
    }
    return sample, raw


def _failed(gt: GroundTruthItem, error: Exception, mode: str,
            graph_strategies: list[str] | None, timing: dict[str, Any]) -> tuple[EvalSample, dict]:
    """The sample and raw record of a question whose request failed.

    Recorded as an infrastructure failure (validity.is_infra_failure) here and in
    raw_responses.json, so --eval-only reruns also leave it out of the averages
    instead of scoring it 0.
    """
    errors = {"request": repr(error)[:200]}
    sample = EvalSample(question_id=gt.question_id, question=gt.question,
                        question_type=gt.question_type, ground_truth=gt,
                        reference_answer=gt.reference_answer, strategy_errors=errors, mode=mode)
    raw = {
        "question_id": gt.question_id, "question": gt.question, "rag_answer": "",
        "contexts": [], "context_source": "", "sources": [], "route_used": "",
        "strategies_used": [], "strategy_errors": errors,
        "use_graph": None, "graph_strategies": graph_strategies,
        "mode": mode, **response_audit_fields({}), **timing,
    }
    return sample, raw


async def _collect_one(gt: GroundTruthItem, client: httpx.AsyncClient, pool,
                       request: dict[str, Any], mode: str) -> tuple[EvalSample, dict]:
    started, attempts = time.perf_counter(), None
    try:
        resp, attempts = await _query_with_retries(gt, client, request)
        return await _answered(gt, resp, pool, mode, _timing(started, attempts))
    except Exception as e:
        logger.error("[%s] Failed: %s", gt.question_id, e)
        console.print(f"  [red]Error: {e}[/red]")
        return _failed(gt, e, mode, request["graph_strategies"],
                       _timing(started, attempts or _MAX_RETRIES))


def _start_run_meta(provenance: Provenance | None, mode: str, graph_strategies: list[str] | None,
                    n_questions: int, inputs: CollectionInputs | None) -> dict | None:
    """run_meta.json v2 on disk before the first question (finished_at null until the end)."""
    if provenance is None:
        return None
    record = start_record(mode=mode, graph_strategies=graph_strategies, n_questions=n_questions,
                          inputs=inputs or CollectionInputs())
    write_run_meta(settings.results_dir, provenance, record)
    return record


def _finish_run_meta(provenance: Provenance | None, record: dict | None,
                     collected: list[dict]) -> None:
    if provenance is None or record is None:
        return
    failures = sum(1 for r in collected if "request" in (r.get("strategy_errors") or {}))
    write_run_meta(settings.results_dir, provenance,
                   finish_record(record, n_collected=len(collected), n_request_failures=failures))


async def collect_responses(
    questions: list[GroundTruthItem],
    use_graph: bool | None = None,
    semantic_only: bool = False,
    graph_strategies: list[str] | None = None,
    provenance: Provenance | None = None,
    inputs: CollectionInputs | None = None,
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
        semantic_only: When True, bypass backend routing / SQL / the
            event_registry lane and run pure semantic retrieval only.
        graph_strategies: Per-request override for which graph strategies run:
            ["event_registry"] (the only one the R1/R2 backend has) or [].
            None = backend RAG_GRAPH_STRATEGIES default.
        provenance: The backend's build and encoder (from /health), written
            to run_meta.json beside the checkpoint for --eval-only reruns.
        inputs: The CLI's argv, ids file and /health body for run_meta.json v2.

    Returns: (samples, inline_metrics)
      - inline_metrics: kept as empty dict for run_evaluation() signature compat.
    """
    _clear_previous_results()
    mode = collection_mode(use_graph, semantic_only)
    record = _start_run_meta(provenance, mode, graph_strategies, len(questions), inputs)

    pool = await get_pool()
    samples: list[EvalSample] = []
    collected_raw: list[dict] = []
    total = len(questions)
    request = {"use_graph": use_graph, "semantic_only": semantic_only,
               "graph_strategies": graph_strategies}

    logger.info("Starting fresh collection for %d questions "
                "(use_graph=%s, semantic_only=%s, graph_strategies=%s)",
                total, use_graph, semantic_only, graph_strategies)

    async with httpx.AsyncClient(timeout=120.0, limits=NO_KEEPALIVE) as client:
        for idx, gt in enumerate(questions, 1):
            console.rule(f"[bold cyan][{idx}/{total}] {gt.question_id}")
            console.print(f"  [dim]Q:[/dim] {gt.question[:80]}")
            sample, raw = await _collect_one(gt, client, pool, request, mode)
            samples.append(sample)
            collected_raw.append(raw)
            _save_responses(collected_raw)
            # Rate-limit between questions
            await asyncio.sleep(settings.request_delay)

    await pool.close()
    _finish_run_meta(provenance, record, collected_raw)
    console.print(f"\n[bold green]Collected and evaluated {len(samples)}/{total} responses.[/bold green]")
    return samples, {}

"""
Async HTTP client for the Bible RAG API.
"""

from __future__ import annotations

import logging
import time

import httpx

from .config import settings
from .models import SourceInfo

logger = logging.getLogger(__name__)

# uvicorn closes an idle connection after 5 s and httpx keeps one for 5 s, so a
# reused connection can be closed under a request (httpx.ReadError mid-run, R1
# retrieval arm 2026-10-08). One connection per request removes the race.
NO_KEEPALIVE = httpx.Limits(max_keepalive_connections=0)


async def query_rag(
    question: str,
    client: httpx.AsyncClient | None = None,
    top_k: int | None = None,
    use_graph: bool | None = None,
    semantic_only: bool = False,
    include_context: bool = True,
    graph_strategies: list[str] | None = None,
) -> dict:
    """
    Send a question to POST /api/v1/query and return the parsed response.

    Args:
        use_graph: Per-request override for backend RAG_USE_GRAPH. None = use
            backend default; True/False explicitly forces graph on/off.
        semantic_only: When True, bypass backend routing / SQL / the
            event_registry lane and run pure semantic retrieval only.
        include_context: Ask the backend for the exact context block it fed
            the generator per source (header + text), so the judge sees the
            same text. Older backends ignore the field.
        graph_strategies: Per-request override for which graph strategies run:
            ["event_registry"] (the only one the R1/R2 backend has) or [] for
            none. None = backend default.

    Returns dict with keys: answer, sources, intent, retrieval_stats
    """
    k = top_k or settings.top_k
    payload: dict = {
        "question": question,
        "top_k": k,
        "include_sources": True,
        "include_context": include_context,
    }
    if use_graph is not None:
        payload["use_graph"] = use_graph
    if semantic_only:
        payload["semantic_only"] = True
    if graph_strategies is not None:
        payload["graph_strategies"] = graph_strategies
    url = f"{settings.backend_url}/api/v1/query"

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0, limits=NO_KEEPALIVE)

    try:
        logger.info("[RAG API] POST %s  question=%r  top_k=%d", url, question[:60], k)
        t0 = time.perf_counter()
        resp = await client.post(url, json=payload)
        elapsed = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        n_sources = len(data.get("sources", []))
        answer_preview = data.get("answer", "")[:80]
        logger.info(
            "[RAG API] %d  %.2fs  sources=%d  answer=%r",
            resp.status_code, elapsed, n_sources, answer_preview,
        )
        return data
    except httpx.HTTPStatusError as e:
        logger.error("[RAG API] %d  %s", e.response.status_code, e.response.text[:200])
        raise
    except Exception as e:
        logger.error("[RAG API] Request failed: %s", e)
        raise
    finally:
        if own_client:
            await client.aclose()


def parse_sources(raw_sources: list[dict]) -> list[SourceInfo]:
    """Convert raw API source dicts to SourceInfo models."""
    results = []
    for s in raw_sources:
        results.append(SourceInfo(
            id=s.get("id", ""),
            book=s.get("book", ""),
            chapter=s.get("chapter"),
            title=s.get("title", ""),
            verse_range=s.get("verse_range", ""),
            score=s.get("score"),
            strategy=s.get("strategy"),
            context=s.get("context"),
            kind=s.get("kind"),
            start_key=s.get("start_key"),
            end_key=s.get("end_key"),
        ))
    return results

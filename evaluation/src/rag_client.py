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


async def query_rag(
    question: str,
    client: httpx.AsyncClient | None = None,
    top_k: int | None = None,
    use_graph: bool | None = None,
    semantic_only: bool = False,
) -> dict:
    """
    Send a question to POST /api/v1/query and return the parsed response.

    Args:
        use_graph: Per-request override for backend RAG_USE_GRAPH. None = use
            backend default; True/False explicitly forces graph on/off.
        semantic_only: When True, bypass backend routing / SQL / graph /
            cross-ref and run pure semantic retrieval only.

    Returns dict with keys: answer, sources, intent, retrieval_stats
    """
    k = top_k or settings.top_k
    payload: dict = {
        "question": question,
        "top_k": k,
        "include_sources": True,
    }
    if use_graph is not None:
        payload["use_graph"] = use_graph
    if semantic_only:
        payload["semantic_only"] = True
    url = f"{settings.backend_url}/api/v1/query"

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=60.0)

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
        ))
    return results

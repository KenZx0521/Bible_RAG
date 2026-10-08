"""The route handlers R1–R6 and fallback: each gathers a candidate pool.

R1 exact verses (falls back to R2 when empty); R2 chapter passages + dense;
R5 dense + chapter passages (multi-book or cross-reference questions); R3/R4/R6
and fallback dense alone. Every route but R1/R2 adds book anchors when the
question names books, and R3–R6 a SQL supplement from the pool's first chapters.
Each returns (pool, strategies used, strategy errors); a failing strategy is
recorded in the errors and the route goes on without it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import settings
from database import postgres
from utils.retrieval import candidates as cands
from utils.retrieval.dense import ROUTE_ARM, SEMANTIC_ARM, retrieve_dense
from utils.retrieval.pins import BOOK_ANCHOR
from utils.retrieval.verse_retriever import retrieve_by_verse_refs
from utils.signal_detector import QuerySignals
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)

Pool = tuple[list[dict], list[str], dict[str, str]]


@dataclass(frozen=True)
class RouteInput:
    query: str
    verse_refs: list[VerseRef]
    signals: QuerySignals


def _error(errors: dict[str, str], route: str, label: str, exc: Exception) -> None:
    logger.warning("%s %s failed: %s", route, label, exc)
    errors[label] = repr(exc)[:200]


async def _dense(inp: RouteInput, route: str, errors: dict[str, str],
                 label: str = "semantic") -> list[dict] | None:
    """The route's dense arm, or None (and an error) when it failed."""
    try:
        return await retrieve_dense(inp.query, ROUTE_ARM)
    except Exception as exc:  # noqa: BLE001 — recorded in strategy_errors
        _error(errors, route, label, exc)
        return None


async def _chapters(inp: RouteInput, route: str, weight: float,
                    errors: dict[str, str]) -> list[dict] | None:
    """The passages and verses the references name, as sql_chapter; None when it failed."""
    try:
        found = cands.apply_weights(await retrieve_by_verse_refs(inp.verse_refs), weight)
    except Exception as exc:  # noqa: BLE001
        _error(errors, route, "sql_chapter", exc)
        return None
    for c in found:
        c["source_strategy"] = "sql_chapter"
    return found


async def _sql_supplement(pairs: list[tuple[str, int]], existing: set[str],
                          limit: int) -> list[dict]:
    """Passages of the pool's first three chapters that the pool lacks."""
    out: list[dict] = []
    for book_id, chapter in pairs[:3]:
        for p in await postgres.chapter_passages(book_id, chapter):
            if p["id"] not in existing and len(out) < limit:
                existing.add(p["id"])
                out.append({**p, "source_strategy": "sql_supplement", "weight": 0.5})
    return out


async def _supplement(pool: list[dict], route: str, weight: float, strategies: list[str],
                      errors: dict[str, str]) -> list[dict]:
    pairs = cands.book_chapters(pool)
    if not pairs:
        return pool
    try:
        found = cands.apply_weights(
            await _sql_supplement(pairs, {c["id"] for c in pool}, limit=3), weight)
    except Exception as exc:  # noqa: BLE001
        _error(errors, route, "sql_supplement", exc)
        return pool
    if found:
        strategies.append("sql_supplement")
    return pool + found


async def _book_anchor_hits(inp: RouteInput, name: str, book_id: str, k: int,
                            errors: dict[str, str], route: str) -> list[dict]:
    try:
        return await retrieve_dense(inp.query, SEMANTIC_ARM, top_k=k, book_ids=[book_id])
    except Exception as exc:  # noqa: BLE001
        _error(errors, route, f"{BOOK_ANCHOR}:{name}", exc)
        return []


async def _book_anchor(inp: RouteInput, route: str, pool: list[dict], strategies: list[str],
                       errors: dict[str, str], weight: float = 0.9, top_k: int = 10
                       ) -> list[dict]:
    """Dense hits restricted to each book the question names, one search per book.

    A single OR-filtered search let the book whose wording sits closest to the
    query eat the whole quota. Hits already in ``pool`` get book_anchor in their
    found_by instead. Multi-book: only each book's best new hit is raised to
    ``weight`` (upgrading every one flooded fusion with same-book decoys).
    """
    books = list(zip(inp.signals.detected_book_names, inp.signals.detected_book_ids))
    if not books or not inp.query:
        return []
    by_id = {c["id"]: c for c in pool}
    multi, seen, new = len(books) > 1, set(by_id), []
    for name, book_id in books:
        added = 0
        k = max(3, top_k // len(books)) if multi else top_k
        for c in await _book_anchor_hits(inp, name, book_id, k, errors, route):
            if c["id"] in seen:
                if c["id"] in by_id:
                    cands.note_found_by(by_id[c["id"]], BOOK_ANCHOR)
                continue
            seen.add(c["id"])
            c["source_strategy"] = BOOK_ANCHOR
            if (not multi or added == 0) and c.get("weight", 0) < weight:
                c["weight"] = weight
            new.append(c)
            added += 1
        if not added:
            logger.info("%s book_anchor: %s contributed 0 new candidates", route, name)
    if new:
        strategies.append(BOOK_ANCHOR)
    return new


async def route_r1(inp: RouteInput) -> Pool:
    """R1: exact verse references → SQL lookup (no rerank); R2 when it finds nothing."""
    errors: dict[str, str] = {}
    try:
        found = await retrieve_by_verse_refs(inp.verse_refs)
    except Exception as exc:  # noqa: BLE001
        _error(errors, "R1", "verse_direct", exc)
        found = []
    if found:
        return found, ["verse_direct"], errors
    logger.info("R1 empty, falling back to R2")
    pool, strategies, r2_errors = await route_r2(inp)
    return pool, strategies, {**errors, **r2_errors}


async def route_r2(inp: RouteInput) -> Pool:
    """R2: chapter passages (0.9) + dense (0.6)."""
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights["R2"]
    pool: list[dict] = []
    if inp.verse_refs:
        chapter = await _chapters(inp, "R2", weights["sql"], errors)
        if chapter is not None:
            pool += chapter
            strategies.append("sql_chapter")
    dense = await _dense(inp, "R2", errors)
    if dense is not None:
        pool += cands.apply_weights(dense, weights["semantic"])
        strategies.append("semantic")
    return cands.dedup(pool), strategies, errors


async def _dense_route(inp: RouteInput, route: str) -> Pool:
    """R3, R4, R6: dense, book anchors, SQL supplement."""
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights[route]
    dense = await _dense(inp, route, errors) or []
    if dense:
        strategies.append("semantic")
    pool = cands.dedup(cands.apply_weights(dense, weights["semantic"]))
    pool += await _book_anchor(inp, route, pool, strategies, errors)
    return await _supplement(pool, route, weights["sql"], strategies, errors), strategies, errors


async def route_r3(inp: RouteInput) -> Pool:
    """R3: two or more persons (no person graph in R1: dense + anchors + supplement)."""
    return await _dense_route(inp, "R3")


async def route_r4(inp: RouteInput) -> Pool:
    """R4: event keyword (the event registry lane appends after ranking)."""
    return await _dense_route(inp, "R4")


async def route_r6(inp: RouteInput) -> Pool:
    """R6: place name (no place graph in R1)."""
    return await _dense_route(inp, "R6")


async def route_r5(inp: RouteInput) -> Pool:
    """R5: multi-book or cross-reference → dense (0.65) + chapter passages (0.85) + anchors.

    Chapter-only references are pulled as sql_chapter after dense, so dedup's
    strict-greater weight keeps the sql_chapter copy and chapter-pin can see it.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights["R5"]
    pool: list[dict] = []
    dense = await _dense(inp, "R5", errors)
    if dense is not None:
        pool += cands.apply_weights(dense, weights["semantic"])
        strategies.append("semantic")
    if any(r.verse_start is None for r in inp.verse_refs):
        chapter = await _chapters(inp, "R5", weights["sql_chapter"], errors) or []
        pool += chapter
        if chapter:
            strategies.append("sql_chapter")
    pool = cands.dedup(pool)
    pool += await _book_anchor(inp, "R5", pool, strategies, errors)
    return await _supplement(pool, "R5", weights["sql"], strategies, errors), strategies, errors


async def route_fallback(inp: RouteInput) -> Pool:
    """Fallback: dense (labelled hybrid, as prod reported it) + book anchors."""
    label = "hybrid"
    strategies: list[str] = []
    errors: dict[str, str] = {}
    dense = await _dense(inp, "fallback", errors, label=label)
    if dense is not None:
        strategies.append(label)
    pool = cands.dedup(dense or [])
    pool += await _book_anchor(inp, "fallback", pool, strategies, errors)
    return pool, strategies, errors


ROUTES = {"R1": route_r1, "R2": route_r2, "R3": route_r3, "R4": route_r4, "R5": route_r5,
          "R6": route_r6, "fallback": route_fallback}

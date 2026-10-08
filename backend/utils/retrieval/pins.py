"""Final-ranking steps after the reranker: rank fusion and the two pins.

- ``fuse_and_rank``: fused = (1 - alpha) * rerank_score + alpha * weight.
- ``cap_book_anchor_entries``: multi-book questions keep one book_anchor per book
  in the fused order; the rest sink to the tail.
- ``pin_chapter_candidates``: a chapter the user named (A書N章; a range by its
  first chapter) keeps at least ``min_pins`` of its passages in the top-k.
- ``pin_book_anchor_candidates``: a book the user named is represented
  (unconditionally for one book; only absent books for several).

Every candidate here carries ``book_id``, ``chapter_num`` and ``start_key``; ids are
never parsed.
"""

from __future__ import annotations

import logging

from database.content import key_order
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)

BOOK_ANCHOR = "book_anchor"
PIN_WEIGHT_FLOOR = 0.85   # sql_chapter and book anchors; dense noise stays below


def fuse_and_rank(candidates: list[dict], top_k: int, alpha: float) -> list[dict]:
    """Blend the cross-encoder score with the retrieval-strategy prior (both in [0, 1])."""
    a = min(max(alpha, 0.0), 1.0)
    for c in candidates:
        rr = float(c.get("rerank_score") or 0.0)
        prior = min(max(float(c.get("weight") or 0.5), 0.0), 1.0)
        c["fused_score"] = (1 - a) * rr + a * prior
    return sorted(candidates, key=lambda x: x["fused_score"], reverse=True)[:top_k]


def cap_book_anchor_entries(ranked: list[dict]) -> list[dict]:
    """Multi-book questions: at most ONE book_anchor entry per book in the fused order.

    The anchor guarantees a named book is REPRESENTED; its 2nd/3rd same-book
    picks riding high rerank scores displaced gold from other strategies
    (2026-07-13 A/B). Excess anchor entries sink to the tail.
    """
    kept, demoted, seen = [], [], set()
    for c in ranked:
        if c.get("source_strategy") == BOOK_ANCHOR:
            if c["book_id"] in seen:
                demoted.append(c)
                continue
            seen.add(c["book_id"])
        kept.append(c)
    return kept + demoted


def _top_score(cands: list[dict], score_key: str) -> float:
    scores = [c.get(score_key) for c in cands if c.get(score_key) is not None]
    return max(scores) if scores else 1.0


def _in_chapter(c: dict, target: tuple[str, int]) -> bool:
    return c.get("book_id") == target[0] and c.get("chapter_num") == target[1]


def _evict_unprotected(result: list[dict], targets: list[tuple[str, int]], top_k: int) -> list[dict]:
    protected = [c for c in result if any(_in_chapter(c, t) for t in targets)]
    evictable = [c for c in result if not any(_in_chapter(c, t) for t in targets)]
    return (protected + evictable[:max(0, top_k - len(protected))])[:top_k]


def _pinnable(candidates: list[dict], existing: set[str], target: tuple[str, int]) -> list[dict]:
    """Strong pool passages of ``target`` not yet ranked: heaviest first, then canonical order.

    Legacy pericope ids (``gen:1:0``) sorted as strings gave the chapter's first
    pericopes; new ids do not (``ps:gen.1.14`` < ``ps:gen.1.6``), so the start key decides.
    """
    return sorted((c for c in candidates if c["id"] not in existing and _in_chapter(c, target)
                   and c.get("weight", 0) >= PIN_WEIGHT_FLOOR),
                  key=lambda c: (-c.get("weight", 0), key_order(c["start_key"])))


def _chapter_pins(ranked: list[dict], candidates: list[dict], targets: list[tuple[str, int]],
                  top_k: int, min_pins: int) -> list[dict]:
    """Passages each target still needs, in the order the user wrote the chapters."""
    pinned: list[dict] = []
    existing = {c["id"] for c in ranked}
    for target in targets:
        needed = min(min_pins, top_k) - sum(1 for c in ranked if _in_chapter(c, target))
        for c in _pinnable(candidates, existing, target)[:max(needed, 0)]:
            existing.add(c["id"])
            pinned.append(c)
    return pinned


def pin_chapter_candidates(ranked: list[dict], candidates: list[dict], verse_refs: list[VerseRef],
                           top_k: int, min_pins: int = 2, score_key: str = "rerank_score"
                           ) -> list[dict]:
    """Guarantee chapter-specified passages survive rerank by pinning them into top-k.

    One target per chapter-only reference (a chapter range is served by its first
    chapter, as legacy read it), pinned in the order the user wrote them; the
    result keeps at most ``top_k`` (the first-written chapters win), and the
    reranker still orders every slot the pins leave. Only pool candidates with
    weight >= PIN_WEIGHT_FLOOR are eligible. Pinned entries get a synthetic
    ``score_key`` just above the current max.
    """
    targets = list(dict.fromkeys((r.book_id, r.chapter) for r in verse_refs
                                 if r.verse_start is None))
    if not targets or not ranked:
        return ranked
    pinned = _chapter_pins(ranked, candidates, targets, top_k, min_pins)
    base = _top_score(ranked, score_key)
    for c in pinned:
        c[score_key] = base + 0.01
    result = pinned + ranked
    return _evict_unprotected(result, targets, top_k) if len(result) > top_k else result


def _book_anchor_order(eligible: list[dict], book_gate: bool) -> list[dict]:
    def sem(c: dict) -> float:
        return c.get("semantic_score", c.get("weight", 0))

    by_book: dict[str, list[dict]] = {}
    for c in eligible:
        by_book.setdefault(c["book_id"], []).append(c)
    for group in by_book.values():
        group.sort(key=sem, reverse=True)
    order = sorted(by_book, key=lambda b: sem(by_book[b][0]), reverse=True)
    if book_gate:
        return [by_book[b][0] for b in order]
    depth = max(map(len, by_book.values()), default=0)
    return [by_book[b][i] for i in range(depth) for b in order if i < len(by_book[b])]


def pin_book_anchor_candidates(ranked: list[dict], candidates: list[dict], top_k: int,
                               max_pins: int = 2, score_key: str = "rerank_score",
                               book_gate: bool = False) -> list[dict]:
    """Pin book_anchor candidates so a named book is represented in the top-k.

    Single-book questions pin unconditionally (measured neutral); multi-book
    questions (``book_gate``) pin only books absent from the ranking, one per book
    (2026-07-13 A/B: a pin for a book already present only evicted gold).
    """
    if not ranked or not candidates:
        return ranked
    existing = {c["id"] for c in ranked}
    eligible = [c for c in candidates
                if c.get("source_strategy") == BOOK_ANCHOR and c["id"] not in existing]
    if book_gate:
        present = {c["book_id"] for c in ranked}
        eligible = [c for c in eligible if c["book_id"] not in present]
    to_pin = _book_anchor_order(eligible, book_gate)[:max_pins]
    if not to_pin:
        return ranked
    base = _top_score(ranked, score_key)
    for i, c in enumerate(to_pin):
        c[score_key] = base + 0.004 * (max_pins - i)
    logger.info("book_anchor pin: %s", [c["id"] for c in to_pin])
    return (to_pin + ranked)[:top_k]

"""Candidate-pool bookkeeping shared by the routes and the ranking steps.

A candidate is a dict with at least ``id``, ``book_id``, ``chapter_num``,
``source_strategy`` and ``weight``; ``found_by`` lists every strategy that
returned its id (provenance only: it never decides which copy is kept).
"""

from __future__ import annotations


def labels_of(c: dict) -> list[str]:
    """Strategies already known to have returned candidate ``c``."""
    if c.get("found_by"):
        return c["found_by"]
    label = c.get("source_strategy")
    return [label] if label else []


def note_found_by(c: dict, label: str | None) -> None:
    """Record that strategy ``label`` also returned candidate ``c``."""
    found = c.setdefault("found_by", labels_of(c))
    if label and label not in found:
        found.append(label)


def dedup(candidates: list[dict]) -> list[dict]:
    """Deduplicate by id, keeping the highest weight (first seen on ties).

    The kept copy carries ``found_by``: every strategy that returned the id, in
    first-seen order.
    """
    seen: dict[str, dict] = {}
    found_by: dict[str, list[str]] = {}
    for c in candidates:
        cid = c["id"]
        labels = found_by.setdefault(cid, [])
        for label in labels_of(c):
            if label not in labels:
                labels.append(label)
        if cid not in seen or c["weight"] > seen[cid]["weight"]:
            seen[cid] = c
    for cid, c in seen.items():
        c["found_by"] = found_by[cid]
    return list(seen.values())


def apply_weights(candidates: list[dict], weight: float) -> list[dict]:
    """Raise every candidate's weight to at least ``weight``."""
    for c in candidates:
        if c.get("weight", 0) < weight:
            c["weight"] = weight
    return candidates


def book_chapters(candidates: list[dict]) -> list[tuple[str, int]]:
    """Unique (book_id, chapter) pairs in order of first appearance.

    The SQL supplement takes the first three, so the order decides which
    chapters get supplemented; first appearance in the (strategy-ordered) pool is
    deterministic, unlike a set.
    """
    pairs: dict[tuple[str, int], None] = {}
    for c in candidates:
        if c.get("book_id") and c.get("chapter_num") is not None:
            pairs.setdefault((c["book_id"], int(c["chapter_num"])), None)
    return list(pairs)

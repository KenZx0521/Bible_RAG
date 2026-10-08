"""Dense retrieval: BGE-M3 query vector → the build's Qdrant collection → PG content.

A hit is a verse record (``vs:``), an unchunked passage (``ps:``) or a chunk
(``ck:``). A verse hit stands for the passage that owns its unit (the payload's
``passage_id``), so verse and passage hits of one passage dedup into one
candidate; a chunk stays itself. Content comes from PostgreSQL in one batch.

Two labels, kept verbatim from the legacy backend so d3 identity gates still
compare (E0a): the routes' dense arm reports ``hybrid_hybrid`` (weights 0.70 for a
verse hit, 0.65 otherwise; prod ran with HYBRID_SEARCH_ENABLED=true, the dense arm
of the retired hybrid collection), the semantic_only baseline and book anchors
report ``semantic`` (0.65 / 0.6). Both search the same collection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import settings
from database import postgres, qdrant_db
from utils import embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DenseArm:
    label: str
    verse_weight: float
    other_weight: float


ROUTE_ARM = DenseArm("hybrid_hybrid", 0.70, 0.65)
SEMANTIC_ARM = DenseArm("semantic", 0.65, 0.6)


def _target(payload: dict[str, Any]) -> tuple[str, str]:
    """(candidate id, kind of source to fetch) of a hit."""
    if payload["kind"] == "verse":
        return payload["passage_id"], "passage"
    return payload["record_id"], payload["kind"]


async def retrieve_dense(query: str, arm: DenseArm, top_k: int | None = None,
                         book_ids: list[str] | None = None) -> list[dict]:
    """Candidates for ``query`` in hit order; ``book_ids`` restricts the search."""
    vector = embedder.encode_query(query)
    hits = qdrant_db.search(vector, top_k=top_k or settings.semantic_search_top_k,
                            book_ids=book_ids)
    targets = [_target(h["payload"]) for h in hits]
    sources = await postgres.fetch_sources(
        [t for t, kind in targets if kind == "passage"],
        [t for t, kind in targets if kind == "chunk"])
    candidates = [
        {**sources[target], "source_strategy": arm.label, "semantic_score": hit["score"],
         "weight": arm.verse_weight if hit["payload"]["kind"] == "verse" else arm.other_weight}
        for hit, (target, _) in zip(hits, targets)]
    logger.info("Dense retriever (%s): %d candidates", arm.label, len(candidates))
    return candidates

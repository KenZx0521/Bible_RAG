"""
Cross-Reference Retriever — follow CROSS_REFERENCES relationships in Neo4j.

Two entry points:
* retrieve_cross_references() — 1-hop, used by R5 seed expansion (legacy).
* retrieve_via_cross_references() — N-hop (default 2), surfaces neighbouring
  pericopes along the 916 hand-curated cross-book edges. Used by R3/R4/R5/R6
  pre-rerank expansion when settings.rag_use_cross_ref_expand is True.
"""

import logging

from database import neo4j_db, postgres

logger = logging.getLogger(__name__)


async def retrieve_cross_references(pericope_ids: list[str], top_k: int = 10) -> list[dict]:
    """1-hop cross-reference traversal (legacy entry point).

    Given pericope IDs, follow CROSS_REFERENCES in Neo4j to find related passages.
    Fetch full content from PostgreSQL.
    """
    candidates = []
    seen_ids: set[str] = set(pericope_ids)

    for pid in pericope_ids:
        refs = await neo4j_db.get_cross_references(pid, limit=top_k)
        for ref in refs:
            target_id = ref["id"]
            if target_id and target_id not in seen_ids:
                seen_ids.add(target_id)
                content_data = await postgres.get_content_by_id(target_id)
                if content_data:
                    candidates.append({
                        "id": target_id,
                        "content": content_data.get("content", ""),
                        "title": content_data.get("title", ref.get("title", "")),
                        "book_name": content_data.get("book_name", ref.get("book_name", "")),
                        "chapter_num": content_data.get("chapter_num", ref.get("chapter_num")),
                        "verse_range": content_data.get("metadata", {}).get("verse_range", ""),
                        "source_strategy": "cross_reference",
                        "weight": 0.7,
                    })

    logger.info(f"Cross-ref retriever: {len(candidates)} candidates from {len(pericope_ids)} pericopes")
    return candidates


# Hop-distance → weight curve. 1-hop edges are explicit citations (high signal);
# 2-hop are second-degree neighbours (signal weaker, used as expansion only).
_HOP_WEIGHT = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}


async def retrieve_via_cross_references(
    pericope_ids: list[str],
    max_hops: int = 2,
    limit: int = 30,
) -> list[dict]:
    """N-hop CROSS_REFERENCES expansion from a set of seed pericopes.

    Returns one candidate per distinct neighbouring pericope, with `weight`
    decaying by hop distance and `source_strategy` set to ``cross_ref_expand``.
    Designed to be merged into the pre-rerank candidate pool of R3/R4/R5/R6.
    """
    if not pericope_ids:
        return []

    refs = await neo4j_db.get_cross_references_multi_hop(
        pericope_ids, max_hops=max_hops, limit=limit
    )
    if not refs:
        logger.info(
            f"Cross-ref expand: no neighbours within {max_hops} hops of "
            f"{len(pericope_ids)} seeds"
        )
        return []

    candidates: list[dict] = []
    seen_ids: set[str] = set(pericope_ids)
    for ref in refs:
        target_id = ref.get("id")
        if not target_id or target_id in seen_ids:
            continue
        seen_ids.add(target_id)
        content_data = await postgres.get_content_by_id(target_id)
        if not content_data:
            continue
        hop = int(ref.get("hop_distance", 1) or 1)
        weight = _HOP_WEIGHT.get(hop, _HOP_WEIGHT[max(_HOP_WEIGHT)])
        candidates.append({
            "id": target_id,
            "content": content_data.get("content", ""),
            "title": content_data.get("title", ref.get("title", "")),
            "book_name": content_data.get("book_name", ref.get("book_name", "")),
            "chapter_num": content_data.get("chapter_num", ref.get("chapter_num")),
            "verse_range": content_data.get("metadata", {}).get(
                "verse_range", ref.get("verse_range", "")
            ),
            "source_strategy": "cross_ref_expand",
            "hop_distance": hop,
            "weight": weight,
        })

    logger.info(
        f"Cross-ref expand: {len(candidates)} neighbours within {max_hops} hops "
        f"from {len(pericope_ids)} seeds"
    )
    return candidates

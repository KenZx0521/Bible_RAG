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
                    votes = ref.get("votes")
                    candidates.append({
                        "id": target_id,
                        "content": content_data.get("content", ""),
                        "title": content_data.get("title", ref.get("title", "")),
                        "book_name": content_data.get("book_name", ref.get("book_name", "")),
                        "chapter_num": content_data.get("chapter_num", ref.get("chapter_num")),
                        "verse_range": content_data.get("metadata", {}).get("verse_range", ""),
                        "source_strategy": "cross_reference",
                        "votes": votes,
                        "weight": _edge_weight(1, votes),
                    })

    logger.info(f"Cross-ref retriever: {len(candidates)} candidates from {len(pericope_ids)} pericopes")
    return candidates


# Hop-distance → weight curves, split by edge provenance.
#
# Hand-curated markdown edges (votes >= _CURATED_VOTES; they carry no votes
# property and neo4j_db coalesces them to 999) are explicit cross-book
# citations — high prior, kept above semantic (0.7).
#
# TSK community edges (votes < 999) are *topical* associations: high votes
# mean strong thematic affinity, NOT same-narrative membership. The 2026-07-06
# P0 eval showed they displace narrative-correct pericopes on EVENT questions
# (保羅歸主 → act:13 宣教串珠, 復活當天 → 登山變像預言串珠), so their prior
# must sit below semantic (0.7) — they only win top-k when the rank-fusion
# layer sees both a decent rerank score and this supplementary prior.
_CURATED_VOTES = 999
_HOP_WEIGHT = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}
_TSK_HOP_WEIGHT = {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30}


def _edge_weight(hop: int, votes: int | None) -> float:
    curve = _HOP_WEIGHT if (votes is not None and votes >= _CURATED_VOTES) else _TSK_HOP_WEIGHT
    return curve.get(hop, curve[max(curve)])


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
        votes = ref.get("votes")
        weight = _edge_weight(hop, votes)
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
            "votes": votes,
            "seed_support": ref.get("seed_support"),
            "weight": weight,
        })

    logger.info(
        f"Cross-ref expand: {len(candidates)} neighbours within {max_hops} hops "
        f"from {len(pericope_ids)} seeds"
    )
    return candidates

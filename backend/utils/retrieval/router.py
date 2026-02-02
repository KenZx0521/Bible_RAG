"""
Multi-strategy retrieval router.
Orchestrates parallel retrieval, fusion, dedup, and reranking.
"""

import asyncio
import logging

from utils.verse_parser import VerseRef
from utils.retrieval.verse_retriever import retrieve_by_verse_refs
from utils.retrieval.semantic_retriever import retrieve_semantic
from utils.retrieval.graph_retriever import retrieve_by_entities
from utils.retrieval.cross_ref_retriever import retrieve_cross_references
from utils import reranker as reranker_mod
from config import settings

logger = logging.getLogger(__name__)


async def retrieve_and_rerank(
    query: str,
    verse_refs: list[VerseRef],
    intent_type: str,
    entity_names: list[str],
    top_k: int | None = None,
) -> tuple[list[dict], dict]:
    """
    Execute parallel multi-strategy retrieval, fuse, dedup, and rerank.

    Returns:
        (top_k_results, retrieval_stats)
    """
    k = top_k or settings.default_top_k

    # Fast path: verse refs detected → direct lookup only, skip semantic & rerank
    if verse_refs:
        try:
            candidates = await retrieve_by_verse_refs(verse_refs)
        except Exception as e:
            logger.warning(f"Verse direct retrieval failed: {e}")
            candidates = []

        stats = {
            "strategies_used": ["verse_direct"],
            "total_candidates": len(candidates),
            "reranked_top_k": len(candidates),
        }
        return candidates[:k], stats

    # Normal path: no explicit verse refs → multi-strategy retrieval
    strategies_used: list[str] = []
    tasks: list[asyncio.Task] = []

    # Semantic retrieval
    tasks.append(asyncio.create_task(retrieve_semantic(query)))
    strategies_used.append("semantic")

    # Graph retrieval if entities detected
    if entity_names:
        tasks.append(asyncio.create_task(retrieve_by_entities(entity_names)))
        strategies_used.append("graph")

    # Wait for all retrievals
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect all candidates
    all_candidates: list[dict] = []
    for result in all_results:
        if isinstance(result, Exception):
            logger.warning(f"Retrieval strategy failed: {result}")
            continue
        all_candidates.extend(result)

    # Dedup by ID, keeping highest weight.
    deduped: dict[str, dict] = {}
    for c in all_candidates:
        cid = c["id"]
        if cid not in deduped or c["weight"] > deduped[cid]["weight"]:
            deduped[cid] = c
    candidates = list(deduped.values())

    total_candidates = len(candidates)

    # Cross-reference retrieval if applicable
    if intent_type == "cross_reference" and candidates:
        source_pericope_ids = [c["id"] for c in candidates[:5] if ":" in c["id"]]
        if source_pericope_ids:
            cross_refs = await retrieve_cross_references(source_pericope_ids, top_k=10)
            for cr in cross_refs:
                if cr["id"] not in deduped:
                    deduped[cr["id"]] = cr
                    candidates.append(cr)
            strategies_used.append("cross_reference")
            total_candidates = len(candidates)

    # Rerank if we have candidates
    if candidates:
        try:
            ranked = reranker_mod.rerank(query, candidates, top_k=k, text_key="content")
        except Exception as e:
            logger.warning(f"Reranker failed, falling back to weight-based sorting: {e}")
            ranked = sorted(candidates, key=lambda x: x.get("weight", 0), reverse=True)[:k]
    else:
        ranked = []

    stats = {
        "strategies_used": strategies_used,
        "total_candidates": total_candidates,
        "reranked_top_k": len(ranked),
    }

    return ranked, stats

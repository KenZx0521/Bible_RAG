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
    strategies_used: list[str] = []
    tasks: list[asyncio.Task] = []

    # Always run semantic retrieval
    tasks.append(asyncio.create_task(retrieve_semantic(query)))
    strategies_used.append("semantic")

    # Verse direct retrieval if refs detected
    if verse_refs:
        tasks.append(asyncio.create_task(retrieve_by_verse_refs(verse_refs)))
        strategies_used.append("verse_direct")

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
    # When a verse hit and a pericope hit refer to the same passage,
    # the verse hit already uses the parent pericope ID, so they share
    # the same key.  Give a +0.05 boost when both hit the same ID.
    deduped: dict[str, dict] = {}
    hit_sources: dict[str, set] = {}  # track which source types hit each ID
    for c in all_candidates:
        cid = c["id"]
        is_verse = c.get("_is_verse_hit", False)
        src_tag = "verse" if is_verse else c.get("source_strategy", "other")
        hit_sources.setdefault(cid, set()).add(src_tag)
        if cid not in deduped or c["weight"] > deduped[cid]["weight"]:
            deduped[cid] = c
    # Apply boost when verse + pericope/semantic both hit the same ID
    for cid, sources in hit_sources.items():
        if "verse" in sources and len(sources) > 1 and cid in deduped:
            deduped[cid]["weight"] = min(deduped[cid]["weight"] + 0.05, 1.0)
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

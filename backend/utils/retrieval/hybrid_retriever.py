"""
Hybrid Retriever — the dense arm of the hybrid Qdrant collection.

The sparse (CKIP + BM25) side was retired in E0a: qdrant-client 1.8.2 has no
query_points, so RRF fusion never ran and every query fell back to this dense
search (G28). Collection, query parameters, candidate shape and the strategy
label are unchanged, so retrieval results are identical to the fallback.
"""

import logging

from database import qdrant_db, postgres
from utils import embedder
from config import settings

logger = logging.getLogger(__name__)

# The label the fallback reported when CKIP found an in-vocabulary token (prod
# logs: 587/587 queries). Kept verbatim: d3 identity gates compare it.
SOURCE_STRATEGY = "hybrid_hybrid"


async def retrieve_hybrid(query: str, top_k: int | None = None) -> list[dict]:
    """
    Dense retrieval on the hybrid collection, then full content from PostgreSQL.

    Args:
        query: The user's query text.
        top_k: Number of results to return.

    Returns:
        List of candidate dicts with: id, content, title, book_name,
        chapter_num, verse_range, source_strategy, weight, hybrid_score.
    """
    k = top_k or settings.semantic_search_top_k
    dense_vector = embedder.encode_query(query)
    hits = qdrant_db.search_hybrid_dense(dense_vector, top_k=k)
    candidates = [await _candidate(hit) for hit in hits]
    logger.info(f"Hybrid retriever (dense arm): {len(candidates)} candidates")
    return candidates


async def _candidate(hit: dict) -> dict:
    record_id = hit["record_id"]
    hit_type = hit.get("type", "unknown")

    # Determine if this is a verse-level hit
    is_verse = hit_type == "verse" or (
        len(record_id.split(":")) == 5 and record_id.split(":")[3] == "v"
    )

    # For verse hits, use parent pericope ID as candidate ID for dedup
    if is_verse:
        candidate_id = hit.get("parent_pericope_id") or ":".join(record_id.split(":")[:3])
        weight = 0.70  # Hybrid verse hits get higher weight
    else:
        candidate_id = record_id
        weight = 0.65  # Hybrid search gets slightly higher base weight

    content_data = await postgres.get_content_by_id(record_id)
    if content_data is None:
        # Use content_preview from Qdrant payload as fallback
        content_data = {
            "id": candidate_id,
            "content": hit.get("content_preview", ""),
            "title": hit.get("title", ""),
            "book_name": hit.get("book_name", ""),
            "chapter_num": hit.get("chapter_num"),
            "verse_range": hit.get("verse_range", ""),
        }
    else:
        content_data["verse_range"] = content_data.get("metadata", {}).get("verse_range", "")

    return {
        "id": candidate_id,
        "content": content_data.get("content", ""),
        "title": content_data.get("title", ""),
        "book_name": content_data.get("book_name", ""),
        "chapter_num": content_data.get("chapter_num"),
        "verse_range": content_data.get("verse_range", ""),
        "source_strategy": SOURCE_STRATEGY,
        "weight": weight,
        "hybrid_score": hit["score"],
        "_is_verse_hit": is_verse,
    }

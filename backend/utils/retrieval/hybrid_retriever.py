"""
Hybrid Retriever — combined dense + sparse vector search via Qdrant.

Uses BM25-based sparse vectors + BGE-M3 dense vectors with RRF fusion
for improved retrieval, especially for exact term matching and Chinese text.
"""

import logging

from database import qdrant_hybrid, postgres
from utils import embedder, sparse_encoder
from config import settings

logger = logging.getLogger(__name__)


async def retrieve_hybrid(query: str, top_k: int | None = None) -> list[dict]:
    """
    Perform hybrid retrieval using dense + sparse vectors with RRF fusion.

    Steps:
    1. Encode query with BGE-M3 (dense) and BM25 (sparse)
    2. Search Qdrant hybrid collection with RRF fusion
    3. Fetch full content from PostgreSQL

    Args:
        query: The user's query text.
        top_k: Number of results to return.

    Returns:
        List of candidate dicts with: id, content, title, book_name,
        chapter_num, verse_range, source_strategy, weight, hybrid_score.
    """
    k = top_k or settings.semantic_search_top_k

    # Encode query - dense
    dense_vector = embedder.encode_query(query)

    # Encode query - sparse
    if sparse_encoder.is_initialized():
        sparse_indices, sparse_values = sparse_encoder.encode_query(query)
    else:
        logger.warning("Sparse encoder not initialized, using dense-only search")
        sparse_indices, sparse_values = [], []

    # Perform hybrid search
    if sparse_indices:
        hits = qdrant_hybrid.hybrid_search(
            dense_vector=dense_vector,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            top_k=k,
            prefetch_limit=settings.hybrid_prefetch_limit,
        )
        search_mode = "hybrid"
    else:
        # Fallback to dense-only on hybrid collection
        hits = qdrant_hybrid.dense_only_search(
            dense_vector=dense_vector,
            top_k=k,
        )
        search_mode = "dense_only"

    # Fetch full content from PostgreSQL for each hit
    candidates = []
    for hit in hits:
        record_id = hit["record_id"]
        hit_type = hit.get("type", "unknown")

        # Determine if this is a verse-level hit
        is_verse = hit_type == "verse" or (
            len(record_id.split(":")) == 5 and record_id.split(":")[3] == "v"
        )

        # For verse hits, use parent pericope ID as candidate ID for dedup
        if is_verse:
            parent_id = hit.get("parent_pericope_id") or ":".join(
                record_id.split(":")[:3]
            )
            candidate_id = parent_id
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
            content_data["verse_range"] = content_data.get("metadata", {}).get(
                "verse_range", ""
            )

        candidates.append({
            "id": candidate_id,
            "content": content_data.get("content", ""),
            "title": content_data.get("title", ""),
            "book_name": content_data.get("book_name", ""),
            "chapter_num": content_data.get("chapter_num"),
            "verse_range": content_data.get("verse_range", ""),
            "source_strategy": f"hybrid_{search_mode}",
            "weight": weight,
            "hybrid_score": hit["score"],
            "_is_verse_hit": is_verse,
        })

    logger.info(
        f"Hybrid retriever ({search_mode}): {len(candidates)} candidates"
    )
    return candidates

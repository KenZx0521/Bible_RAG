"""
Qdrant hybrid collection client for dense + sparse vector search.

Supports both old (< 1.7.0) and new (>= 1.7.0) qdrant-client APIs.
"""

import logging
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from config import settings
from database.qdrant_db import get_client

logger = logging.getLogger(__name__)

# Check API version once at module load
_has_query_points: Optional[bool] = None


def _check_api_version() -> bool:
    """Check if the new query_points API is available."""
    global _has_query_points
    if _has_query_points is None:
        client = get_client()
        _has_query_points = hasattr(client, 'query_points')
        if not _has_query_points:
            logger.warning(
                "qdrant-client < 1.7.0 detected. "
                "Hybrid search with RRF fusion requires upgrade: "
                "pip install --upgrade qdrant-client"
            )
    return _has_query_points


def _extract_payload(point) -> dict:
    """Extract payload from a search result point."""
    payload = point.payload or {}
    return {
        "record_id": payload.get("record_id", ""),
        "score": point.score,
        "type": payload.get("type", ""),
        "book_id": payload.get("book_id", ""),
        "book_name": payload.get("book_name", ""),
        "chapter_num": payload.get("chapter_num"),
        "title": payload.get("title", ""),
        "verse_range": payload.get("verse_range", ""),
        "content_preview": payload.get("content_preview", ""),
        "parent_pericope_id": payload.get("parent_pericope_id"),
    }


def hybrid_search(
    dense_vector: List[float],
    sparse_indices: List[int],
    sparse_values: List[float],
    top_k: int = 20,
    prefetch_limit: Optional[int] = None,
) -> List[dict]:
    """
    Perform hybrid search using both dense and sparse vectors with RRF fusion.

    Args:
        dense_vector: Dense embedding vector (1024D BGE-M3).
        sparse_indices: Sparse vector indices.
        sparse_values: Sparse vector values (BM25 scores).
        top_k: Number of final results to return.
        prefetch_limit: Number of candidates to prefetch from each modality.

    Returns:
        List of dicts with: record_id, score, type, book_id, book_name,
        chapter_num, title, verse_range, content_preview.
    """
    client = get_client()
    prefetch_limit = prefetch_limit or settings.hybrid_prefetch_limit

    if _check_api_version():
        # New API (qdrant-client >= 1.7.0) - supports RRF fusion
        prefetch_queries = [
            models.Prefetch(
                query=dense_vector,
                using="dense",
                limit=prefetch_limit,
            ),
        ]

        if sparse_indices:
            prefetch_queries.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values,
                    ),
                    using="sparse",
                    limit=prefetch_limit,
                ),
            )

        results = client.query_points(
            collection_name=settings.qdrant_hybrid_collection,
            prefetch=prefetch_queries,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return [_extract_payload(point) for point in results.points]

    else:
        # Old API fallback - dense search only, manual fusion if needed
        logger.warning("Falling back to dense-only search (old API)")
        return dense_only_search(dense_vector, top_k)


def dense_only_search(
    dense_vector: List[float],
    top_k: int = 20,
) -> List[dict]:
    """
    Perform dense-only search on the hybrid collection.

    Useful as a fallback when sparse encoding is not available.

    Args:
        dense_vector: Dense embedding vector (1024D BGE-M3).
        top_k: Number of results to return.

    Returns:
        List of dicts with payload fields.
    """
    client = get_client()

    if _check_api_version():
        # New API
        results = client.query_points(
            collection_name=settings.qdrant_hybrid_collection,
            query=dense_vector,
            using="dense",
            limit=top_k,
            with_payload=True,
        )
        return [_extract_payload(point) for point in results.points]
    else:
        # Old API - use search with named vector
        results = client.search(
            collection_name=settings.qdrant_hybrid_collection,
            query_vector=("dense", dense_vector),
            limit=top_k,
        )
        return [_extract_payload(point) for point in results]


def check_hybrid_collection() -> bool:
    """
    Check if hybrid collection exists and is accessible.

    Returns:
        True if collection exists and is ready.
    """
    try:
        client = get_client()
        collections = client.get_collections().collections
        exists = any(
            c.name == settings.qdrant_hybrid_collection for c in collections
        )
        return exists
    except Exception as e:
        logger.warning(f"Failed to check hybrid collection: {e}")
        return False


def get_hybrid_collection_info() -> Optional[dict]:
    """
    Get information about the hybrid collection.

    Returns:
        Dict with collection stats or None if not available.
    """
    try:
        client = get_client()
        info = client.get_collection(settings.qdrant_hybrid_collection)
        return {
            "name": settings.qdrant_hybrid_collection,
            "points_count": getattr(info, "points_count", 0),
            "status": str(info.status),
        }
    except Exception as e:
        logger.warning(f"Failed to get hybrid collection info: {e}")
        return None

"""
Qdrant vector database client and search functions.
"""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from config import settings

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None


def init_client() -> QdrantClient:
    global _client
    _client = QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
    )
    logger.info("Qdrant client initialized")
    return _client


def close_client():
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Qdrant client closed")


def get_client() -> QdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant client not initialized")
    return _client


def health_check() -> bool:
    try:
        client = get_client()
        client.get_collections()
        return True
    except Exception:
        return False


def search_vectors(
    query_vector: list[float],
    top_k: int = 20,
    score_threshold: Optional[float] = None,
) -> list[dict]:
    """
    Search for similar vectors in the bible_embeddings collection.

    Returns list of dicts with: record_id, score, type, book_id, book_name,
    chapter_num, title, verse_range, content_preview.
    """
    client = get_client()
    results = client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
    )

    return [
        {
            "record_id": hit.payload.get("record_id", ""),
            "score": hit.score,
            "type": hit.payload.get("type", ""),
            "book_id": hit.payload.get("book_id", ""),
            "book_name": hit.payload.get("book_name", ""),
            "chapter_num": hit.payload.get("chapter_num"),
            "title": hit.payload.get("title", ""),
            "verse_range": hit.payload.get("verse_range", ""),
            "content_preview": hit.payload.get("content_preview", ""),
        }
        for hit in results
    ]

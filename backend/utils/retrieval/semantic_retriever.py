"""
Semantic Retriever — vector similarity search via Qdrant + BGE-M3 embeddings.
"""

import logging

from database import qdrant_db, postgres
from utils import embedder
from config import settings

logger = logging.getLogger(__name__)


async def retrieve_semantic(query: str, top_k: int | None = None) -> list[dict]:
    """
    Embed query with BGE-M3, search Qdrant, then fetch full content from PostgreSQL.

    Returns list of candidate dicts with: id, content, title, book_name,
    chapter_num, verse_range, source_strategy, weight, semantic_score.
    """
    k = top_k or settings.semantic_search_top_k

    # Embed query
    query_vector = embedder.encode_query(query)

    # Search Qdrant
    hits = qdrant_db.search_vectors(query_vector, top_k=k)

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
            parent_id = hit.get("parent_pericope_id") or ":".join(record_id.split(":")[:3])
            candidate_id = parent_id
            weight = 0.65  # Verse hits are more precise than pericope
        else:
            candidate_id = record_id
            weight = 0.6

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

        candidates.append({
            "id": candidate_id,
            "content": content_data.get("content", ""),
            "title": content_data.get("title", ""),
            "book_name": content_data.get("book_name", ""),
            "chapter_num": content_data.get("chapter_num"),
            "verse_range": content_data.get("verse_range", ""),
            "source_strategy": "semantic",
            "weight": weight,
            "semantic_score": hit["score"],
            "_is_verse_hit": is_verse,
        })

    logger.info(f"Semantic retriever: {len(candidates)} candidates")
    return candidates

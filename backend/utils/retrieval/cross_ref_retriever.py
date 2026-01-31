"""
Cross-Reference Retriever — follow CROSS_REFERENCES relationships in Neo4j.
"""

import logging

from database import neo4j_db, postgres

logger = logging.getLogger(__name__)


async def retrieve_cross_references(pericope_ids: list[str], top_k: int = 10) -> list[dict]:
    """
    Given pericope IDs, follow CROSS_REFERENCES in Neo4j to find related passages.
    Fetch full content from PostgreSQL.

    Returns list of candidate dicts.
    """
    candidates = []
    seen_ids: set[str] = set(pericope_ids)  # exclude source pericopes

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

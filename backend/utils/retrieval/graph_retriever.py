"""
Graph Retriever — knowledge graph traversal via Neo4j for entity-based queries.
"""

import logging

from database import neo4j_db, postgres

logger = logging.getLogger(__name__)


async def retrieve_by_entities(entity_names: list[str], top_k: int = 10) -> list[dict]:
    """
    Find entities in Neo4j, then traverse MENTIONS to find related pericopes/chunks.
    Fetch full content from PostgreSQL.

    Returns list of candidate dicts.
    """
    candidates = []
    seen_ids: set[str] = set()

    # Collect all matched entity_ids
    all_entity_ids: list[str] = []

    for name in entity_names:
        entities = await neo4j_db.find_entity_by_name(name, limit=3)
        for entity in entities:
            eid = entity["entity_id"]
            all_entity_ids.append(eid)

            # Get pericopes related to this entity
            related = await neo4j_db.get_entity_related_pericopes(eid, limit=top_k)
            for item in related:
                record_id = item["id"]
                if record_id and record_id not in seen_ids:
                    seen_ids.add(record_id)
                    content_data = await postgres.get_content_by_id(record_id)
                    if content_data:
                        candidates.append({
                            "id": record_id,
                            "content": content_data.get("content", ""),
                            "title": content_data.get("title", item.get("title", "")),
                            "book_name": content_data.get("book_name", item.get("book_name", "")),
                            "chapter_num": content_data.get("chapter_num", item.get("chapter_num")),
                            "verse_range": content_data.get("metadata", {}).get("verse_range", item.get("verse_range", "")),
                            "source_strategy": "graph",
                            "weight": 0.8,
                        })

    # If multiple entities, also look for shared pericopes
    if len(all_entity_ids) >= 2:
        unique_ids = list(dict.fromkeys(all_entity_ids))[:5]
        shared = await neo4j_db.get_entities_shared_pericopes(unique_ids, limit=5)
        for item in shared:
            record_id = item["id"]
            if record_id and record_id not in seen_ids:
                seen_ids.add(record_id)
                content_data = await postgres.get_content_by_id(record_id)
                if content_data:
                    candidates.append({
                        "id": record_id,
                        "content": content_data.get("content", ""),
                        "title": content_data.get("title", ""),
                        "book_name": content_data.get("book_name", ""),
                        "chapter_num": content_data.get("chapter_num"),
                        "verse_range": content_data.get("metadata", {}).get("verse_range", ""),
                        "source_strategy": "graph",
                        "weight": 0.9,  # shared context is more relevant
                    })

    logger.info(f"Graph retriever: {len(candidates)} candidates from {len(entity_names)} entities")
    return candidates

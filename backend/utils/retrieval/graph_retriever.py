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


async def retrieve_by_events(event_keywords: list[str], top_k: int = 10) -> list[dict]:
    """
    Find Event nodes by keyword, then traverse MENTIONS to find related pericopes.
    Fetch full content from PostgreSQL.

    Used by route R4 (event search).
    """
    candidates = []
    seen_ids: set[str] = set()

    for keyword in event_keywords:
        events = await neo4j_db.find_events_by_keyword(keyword, limit=3)
        for event in events:
            eid = event["entity_id"]
            # Exact keyword↔name/alias equality marks a curated modern→ancient
            # bridge (e.g. detected keyword 保羅歸主 == alias of 掃羅的轉變).
            # Downstream _pin_keyword_event_candidates relies on this flag —
            # substring matches (復活 ⊂ 耶穌復活) stay unpinned.
            aliases = event.get("aliases") or []
            keyword_exact = keyword == (event.get("canonical_name") or "") or keyword in aliases
            event_mc = event.get("mention_count") or 0
            related = await neo4j_db.get_event_related_content(eid, limit=top_k)
            for rank, item in enumerate(related):
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
                            "source_strategy": "graph_event",
                            "via_event_id": eid,
                            "via_event_name": event.get("canonical_name"),
                            "via_event_mc": event_mc,
                            "keyword_exact": keyword_exact,
                            "anchor_rank": rank,
                            "weight": 0.85,
                        })

    logger.info(f"Graph event retriever: {len(candidates)} candidates from {len(event_keywords)} keywords")
    return candidates


async def retrieve_by_places(place_names: list[str], top_k: int = 10) -> list[dict]:
    """
    Find Place entities by name, then traverse MENTIONS to find related pericopes.
    Fetch full content from PostgreSQL.

    Used by route R6 (place search).
    """
    candidates = []
    seen_ids: set[str] = set()

    for name in place_names:
        entities = await neo4j_db.find_entity_by_name(name, limit=3)
        for entity in entities:
            # Filter to Place labels only
            labels = entity.get("labels", [])
            if "Place" not in labels:
                continue
            eid = entity["entity_id"]
            related = await neo4j_db.get_place_related_content(eid, limit=top_k)
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
                            "source_strategy": "graph_place",
                            "weight": 0.85,
                        })

    logger.info(f"Graph place retriever: {len(candidates)} candidates from {len(place_names)} places")
    return candidates

"""Entity-Path Retriever — leverages Entity-Entity edges and entity embeddings.

Two strategies:

1. retrieve_by_entity_path(entity_ids, max_hops=2):
   Walks Entity-[r*1..N]-Entity-[:MENTIONS]-Pericope where r is any
   non-structural relation (FATHER_OF, RULED, ...). Activated once
   import_relations_neo4j.py has populated Entity-Entity edges.

2. retrieve_by_entity_query(query_text, top_k=10):
   Encodes the query with BGE-M3, hits Qdrant `bible_entities` collection,
   resolves to entity_ids, then runs retrieve_by_entity_path. Activated
   once embed_entities.py has populated the new Qdrant collection.
"""

from __future__ import annotations

import logging
from typing import Optional

from database import neo4j_db, postgres
from utils import embedder

logger = logging.getLogger(__name__)


_STRUCTURAL_RELATIONS = {"CONTAINS", "NEXT", "NEXT_BOOK", "MENTIONS", "CROSS_REFERENCES"}


_ENTITY_PATH_CYPHER = """
MATCH (seed:Entity)
WHERE seed.entity_id IN $entity_ids
MATCH path = (seed)-[r*1..%(hops)d]-(other:Entity)
WHERE NOT other.entity_id IN $entity_ids
  AND ALL(rel IN r WHERE NOT type(rel) IN $structural)
WITH other, min(length(path)) AS hop_distance,
     [rel IN r | type(rel)] AS path_types
LIMIT $entity_limit
MATCH (other)-[:MENTIONS]-(p:Pericope)
WITH other, p, hop_distance, path_types
RETURN p.id AS pericope_id,
       p.title AS title,
       p.book_name AS book_name,
       p.chapter_num AS chapter_num,
       p.verse_range AS verse_range,
       other.entity_id AS via_entity_id,
       other.canonical_name AS via_entity_name,
       hop_distance,
       path_types
ORDER BY hop_distance ASC
LIMIT $limit
"""


_HOP_WEIGHT = {1: 0.85, 2: 0.65, 3: 0.45}


async def retrieve_by_entity_path(
    entity_ids: list[str],
    max_hops: int = 2,
    limit: int = 20,
    entity_limit: int = 60,
) -> list[dict]:
    if not entity_ids:
        return []
    hops = max(1, min(int(max_hops), 3))
    cypher = _ENTITY_PATH_CYPHER % {"hops": hops}

    driver = neo4j_db.get_driver()
    candidates: list[dict] = []
    seen_pericope_ids: set[str] = set()
    async with driver.session() as session:
        result = await session.run(
            cypher,
            entity_ids=entity_ids,
            structural=list(_STRUCTURAL_RELATIONS),
            entity_limit=entity_limit,
            limit=limit,
        )
        for record in await result.data():
            pid = record.get("pericope_id")
            if not pid or pid in seen_pericope_ids:
                continue
            seen_pericope_ids.add(pid)

            content_data = await postgres.get_content_by_id(pid)
            if not content_data:
                continue
            hop = int(record.get("hop_distance") or 1)
            weight = _HOP_WEIGHT.get(hop, 0.4)
            candidates.append({
                "id": pid,
                "content": content_data.get("content", ""),
                "title": content_data.get("title", record.get("title") or ""),
                "book_name": content_data.get("book_name", record.get("book_name") or ""),
                "chapter_num": content_data.get("chapter_num", record.get("chapter_num")),
                "verse_range": content_data.get("metadata", {}).get(
                    "verse_range", record.get("verse_range") or ""
                ),
                "source_strategy": "entity_path",
                "hop_distance": hop,
                "via_entity_id": record.get("via_entity_id"),
                "via_entity_name": record.get("via_entity_name"),
                "path_types": record.get("path_types") or [],
                "weight": weight,
            })

    logger.info(
        "entity_path retriever: %d pericope candidates from %d seeds (max_hops=%d)",
        len(candidates), len(entity_ids), hops,
    )
    return candidates


async def retrieve_by_entity_query(
    query_text: str,
    top_k_entities: int = 10,
    max_hops: int = 2,
    pericope_limit: int = 20,
    qdrant_collection: Optional[str] = None,
) -> list[dict]:
    if not query_text:
        return []

    try:
        from qdrant_client import QdrantClient
        from config import settings
    except ImportError:
        logger.warning("qdrant_client missing — entity_query disabled")
        return []

    collection_name = qdrant_collection or "bible_entities"

    query_vector = embedder.encode_query(query_text).tolist()

    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_http_port)
    try:
        existing = {c.name for c in client.get_collections().collections}
        if collection_name not in existing:
            logger.info(
                "Qdrant collection %s missing — run scripts/embed_entities.py first",
                collection_name,
            )
            return []
        results = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k_entities,
        )
    finally:
        client.close()

    entity_ids = [hit.payload.get("entity_id") for hit in results if hit.payload]
    entity_ids = [e for e in entity_ids if e]
    if not entity_ids:
        return []

    return await retrieve_by_entity_path(entity_ids, max_hops=max_hops, limit=pericope_limit)

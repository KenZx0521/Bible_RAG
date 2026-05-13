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
    top_k_entities: int = 5,
    score_threshold: float = 0.5,
    hub_threshold: int = 50,
    pericopes_per_entity_normal: int = 5,
    pericopes_per_entity_hub: int = 3,
    qdrant_collection: Optional[str] = None,
) -> list[dict]:
    """Entity-agnostic vector pivot: query → bible_entities top-k entities →
    Neo4j MENTIONS → pericope candidates. No type filter (Event-only is too
    restrictive — see module docstring).

    Why Neo4j (not Qdrant payload.pericope_ids): embed_entities.py writes only
    an unsorted top-5 sample of pericope_ids into payload (Cypher LIMIT 5,
    storage order). For hub entities like 掃羅 (69 mentions), the correct
    pericopes (e.g. act:9:* for 保羅歸主) often miss that sample. Going through
    Neo4j MENTIONS directly returns the full mention set with deterministic
    hub-aware capping.

    Hub entities (>= hub_threshold MENTIONS edges) are capped at
    pericopes_per_entity_hub to prevent topic-pollution from well-connected
    entities such as 摩西 (256 mentions) or 聖靈 (146).
    """
    if not query_text:
        return []

    try:
        from qdrant_client import QdrantClient
        from config import settings
    except ImportError:
        logger.warning("qdrant_client missing — entity_query disabled")
        return []

    collection_name = qdrant_collection or settings.qdrant_entity_collection

    query_vector = embedder.encode_query(query_text)

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
            score_threshold=score_threshold,
        )
    finally:
        client.close()

    if not results:
        return []

    # Build entity_id → metadata map (preserves Qdrant ranking order)
    entity_meta: dict[str, dict] = {}
    ordered_eids: list[str] = []
    for hit in results:
        payload = hit.payload or {}
        eid = payload.get("entity_id")
        if eid and eid not in entity_meta:
            entity_meta[eid] = {
                "score": float(hit.score),
                "canonical_name": payload.get("canonical_name"),
                "type": payload.get("type"),
            }
            ordered_eids.append(eid)

    if not entity_meta:
        return []

    # Batch fetch real MENTIONS pericopes via Neo4j (replaces payload sampling).
    records = await neo4j_db.get_pericopes_for_entities_hub_aware(
        ordered_eids,
        hub_threshold=hub_threshold,
        hub_cap=pericopes_per_entity_hub,
        normal_cap=pericopes_per_entity_normal,
    )

    # Group by entity, preserve Neo4j result order (used as pericope_rank)
    by_entity: dict[str, list[dict]] = {}
    for rec in records:
        by_entity.setdefault(rec["entity_id"], []).append(rec)

    candidates: list[dict] = []
    seen_pids: set[str] = set()
    for eid in ordered_eids:
        info = entity_meta[eid]
        entity_records = by_entity.get(eid, [])
        if not entity_records:
            continue
        total_mentions = entity_records[0].get("total_mentions", 0) or 0
        is_hub = total_mentions >= hub_threshold
        for i, rec in enumerate(entity_records):
            pid = rec.get("id")
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            content_data = await postgres.get_content_by_id(pid)
            if not content_data:
                continue
            weight = info["score"] * (0.9 ** i)
            candidates.append({
                "id": pid,
                "content": content_data.get("content", ""),
                "title": content_data.get("title", rec.get("title", "")),
                "book_name": content_data.get("book_name", rec.get("book_name", "")),
                "chapter_num": content_data.get("chapter_num", rec.get("chapter_num")),
                "verse_range": content_data.get("metadata", {}).get(
                    "verse_range", rec.get("verse_range", "")
                ),
                "source_strategy": "entity_query",
                "via_entity_id": eid,
                "via_entity_name": info["canonical_name"],
                "via_entity_type": info["type"],
                "via_entity_score": info["score"],
                "via_total_mentions": total_mentions,
                "is_hub": is_hub,
                "pericope_rank": i,
                "weight": weight,
            })

    logger.info(
        "entity_query: %d candidates from %d entities (top_k=%d, threshold=%.2f)",
        len(candidates), len(results), top_k_entities, score_threshold,
    )
    return candidates

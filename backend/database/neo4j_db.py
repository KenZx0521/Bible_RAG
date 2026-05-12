"""
Neo4j async driver and graph query functions.
"""

import logging
from typing import Optional

from neo4j import AsyncGraphDatabase, AsyncDriver

from config import settings

logger = logging.getLogger(__name__)

_driver: Optional[AsyncDriver] = None


async def init_driver() -> AsyncDriver:
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j async driver initialized")
    return _driver


async def close_driver():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


def get_driver() -> AsyncDriver:
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialized")
    return _driver


async def health_check() -> bool:
    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS n")
            await result.single()
        return True
    except Exception:
        return False


async def find_entity_by_name(name: str, limit: int = 5) -> list[dict]:
    """Find entities by canonical name or alias in Neo4j."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e)
            WHERE (e:Person OR e:Place OR e:Group OR e:Event OR e:Object OR e:Theme)
              AND (e.canonical_name CONTAINS $name
                   OR any(a IN e.aliases WHERE a CONTAINS $name))
            RETURN e.entity_id AS entity_id,
                   e.canonical_name AS canonical_name,
                   labels(e) AS labels,
                   e.description AS description,
                   e.mention_count AS mention_count
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """,
            name=name,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_entity_related_pericopes(entity_id: str, limit: int = 10) -> list[dict]:
    """Get pericopes/chunks related to an entity via MENTIONS relationships."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {entity_id: $entity_id})-[:MENTIONS]-(p)
            WHERE p:Pericope OR p:Chunk
            RETURN p.id AS id,
                   labels(p) AS labels,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_entities_shared_pericopes(entity_ids: list[str], limit: int = 10) -> list[dict]:
    """Find pericopes that mention multiple entities (shared context)."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {entity_id: $first_id})-[:MENTIONS]-(p)
            WHERE (p:Pericope OR p:Chunk)
              AND ALL(eid IN $other_ids WHERE
                EXISTS {
                  MATCH (e2 {entity_id: eid})-[:MENTIONS]-(p)
                }
              )
            RETURN p.id AS id,
                   labels(p) AS labels,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            LIMIT $limit
            """,
            first_id=entity_ids[0],
            other_ids=entity_ids[1:],
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_cross_references(pericope_id: str, limit: int = 10) -> list[dict]:
    """Get cross-referenced pericopes/chapters for a given pericope."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Pericope {id: $pericope_id})-[:CROSS_REFERENCES]->(target)
            RETURN target.id AS id,
                   labels(target) AS labels,
                   target.title AS title,
                   target.book_name AS book_name,
                   target.chapter_num AS chapter_num
            LIMIT $limit
            """,
            pericope_id=pericope_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_cross_references_multi_hop(
    pericope_ids: list[str], max_hops: int = 2, limit: int = 30
) -> list[dict]:
    """Traverse CROSS_REFERENCES up to `max_hops` steps from any seed pericope.

    Used by retrieve_via_cross_references() to surface neighbouring pericopes
    along the 916 hand-curated cross-book edges. Returns DISTINCT targets only,
    excluding the seed set itself. `hop_distance` reflects the shortest path
    length back to a seed.
    """
    if not pericope_ids or max_hops < 1:
        return []
    hops = max(1, min(int(max_hops), 4))
    driver = get_driver()
    cypher = (
        "MATCH (seed:Pericope) WHERE seed.id IN $ids "
        f"MATCH path = (seed)-[:CROSS_REFERENCES*1..{hops}]-(target:Pericope) "
        "WHERE NOT target.id IN $ids "
        "WITH target, min(length(path)) AS hop_distance "
        "RETURN target.id AS id, "
        "       labels(target) AS labels, "
        "       target.title AS title, "
        "       target.book_name AS book_name, "
        "       target.chapter_num AS chapter_num, "
        "       target.verse_range AS verse_range, "
        "       hop_distance "
        "ORDER BY hop_distance ASC "
        "LIMIT $limit"
    )
    async with driver.session() as session:
        result = await session.run(cypher, ids=pericope_ids, limit=limit)
        return [dict(record) for record in await result.data()]


async def get_event_related_content(entity_id: str, limit: int = 10) -> list[dict]:
    """Get content related to an Event entity through various relationships."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Event {entity_id: $entity_id})-[:MENTIONS]-(p)
            WHERE p:Pericope OR p:Chunk
            RETURN p.id AS id,
                   labels(p) AS labels,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_place_related_content(entity_id: str, limit: int = 10) -> list[dict]:
    """Get content related to a Place entity through MENTIONS relationships."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Place {entity_id: $entity_id})-[:MENTIONS]-(p)
            WHERE p:Pericope OR p:Chunk
            RETURN p.id AS id,
                   labels(p) AS labels,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def find_events_by_keyword(keyword: str, limit: int = 5) -> list[dict]:
    """Search Event nodes whose canonical_name or aliases contain the keyword."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Event)
            WHERE e.canonical_name CONTAINS $keyword
               OR any(a IN e.aliases WHERE a CONTAINS $keyword)
            RETURN e.entity_id AS entity_id,
                   e.canonical_name AS canonical_name,
                   e.description AS description,
                   e.mention_count AS mention_count
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """,
            keyword=keyword,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def find_related_entities(entity_id: str, limit: int = 10) -> list[dict]:
    """Find entities related to the given entity through shared pericopes."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {entity_id: $entity_id})-[:MENTIONS]-(p)-[:MENTIONS]-(other)
            WHERE other.entity_id <> $entity_id
            WITH other, count(p) AS shared_pericopes
            RETURN other.entity_id AS entity_id,
                   other.canonical_name AS canonical_name,
                   labels(other) AS labels,
                   shared_pericopes
            ORDER BY shared_pericopes DESC
            LIMIT $limit
            """,
            entity_id=entity_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]

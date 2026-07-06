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
    """Get pericopes related to an entity via MENTIONS relationships.

    Chunk-level anchors are remapped to their parent Pericope (via CONTAINS,
    431/431 chunks have one) so a candidate never appears twice — once as
    `exo:29:0` and once as chunk `exo:29:0:0` — which used to burn two top-k
    slots on identical content and hide chunk-only entities from
    pericope-level consumers.
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {entity_id: $entity_id})-[:MENTIONS]-(p0)
            WHERE p0:Pericope OR p0:Chunk
            OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
            WITH DISTINCT CASE WHEN p0:Chunk THEN coalesce(parent, p0) ELSE p0 END AS p
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


async def get_pericopes_for_entities_hub_aware(
    entity_ids: list[str],
    hub_threshold: int = 50,
    hub_cap: int = 3,
    normal_cap: int = 5,
) -> list[dict]:
    """Batch fetch pericopes for multiple entities via MENTIONS, with
    hub-aware cap to prevent topic-pollution from well-connected entities.

    For each entity_id, returns up to hub_cap pericopes if the entity has
    >= hub_threshold MENTIONS edges (e.g. 摩西 with 256 mentions), otherwise
    up to normal_cap. One Cypher call handles all entities.

    Returns flat list of records; caller groups by entity_id. Each record
    carries the entity's total_mentions so callers can mark hub provenance.
    """
    if not entity_ids:
        return []
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $entity_ids AS eid
            MATCH (e {entity_id: eid})
            OPTIONAL MATCH (e)-[:MENTIONS]-(p0)
            WHERE p0:Pericope OR p0:Chunk
            OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
            WITH eid, CASE WHEN p0:Chunk THEN coalesce(parent, p0) ELSE p0 END AS p
            WITH eid, collect(DISTINCT p) AS all_p
            WHERE size(all_p) > 0
            WITH eid, all_p, size(all_p) AS total,
                 CASE WHEN size(all_p) >= $hub_threshold
                      THEN $hub_cap ELSE $normal_cap END AS cap
            UNWIND all_p[0..cap] AS p
            RETURN eid AS entity_id,
                   total AS total_mentions,
                   p.id AS id,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            """,
            entity_ids=entity_ids,
            hub_threshold=hub_threshold,
            hub_cap=hub_cap,
            normal_cap=normal_cap,
        )
        return [dict(record) for record in await result.data()]


async def get_entities_shared_pericopes(entity_ids: list[str], limit: int = 10) -> list[dict]:
    """Find pericopes that mention multiple entities (shared context)."""
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e {entity_id: $first_id})-[:MENTIONS]-(p0)
            WHERE (p0:Pericope OR p0:Chunk)
              AND ALL(eid IN $other_ids WHERE
                EXISTS {
                  MATCH (e2 {entity_id: eid})-[:MENTIONS]-(p0)
                }
              )
            OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
            WITH DISTINCT CASE WHEN p0:Chunk THEN coalesce(parent, p0) ELSE p0 END AS p
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
    """Get cross-referenced pericopes for a given pericope, strongest first.

    Since the TSK import (~250k edges) the cross-ref graph is dense
    (~180 neighbours per pericope), so an unordered LIMIT would return an
    arbitrary subset. Order by community votes; hand-curated markdown edges
    carry no votes property and rank highest (999).
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (p:Pericope {id: $pericope_id})-[r:CROSS_REFERENCES]-(target:Pericope)
            WHERE target.id <> $pericope_id
            WITH target, max(coalesce(r.votes, 999)) AS votes
            RETURN target.id AS id,
                   labels(target) AS labels,
                   target.title AS title,
                   target.book_name AS book_name,
                   target.chapter_num AS chapter_num,
                   votes
            ORDER BY votes DESC
            LIMIT $limit
            """,
            pericope_id=pericope_id,
            limit=limit,
        )
        return [dict(record) for record in await result.data()]


async def get_cross_references_multi_hop(
    pericope_ids: list[str], max_hops: int = 2, limit: int = 30
) -> list[dict]:
    """Strongest cross-referenced neighbours for a set of seed pericopes.

    Since the TSK import (~250k edges, ~180 neighbours per pericope) the
    1-hop pool alone far exceeds any sensible limit, so ranking — not
    reachability — is what matters: order by how many seeds cite the target
    (seed_support), then by community votes (hand-curated markdown edges
    carry no votes property and rank highest). Hops beyond 1 are only walked
    as a fallback when the 1-hop pool cannot fill `limit` (sparse regions).
    `hop_distance` reflects the shortest path length back to a seed.
    """
    if not pericope_ids or max_hops < 1:
        return []
    driver = get_driver()
    one_hop_cypher = (
        "MATCH (seed:Pericope) WHERE seed.id IN $ids "
        "MATCH (seed)-[r:CROSS_REFERENCES]-(target:Pericope) "
        "WHERE NOT target.id IN $ids "
        "WITH target, count(DISTINCT seed) AS seed_support, "
        "     max(coalesce(r.votes, 999)) AS votes "
        "RETURN target.id AS id, "
        "       labels(target) AS labels, "
        "       target.title AS title, "
        "       target.book_name AS book_name, "
        "       target.chapter_num AS chapter_num, "
        "       target.verse_range AS verse_range, "
        "       1 AS hop_distance, "
        "       seed_support, votes "
        "ORDER BY seed_support DESC, votes DESC "
        "LIMIT $limit"
    )
    async with driver.session() as session:
        result = await session.run(one_hop_cypher, ids=pericope_ids, limit=limit)
        rows = [dict(record) for record in await result.data()]

    if len(rows) >= limit or max_hops < 2:
        return rows

    # Sparse fallback: expand remaining slots via multi-hop paths.
    hops = max(2, min(int(max_hops), 4))
    exclude = list(set(pericope_ids) | {r["id"] for r in rows})
    fallback_cypher = (
        "MATCH (seed:Pericope) WHERE seed.id IN $ids "
        f"MATCH path = (seed)-[:CROSS_REFERENCES*2..{hops}]-(target:Pericope) "
        "WHERE NOT target.id IN $exclude "
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
        result = await session.run(
            fallback_cypher, ids=pericope_ids, exclude=exclude,
            limit=limit - len(rows),
        )
        rows.extend(dict(record) for record in await result.data())
    return rows


async def get_event_related_content(entity_id: str, limit: int = 10) -> list[dict]:
    """Get content related to an Event entity through MENTIONS relationships.

    Sorted by book/chapter ascending so multi-chapter narrative events
    (e.g. 受難週 spanning Mat21-27) surface chronological start first,
    making the triumphal entry → 撒9:9 cross-ref reachable.
    """
    driver = get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:Event {entity_id: $entity_id})-[:MENTIONS]-(p0)
            WHERE p0:Pericope OR p0:Chunk
            OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
            WITH DISTINCT CASE WHEN p0:Chunk THEN coalesce(parent, p0) ELSE p0 END AS p
            RETURN p.id AS id,
                   labels(p) AS labels,
                   p.title AS title,
                   p.book_name AS book_name,
                   p.chapter_num AS chapter_num,
                   p.verse_range AS verse_range
            ORDER BY p.book_name ASC, p.chapter_num ASC, p.verse_range ASC
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
            MATCH (e:Place {entity_id: $entity_id})-[:MENTIONS]-(p0)
            WHERE p0:Pericope OR p0:Chunk
            OPTIONAL MATCH (parent:Pericope)-[:CONTAINS]->(p0)
            WITH DISTINCT CASE WHEN p0:Chunk THEN coalesce(parent, p0) ELSE p0 END AS p
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
                   e.aliases AS aliases,
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

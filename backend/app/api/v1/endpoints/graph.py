"""Graph API endpoints for Neo4j knowledge graph."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.core.neo4j_client import Neo4jClient
from app.models.orm import Entity, VerseEntity, Topic, VerseTopic, Verse, Book, Pericope
from app.models.schemas import (
    EntityBase,
    EntityDetail,
    EntitySearchResult,
    EntityType,
    GraphEdge,
    GraphNode,
    GraphResponse,
    GraphStats,
    PericopeParallelsResponse,
    TopicBase,
    TopicDetail,
    TopicRelatedResponse,
    TopicSearchResult,
    TopicType,
    VerseCrossReferencesResponse,
    VerseEntitiesResponse,
    VersePropheciesResponse,
)

router = APIRouter()


@router.get("/health")
async def graph_health_check():
    """Check Neo4j connectivity status."""
    health = await Neo4jClient.health_check()
    return health


@router.get("/stats", response_model=GraphStats)
async def get_graph_stats(db: DbSession):
    """Get statistics about the knowledge graph."""
    # Count entities by type
    entity_counts = {}
    for entity_type in ["PERSON", "PLACE", "GROUP", "EVENT"]:
        result = await db.execute(
            select(func.count(Entity.id)).where(Entity.type == entity_type)
        )
        entity_counts[entity_type.lower() + "s"] = result.scalar() or 0

    # Count topics
    topic_result = await db.execute(select(func.count(Topic.id)))
    topic_count = topic_result.scalar() or 0

    # Count relationships (from PostgreSQL)
    ve_result = await db.execute(select(func.count()).select_from(VerseEntity))
    vt_result = await db.execute(select(func.count()).select_from(VerseTopic))
    relationship_count = (ve_result.scalar() or 0) + (vt_result.scalar() or 0)

    return GraphStats(
        total_persons=entity_counts.get("persons", 0),
        total_places=entity_counts.get("places", 0),
        total_groups=entity_counts.get("groups", 0),
        total_events=entity_counts.get("events", 0),
        total_topics=topic_count,
        total_relationships=relationship_count,
    )


@router.get("/entity/search", response_model=EntitySearchResult)
async def search_entities(
    db: DbSession,
    name: str = Query(..., min_length=1, max_length=100, description="Entity name to search"),
    type: EntityType | None = Query(None, description="Filter by entity type"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results"),
):
    """Search entities by name.

    Args:
        name: Name to search (partial match)
        type: Optional entity type filter
        limit: Max results
    """
    query = select(Entity).where(Entity.name.ilike(f"%{name}%"))

    if type:
        query = query.where(Entity.type == type.value)

    query = query.limit(limit)

    result = await db.execute(query)
    entities = result.scalars().all()

    return EntitySearchResult(
        entities=[
            EntityBase(id=e.id, name=e.name, type=EntityType(e.type))
            for e in entities
        ],
        total=len(entities),
    )


@router.get("/entity/{entity_id}", response_model=EntityDetail)
async def get_entity(
    entity_id: int,
    db: DbSession,
):
    """Get entity details with relationships.

    Args:
        entity_id: Entity ID
    """
    # Get entity from PostgreSQL
    result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Get verse count
    verse_count_result = await db.execute(
        select(func.count(VerseEntity.verse_id)).where(VerseEntity.entity_id == entity_id)
    )
    verse_count = verse_count_result.scalar() or 0

    # Get related entities from Neo4j (if available)
    related_entities: list[EntityBase] = []
    if Neo4jClient.is_available():
        entity_label = entity.type.title()
        try:
            cypher = f"""
            MATCH (e:{entity_label} {{id: $entity_id}})
            MATCH (v:Verse)-[r1]->(e)
            MATCH (v)-[r2]->(related)
            WHERE related <> e AND type(r2) STARTS WITH 'MENTIONS_'
            WITH labels(related)[0] AS type, related.id AS id, related.name AS name
            RETURN DISTINCT type, id, name
            LIMIT 20
            """
            related = await Neo4jClient.execute_read(cypher, {"entity_id": entity_id})

            for r in related:
                try:
                    etype = EntityType(r["type"].upper())
                    related_entities.append(
                        EntityBase(id=r["id"], name=r["name"], type=etype)
                    )
                except ValueError:
                    pass  # Skip unknown types like "Topic"
        except Exception:
            pass  # Neo4j query failed, continue without related entities

    return EntityDetail(
        id=entity.id,
        name=entity.name,
        type=EntityType(entity.type),
        description=entity.description,
        related_verses_count=verse_count,
        related_entities=related_entities,
    )


@router.get("/topic/search", response_model=TopicSearchResult)
async def search_topics(
    db: DbSession,
    name: str = Query(..., min_length=1, max_length=100, description="Topic name to search"),
    type: TopicType | None = Query(None, description="Filter by topic type"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results"),
):
    """Search topics by name.

    Args:
        name: Name to search (partial match)
        type: Optional topic type filter
        limit: Max results
    """
    query = select(Topic).where(Topic.name.ilike(f"%{name}%"))

    if type:
        query = query.where(Topic.type == type.value)

    query = query.limit(limit)

    result = await db.execute(query)
    topics = result.scalars().all()

    return TopicSearchResult(
        topics=[
            TopicBase(id=t.id, name=t.name, type=TopicType(t.type))
            for t in topics
        ],
        total=len(topics),
    )


@router.get("/topic/{topic_id}", response_model=TopicDetail)
async def get_topic(
    topic_id: int,
    db: DbSession,
):
    """Get topic details with relationships.

    Args:
        topic_id: Topic ID
    """
    # Get topic from PostgreSQL
    result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = result.scalar_one_or_none()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Get verse count
    verse_count_result = await db.execute(
        select(func.count(VerseTopic.verse_id)).where(VerseTopic.topic_id == topic_id)
    )
    verse_count = verse_count_result.scalar() or 0

    # Get related topics from Neo4j (if available)
    related_topics: list[TopicBase] = []
    if Neo4jClient.is_available():
        try:
            cypher = """
            MATCH (t:Topic {id: $topic_id})
            MATCH (v:Verse)-[:MENTIONS_TOPIC]->(t)
            MATCH (v)-[:MENTIONS_TOPIC]->(related:Topic)
            WHERE related <> t
            WITH related, count(v) AS shared_verses
            ORDER BY shared_verses DESC
            RETURN related.id AS id, related.name AS name, related.type AS type
            LIMIT 10
            """
            related = await Neo4jClient.execute_read(cypher, {"topic_id": topic_id})

            for r in related:
                try:
                    ttype = TopicType(r["type"])
                    related_topics.append(
                        TopicBase(id=r["id"], name=r["name"], type=ttype)
                    )
                except ValueError:
                    pass
        except Exception:
            pass

    return TopicDetail(
        id=topic.id,
        name=topic.name,
        type=TopicType(topic.type),
        description=topic.description,
        related_verses_count=verse_count,
        related_topics=related_topics,
    )


@router.get("/verse/{verse_id}/entities", response_model=VerseEntitiesResponse)
async def get_verse_entities(
    verse_id: int,
    db: DbSession,
):
    """Get all entities for a verse.

    Args:
        verse_id: Verse ID
    """
    # Verify verse exists
    verse_result = await db.execute(select(Verse).where(Verse.id == verse_id))
    verse = verse_result.scalar_one_or_none()

    if not verse:
        raise HTTPException(status_code=404, detail="Verse not found")

    # Get book name for reference
    book_result = await db.execute(select(Book).where(Book.id == verse.book_id))
    book = book_result.scalar_one_or_none()
    reference = f"{book.name_zh} {verse.chapter}:{verse.verse}" if book else ""

    # Get entities
    ve_result = await db.execute(
        select(VerseEntity, Entity)
        .join(Entity, VerseEntity.entity_id == Entity.id)
        .where(VerseEntity.verse_id == verse_id)
    )
    verse_entities = ve_result.all()

    # Get topics
    vt_result = await db.execute(
        select(VerseTopic, Topic)
        .join(Topic, VerseTopic.topic_id == Topic.id)
        .where(VerseTopic.verse_id == verse_id)
    )
    verse_topics = vt_result.all()

    # Organize by type
    response = VerseEntitiesResponse(verse_id=verse_id, verse_reference=reference)

    for ve, entity in verse_entities:
        entity_base = EntityBase(
            id=entity.id,
            name=entity.name,
            type=EntityType(entity.type),
        )

        if entity.type == "PERSON":
            response.persons.append(entity_base)
        elif entity.type == "PLACE":
            response.places.append(entity_base)
        elif entity.type == "GROUP":
            response.groups.append(entity_base)
        elif entity.type == "EVENT":
            response.events.append(entity_base)

    for vt, topic in verse_topics:
        response.topics.append(
            TopicBase(id=topic.id, name=topic.name, type=TopicType(topic.type))
        )

    return response


@router.get("/relationships", response_model=GraphResponse)
async def get_relationships(
    entity_id: int = Query(..., description="Starting entity ID"),
    entity_type: EntityType = Query(..., description="Entity type"),
    depth: int = Query(2, ge=1, le=3, description="Traversal depth"),
    limit: int = Query(50, ge=1, le=200, description="Max nodes"),
):
    """Get relationship subgraph for visualization.

    Args:
        entity_id: Starting entity ID
        entity_type: Entity type (PERSON, PLACE, GROUP, EVENT)
        depth: Traversal depth (1-3)
        limit: Max nodes
    """
    if not Neo4jClient.is_available():
        raise HTTPException(
            status_code=503,
            detail="Neo4j is not available. Graph visualization requires Neo4j.",
        )

    label = entity_type.value.title()

    # Get subgraph
    cypher = f"""
    MATCH (start:{label} {{id: $entity_id}})
    CALL apoc.path.subgraphAll(start, {{
        maxLevel: $depth,
        relationshipFilter: 'MENTIONS_PERSON|MENTIONS_PLACE|MENTIONS_GROUP|MENTIONS_EVENT|MENTIONS_TOPIC|HAS_VERSE'
    }})
    YIELD nodes, relationships
    UNWIND nodes AS n
    WITH collect(DISTINCT {{
        id: toString(id(n)),
        label: coalesce(n.name, n.title, toString(n.id)),
        type: labels(n)[0],
        properties: properties(n)
    }}) AS nodeList, relationships
    UNWIND relationships AS r
    WITH nodeList, collect(DISTINCT {{
        source: toString(id(startNode(r))),
        target: toString(id(endNode(r))),
        type: type(r),
        properties: properties(r)
    }}) AS edgeList
    RETURN nodeList[0..$limit] AS nodes, edgeList AS edges
    """

    try:
        result = await Neo4jClient.execute_read(
            cypher,
            {"entity_id": entity_id, "depth": depth, "limit": limit},
        )

        if not result:
            # Fallback: simple query without APOC
            fallback_cypher = f"""
            MATCH (start:{label} {{id: $entity_id}})
            OPTIONAL MATCH (v:Verse)-[r1]->(start)
            OPTIONAL MATCH (v)-[r2]->(related)
            WHERE type(r2) STARTS WITH 'MENTIONS_'
            WITH start, collect(DISTINCT v) AS verses, collect(DISTINCT related) AS related_entities
            RETURN
                [start] + verses + related_entities AS nodes
            LIMIT 1
            """

            fallback_result = await Neo4jClient.execute_read(
                fallback_cypher, {"entity_id": entity_id}
            )

            if fallback_result and fallback_result[0].get("nodes"):
                nodes = []
                for n in fallback_result[0]["nodes"][:limit]:
                    if n:
                        nodes.append(GraphNode(
                            id=str(n.get("id", "")),
                            label=n.get("name") or n.get("title") or str(n.get("id", "")),
                            type=n.get("type", "Unknown"),
                            properties={},
                        ))
                return GraphResponse(nodes=nodes, edges=[])

            return GraphResponse(nodes=[], edges=[])

        data = result[0]
        return GraphResponse(
            nodes=[GraphNode(**n) for n in data.get("nodes", [])[:limit]],
            edges=[GraphEdge(**e) for e in data.get("edges", [])],
        )

    except Exception as e:
        # Return empty if query fails
        return GraphResponse(nodes=[], edges=[])


@router.get("/verse/{verse_id}/cross-references", response_model=VerseCrossReferencesResponse)
async def get_verse_cross_references(
    verse_id: int,
    db: DbSession,
):
    """Get cross-references for a verse.

    Returns QUOTES and ALLUDES_TO relationships in both directions.

    Args:
        verse_id: Verse ID
    """
    from app.models.schemas import (
        CrossReference,
        CrossReferenceType,
        VerseCrossReferencesResponse,
    )

    # Verify verse exists and get reference
    verse_result = await db.execute(select(Verse).where(Verse.id == verse_id))
    verse = verse_result.scalar_one_or_none()

    if not verse:
        raise HTTPException(status_code=404, detail="Verse not found")

    book_result = await db.execute(select(Book).where(Book.id == verse.book_id))
    book = book_result.scalar_one_or_none()
    verse_reference = f"{book.name_zh} {verse.chapter}:{verse.verse}" if book else ""

    response = VerseCrossReferencesResponse(
        verse_id=verse_id,
        verse_reference=verse_reference,
    )

    if not Neo4jClient.is_available():
        return response

    try:
        # Get QUOTES relationships (this verse quotes others)
        quotes_cypher = """
        MATCH (v:Verse {id: $verse_id})-[r:QUOTES]->(target:Verse)
        MATCH (b:Book {id: target.book_id})
        RETURN target.id AS id, b.name_zh AS book_name, target.chapter AS chapter,
               target.verse AS verse, coalesce(r.votes, 0) AS votes
        ORDER BY r.votes DESC
        LIMIT 50
        """
        quotes_result = await Neo4jClient.execute_read(quotes_cypher, {"verse_id": verse_id})
        for r in quotes_result:
            response.quotes.append(CrossReference(
                verse_id=r["id"],
                book_name=r["book_name"],
                chapter=r["chapter"],
                verse=r["verse"],
                reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                type=CrossReferenceType.QUOTES,
                votes=r["votes"],
            ))

        # Get quoted_by relationships (others quote this verse)
        quoted_by_cypher = """
        MATCH (source:Verse)-[r:QUOTES]->(v:Verse {id: $verse_id})
        MATCH (b:Book {id: source.book_id})
        RETURN source.id AS id, b.name_zh AS book_name, source.chapter AS chapter,
               source.verse AS verse, coalesce(r.votes, 0) AS votes
        ORDER BY r.votes DESC
        LIMIT 50
        """
        quoted_by_result = await Neo4jClient.execute_read(quoted_by_cypher, {"verse_id": verse_id})
        for r in quoted_by_result:
            response.quoted_by.append(CrossReference(
                verse_id=r["id"],
                book_name=r["book_name"],
                chapter=r["chapter"],
                verse=r["verse"],
                reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                type=CrossReferenceType.QUOTES,
                votes=r["votes"],
            ))

        # Get ALLUDES_TO relationships
        alludes_cypher = """
        MATCH (v:Verse {id: $verse_id})-[r:ALLUDES_TO]->(target:Verse)
        MATCH (b:Book {id: target.book_id})
        RETURN target.id AS id, b.name_zh AS book_name, target.chapter AS chapter,
               target.verse AS verse, coalesce(r.votes, 0) AS votes
        ORDER BY r.votes DESC
        LIMIT 50
        """
        alludes_result = await Neo4jClient.execute_read(alludes_cypher, {"verse_id": verse_id})
        for r in alludes_result:
            response.alludes_to.append(CrossReference(
                verse_id=r["id"],
                book_name=r["book_name"],
                chapter=r["chapter"],
                verse=r["verse"],
                reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                type=CrossReferenceType.ALLUDES_TO,
                votes=r["votes"],
            ))

        # Get alluded_by relationships
        alluded_by_cypher = """
        MATCH (source:Verse)-[r:ALLUDES_TO]->(v:Verse {id: $verse_id})
        MATCH (b:Book {id: source.book_id})
        RETURN source.id AS id, b.name_zh AS book_name, source.chapter AS chapter,
               source.verse AS verse, coalesce(r.votes, 0) AS votes
        ORDER BY r.votes DESC
        LIMIT 50
        """
        alluded_by_result = await Neo4jClient.execute_read(alluded_by_cypher, {"verse_id": verse_id})
        for r in alluded_by_result:
            response.alluded_by.append(CrossReference(
                verse_id=r["id"],
                book_name=r["book_name"],
                chapter=r["chapter"],
                verse=r["verse"],
                reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                type=CrossReferenceType.ALLUDES_TO,
                votes=r["votes"],
            ))

        response.total = (
            len(response.quotes) + len(response.quoted_by) +
            len(response.alludes_to) + len(response.alluded_by)
        )

    except Exception:
        pass

    return response


@router.get("/verse/{verse_id}/prophecies", response_model=VersePropheciesResponse)
async def get_verse_prophecies(
    verse_id: int,
    db: DbSession,
):
    """Get prophecy fulfillment links for a verse.

    Args:
        verse_id: Verse ID
    """
    from app.models.schemas import ProphecyLink, VersePropheciesResponse

    # Verify verse exists
    verse_result = await db.execute(select(Verse).where(Verse.id == verse_id))
    verse = verse_result.scalar_one_or_none()

    if not verse:
        raise HTTPException(status_code=404, detail="Verse not found")

    book_result = await db.execute(select(Book).where(Book.id == verse.book_id))
    book = book_result.scalar_one_or_none()
    verse_reference = f"{book.name_zh} {verse.chapter}:{verse.verse}" if book else ""
    is_ot = book.order_index <= 39 if book else False

    response = VersePropheciesResponse(
        verse_id=verse_id,
        verse_reference=verse_reference,
        is_ot=is_ot,
    )

    if not Neo4jClient.is_available():
        return response

    try:
        if is_ot:
            # OT verse - find NT fulfillments
            cypher = """
            MATCH (ot:Verse {id: $verse_id})-[r:PROPHECY_FULFILLED_IN]->(nt:Verse)
            MATCH (b:Book {id: nt.book_id})
            RETURN nt.id AS id, b.name_zh AS book_name, nt.chapter AS chapter,
                   nt.verse AS verse, nt.text AS text, coalesce(r.confidence, 0.5) AS confidence
            ORDER BY r.confidence DESC
            LIMIT 20
            """
            result = await Neo4jClient.execute_read(cypher, {"verse_id": verse_id})
            for r in result:
                response.fulfillments.append(ProphecyLink(
                    verse_id=r["id"],
                    book_name=r["book_name"],
                    chapter=r["chapter"],
                    verse=r["verse"],
                    reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                    text_excerpt=r["text"][:100] + "..." if r["text"] and len(r["text"]) > 100 else (r["text"] or ""),
                    confidence=r["confidence"],
                ))
        else:
            # NT verse - find OT prophecies
            cypher = """
            MATCH (ot:Verse)-[r:PROPHECY_FULFILLED_IN]->(nt:Verse {id: $verse_id})
            MATCH (b:Book {id: ot.book_id})
            RETURN ot.id AS id, b.name_zh AS book_name, ot.chapter AS chapter,
                   ot.verse AS verse, ot.text AS text, coalesce(r.confidence, 0.5) AS confidence
            ORDER BY r.confidence DESC
            LIMIT 20
            """
            result = await Neo4jClient.execute_read(cypher, {"verse_id": verse_id})
            for r in result:
                response.prophecies.append(ProphecyLink(
                    verse_id=r["id"],
                    book_name=r["book_name"],
                    chapter=r["chapter"],
                    verse=r["verse"],
                    reference=f"{r['book_name']} {r['chapter']}:{r['verse']}",
                    text_excerpt=r["text"][:100] + "..." if r["text"] and len(r["text"]) > 100 else (r["text"] or ""),
                    confidence=r["confidence"],
                ))

        response.total = len(response.fulfillments) + len(response.prophecies)

    except Exception:
        pass

    return response


@router.get("/pericope/{pericope_id}/parallels", response_model=PericopeParallelsResponse)
async def get_pericope_parallels(
    pericope_id: int,
    db: DbSession,
):
    """Get parallel passages for a pericope (Gospel parallels).

    Args:
        pericope_id: Pericope ID
    """
    from app.models.schemas import ParallelPassage, PericopeParallelsResponse

    # Verify pericope exists
    pericope_result = await db.execute(select(Pericope).where(Pericope.id == pericope_id))
    pericope = pericope_result.scalar_one_or_none()

    if not pericope:
        raise HTTPException(status_code=404, detail="Pericope not found")

    book_result = await db.execute(select(Book).where(Book.id == pericope.book_id))
    book = book_result.scalar_one_or_none()
    reference = f"{book.name_zh} {pericope.chapter_start}:{pericope.verse_start}" if book else ""
    if pericope.chapter_end != pericope.chapter_start or pericope.verse_end != pericope.verse_start:
        if pericope.chapter_end == pericope.chapter_start:
            reference += f"-{pericope.verse_end}"
        else:
            reference += f"-{pericope.chapter_end}:{pericope.verse_end}"

    response = PericopeParallelsResponse(
        pericope_id=pericope_id,
        pericope_title=pericope.title or "",
        pericope_reference=reference,
    )

    if not Neo4jClient.is_available():
        return response

    try:
        cypher = """
        MATCH (p1:Pericope {id: $pericope_id})-[r:PARALLEL_WITH]-(p2:Pericope)
        MATCH (b:Book {id: p2.book_id})
        RETURN p2.id AS id, b.name_zh AS book_name, p2.title AS title,
               p2.chapter_start AS cs, p2.verse_start AS vs,
               p2.chapter_end AS ce, p2.verse_end AS ve,
               coalesce(r.name_zh, r.name, '') AS parallel_name
        """
        result = await Neo4jClient.execute_read(cypher, {"pericope_id": pericope_id})

        for r in result:
            ref = f"{r['book_name']} {r['cs']}:{r['vs']}"
            if r['ce'] != r['cs'] or r['ve'] != r['vs']:
                if r['ce'] == r['cs']:
                    ref += f"-{r['ve']}"
                else:
                    ref += f"-{r['ce']}:{r['ve']}"

            response.parallels.append(ParallelPassage(
                pericope_id=r["id"],
                book_name=r["book_name"],
                title=r["title"] or "",
                reference=ref,
                parallel_name=r["parallel_name"],
            ))

        response.total = len(response.parallels)

    except Exception:
        pass

    return response


@router.get("/topic/{topic_id}/related", response_model=TopicRelatedResponse)
async def get_related_topics(
    topic_id: int,
    db: DbSession,
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
):
    """Get topics related to a given topic.

    Args:
        topic_id: Topic ID
        limit: Maximum number of related topics to return
    """
    from app.models.schemas import RelatedTopic, TopicRelatedResponse

    # Verify topic exists
    topic_result = await db.execute(select(Topic).where(Topic.id == topic_id))
    topic = topic_result.scalar_one_or_none()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    response = TopicRelatedResponse(
        topic_id=topic_id,
        topic_name=topic.name,
    )

    if not Neo4jClient.is_available():
        return response

    try:
        cypher = """
        MATCH (t1:Topic {id: $topic_id})-[r:RELATED_TO]-(t2:Topic)
        RETURN t2.id AS id, t2.name AS name, t2.type AS type,
               r.weight AS weight, r.co_occurrence AS co_occurrence
        ORDER BY r.weight DESC
        LIMIT $limit
        """
        result = await Neo4jClient.execute_read(
            cypher, {"topic_id": topic_id, "limit": limit}
        )

        for r in result:
            try:
                topic_type = TopicType(r["type"]) if r["type"] else TopicType.OTHER
            except ValueError:
                topic_type = TopicType.OTHER

            response.related.append(RelatedTopic(
                id=r["id"],
                name=r["name"],
                type=topic_type,
                weight=r["weight"] or 0.0,
                co_occurrence=r["co_occurrence"] or 0,
            ))

        response.total = len(response.related)

    except Exception:
        pass

    return response

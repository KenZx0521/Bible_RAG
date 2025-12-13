"""Build Neo4j knowledge graph from PostgreSQL data.

This script creates the Neo4j knowledge graph by:
1. Loading data from PostgreSQL (books, chapters, pericopes, verses, entities, topics)
2. Creating nodes in Neo4j
3. Creating relationships
4. Creating indexes for performance

Usage:
    cd backend
    python -m scripts.build_graph
    python -m scripts.build_graph --clear  # Clear existing graph first
    python -m scripts.build_graph --indexes-only  # Only create indexes
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.neo4j_client import Neo4jClient
from app.models.orm import Book, Chapter, Pericope, Verse, Entity, VerseEntity, Topic, VerseTopic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Batch sizes for bulk operations
NODE_BATCH_SIZE = 500
RELATIONSHIP_BATCH_SIZE = 1000


class GraphBuilder:
    """Build Neo4j knowledge graph from PostgreSQL data."""

    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def build_full_graph(self, clear_existing: bool = True) -> dict:
        """Build the complete knowledge graph.

        Args:
            clear_existing: Whether to clear existing graph first

        Returns:
            Statistics dict
        """
        stats = {
            "books": 0,
            "chapters": 0,
            "pericopes": 0,
            "verses": 0,
            "persons": 0,
            "places": 0,
            "groups": 0,
            "events": 0,
            "topics": 0,
            "relationships": 0,
        }

        if clear_existing:
            logger.info("Clearing existing graph...")
            await self._clear_graph()

        # Create structural nodes
        logger.info("Creating Book nodes...")
        stats["books"] = await self._create_book_nodes()

        logger.info("Creating Chapter nodes...")
        stats["chapters"] = await self._create_chapter_nodes()

        logger.info("Creating Pericope nodes...")
        stats["pericopes"] = await self._create_pericope_nodes()

        logger.info("Creating Verse nodes...")
        stats["verses"] = await self._create_verse_nodes()

        # Create entity nodes
        logger.info("Creating Entity nodes...")
        entity_counts = await self._create_entity_nodes()
        stats.update(entity_counts)

        logger.info("Creating Topic nodes...")
        stats["topics"] = await self._create_topic_nodes()

        # Create relationships
        logger.info("Creating structural relationships...")
        stats["relationships"] += await self._create_structural_relationships()

        logger.info("Creating entity mention relationships...")
        stats["relationships"] += await self._create_entity_relationships()

        logger.info("Creating topic mention relationships...")
        stats["relationships"] += await self._create_topic_relationships()

        # Create indexes
        logger.info("Creating indexes...")
        await self._create_indexes()

        logger.info(f"Graph building complete: {stats}")
        return stats

    async def _clear_graph(self) -> None:
        """Clear all nodes and relationships."""
        await Neo4jClient.execute_write("MATCH (n) DETACH DELETE n")

    async def _create_book_nodes(self) -> int:
        """Create Book nodes."""
        result = await self.pg_session.execute(select(Book))
        books = result.scalars().all()

        data = [
            {
                "id": b.id,
                "name_zh": b.name_zh,
                "abbrev_zh": b.abbrev_zh,
                "testament": b.testament,
                "order_index": b.order_index,
            }
            for b in books
        ]

        if data:
            await Neo4jClient.execute_write(
                """
                UNWIND $books AS b
                CREATE (:Book {
                    id: b.id,
                    name_zh: b.name_zh,
                    abbrev_zh: b.abbrev_zh,
                    testament: b.testament,
                    order_index: b.order_index
                })
                """,
                {"books": data}
            )

        return len(data)

    async def _create_chapter_nodes(self) -> int:
        """Create Chapter nodes."""
        result = await self.pg_session.execute(select(Chapter))
        chapters = result.scalars().all()

        data = [
            {"id": c.id, "book_id": c.book_id, "number": c.number}
            for c in chapters
        ]

        # Batch create
        for i in range(0, len(data), NODE_BATCH_SIZE):
            batch = data[i:i + NODE_BATCH_SIZE]
            await Neo4jClient.execute_write(
                """
                UNWIND $chapters AS c
                CREATE (:Chapter {id: c.id, book_id: c.book_id, number: c.number})
                """,
                {"chapters": batch}
            )

        return len(data)

    async def _create_pericope_nodes(self) -> int:
        """Create Pericope nodes."""
        result = await self.pg_session.execute(select(Pericope))
        pericopes = result.scalars().all()

        data = [
            {
                "id": p.id,
                "book_id": p.book_id,
                "title": p.title,
                "chapter_start": p.chapter_start,
                "verse_start": p.verse_start,
                "chapter_end": p.chapter_end,
                "verse_end": p.verse_end,
            }
            for p in pericopes
        ]

        # Batch create
        for i in range(0, len(data), NODE_BATCH_SIZE):
            batch = data[i:i + NODE_BATCH_SIZE]
            await Neo4jClient.execute_write(
                """
                UNWIND $pericopes AS p
                CREATE (:Pericope {
                    id: p.id,
                    book_id: p.book_id,
                    title: p.title,
                    chapter_start: p.chapter_start,
                    verse_start: p.verse_start,
                    chapter_end: p.chapter_end,
                    verse_end: p.verse_end
                })
                """,
                {"pericopes": batch}
            )

        return len(data)

    async def _create_verse_nodes(self) -> int:
        """Create Verse nodes."""
        # Get total count
        count_result = await self.pg_session.execute(select(func.count(Verse.id)))
        total = count_result.scalar() or 0

        created = 0
        offset = 0

        while offset < total:
            result = await self.pg_session.execute(
                select(Verse)
                .order_by(Verse.id)
                .offset(offset)
                .limit(NODE_BATCH_SIZE)
            )
            verses = result.scalars().all()

            if not verses:
                break

            data = [
                {
                    "id": v.id,
                    "book_id": v.book_id,
                    "chapter": v.chapter,
                    "verse": v.verse,
                    "text": v.text[:500] if v.text else "",  # Truncate for Neo4j
                    "pericope_id": v.pericope_id,
                }
                for v in verses
            ]

            await Neo4jClient.execute_write(
                """
                UNWIND $verses AS v
                CREATE (:Verse {
                    id: v.id,
                    book_id: v.book_id,
                    chapter: v.chapter,
                    verse: v.verse,
                    text: v.text,
                    pericope_id: v.pericope_id
                })
                """,
                {"verses": data}
            )

            created += len(data)
            offset += NODE_BATCH_SIZE
            logger.info(f"  Created {created}/{total} verse nodes...")

        return created

    async def _create_entity_nodes(self) -> dict[str, int]:
        """Create Entity nodes (Person, Place, Group, Event)."""
        result = await self.pg_session.execute(select(Entity))
        entities = result.scalars().all()

        counts = {"persons": 0, "places": 0, "groups": 0, "events": 0}

        # Group by type
        by_type: dict[str, list] = {
            "PERSON": [],
            "PLACE": [],
            "GROUP": [],
            "EVENT": [],
        }

        for e in entities:
            if e.type in by_type:
                by_type[e.type].append({
                    "id": e.id,
                    "name": e.name,
                    "description": e.description or "",
                })

        # Create nodes by type
        type_map = {
            "PERSON": ("Person", "persons"),
            "PLACE": ("Place", "places"),
            "GROUP": ("Group", "groups"),
            "EVENT": ("Event", "events"),
        }

        for entity_type, (label, count_key) in type_map.items():
            data = by_type[entity_type]
            if data:
                await Neo4jClient.execute_write(
                    f"""
                    UNWIND $entities AS e
                    CREATE (:{label} {{id: e.id, name: e.name, description: e.description}})
                    """,
                    {"entities": data}
                )
                counts[count_key] = len(data)

        return counts

    async def _create_topic_nodes(self) -> int:
        """Create Topic nodes."""
        result = await self.pg_session.execute(select(Topic))
        topics = result.scalars().all()

        data = [
            {
                "id": t.id,
                "name": t.name,
                "type": t.type,
                "description": t.description or "",
            }
            for t in topics
        ]

        if data:
            await Neo4jClient.execute_write(
                """
                UNWIND $topics AS t
                CREATE (:Topic {id: t.id, name: t.name, type: t.type, description: t.description})
                """,
                {"topics": data}
            )

        return len(data)

    async def _create_structural_relationships(self) -> int:
        """Create structural relationships (Book->Chapter, Pericope->Verse)."""
        count = 0

        # Book -> Chapter
        await Neo4jClient.execute_write(
            """
            MATCH (b:Book), (c:Chapter)
            WHERE b.id = c.book_id
            CREATE (b)-[:HAS_CHAPTER]->(c)
            """
        )
        result = await Neo4jClient.execute_read(
            "MATCH ()-[r:HAS_CHAPTER]->() RETURN count(r) as count"
        )
        count += result[0]["count"] if result else 0

        # Book -> Pericope
        await Neo4jClient.execute_write(
            """
            MATCH (b:Book), (p:Pericope)
            WHERE b.id = p.book_id
            CREATE (b)-[:HAS_PERICOPE]->(p)
            """
        )
        result = await Neo4jClient.execute_read(
            "MATCH ()-[r:HAS_PERICOPE]->() RETURN count(r) as count"
        )
        count += result[0]["count"] if result else 0

        # Pericope -> Verse
        await Neo4jClient.execute_write(
            """
            MATCH (p:Pericope), (v:Verse)
            WHERE p.id = v.pericope_id
            CREATE (p)-[:HAS_VERSE]->(v)
            """
        )
        result = await Neo4jClient.execute_read(
            "MATCH ()-[r:HAS_VERSE]->() RETURN count(r) as count"
        )
        count += result[0]["count"] if result else 0

        return count

    async def _create_entity_relationships(self) -> int:
        """Create entity mention relationships (Verse->Entity)."""
        # Get total count
        count_result = await self.pg_session.execute(
            select(func.count()).select_from(VerseEntity)
        )
        total = count_result.scalar() or 0

        if total == 0:
            logger.info("  No entity relationships to create")
            return 0

        created = 0
        offset = 0

        while offset < total:
            result = await self.pg_session.execute(
                select(VerseEntity, Entity.type)
                .join(Entity, VerseEntity.entity_id == Entity.id)
                .order_by(VerseEntity.verse_id)
                .offset(offset)
                .limit(RELATIONSHIP_BATCH_SIZE)
            )
            rows = result.all()

            if not rows:
                break

            # Group by entity type
            by_type: dict[str, list] = {
                "PERSON": [],
                "PLACE": [],
                "GROUP": [],
                "EVENT": [],
            }

            for ve, entity_type in rows:
                if entity_type in by_type:
                    by_type[entity_type].append({
                        "verse_id": ve.verse_id,
                        "entity_id": ve.entity_id,
                        "role": ve.role or "",
                    })

            # Create relationships by type
            type_map = {
                "PERSON": ("Person", "MENTIONS_PERSON"),
                "PLACE": ("Place", "MENTIONS_PLACE"),
                "GROUP": ("Group", "MENTIONS_GROUP"),
                "EVENT": ("Event", "MENTIONS_EVENT"),
            }

            for entity_type, (label, rel_type) in type_map.items():
                data = by_type[entity_type]
                if data:
                    await Neo4jClient.execute_write(
                        f"""
                        UNWIND $data AS d
                        MATCH (v:Verse {{id: d.verse_id}})
                        MATCH (e:{label} {{id: d.entity_id}})
                        CREATE (v)-[:{rel_type} {{role: d.role}}]->(e)
                        """,
                        {"data": data}
                    )

            created += len(rows)
            offset += RELATIONSHIP_BATCH_SIZE
            logger.info(f"  Created {created}/{total} entity relationships...")

        return created

    async def _create_topic_relationships(self) -> int:
        """Create topic mention relationships (Verse->Topic)."""
        # Get total count
        count_result = await self.pg_session.execute(
            select(func.count()).select_from(VerseTopic)
        )
        total = count_result.scalar() or 0

        if total == 0:
            logger.info("  No topic relationships to create")
            return 0

        created = 0
        offset = 0

        while offset < total:
            result = await self.pg_session.execute(
                select(VerseTopic)
                .order_by(VerseTopic.verse_id)
                .offset(offset)
                .limit(RELATIONSHIP_BATCH_SIZE)
            )
            verse_topics = result.scalars().all()

            if not verse_topics:
                break

            data = [
                {
                    "verse_id": vt.verse_id,
                    "topic_id": vt.topic_id,
                    "weight": vt.weight,
                }
                for vt in verse_topics
            ]

            await Neo4jClient.execute_write(
                """
                UNWIND $data AS d
                MATCH (v:Verse {id: d.verse_id})
                MATCH (t:Topic {id: d.topic_id})
                CREATE (v)-[:MENTIONS_TOPIC {weight: d.weight}]->(t)
                """,
                {"data": data}
            )

            created += len(data)
            offset += RELATIONSHIP_BATCH_SIZE
            logger.info(f"  Created {created}/{total} topic relationships...")

        return created

    async def _create_indexes(self) -> None:
        """Create Neo4j indexes for performance."""
        indexes = [
            # Node property indexes
            "CREATE INDEX book_id IF NOT EXISTS FOR (b:Book) ON (b.id)",
            "CREATE INDEX book_name IF NOT EXISTS FOR (b:Book) ON (b.name_zh)",
            "CREATE INDEX chapter_id IF NOT EXISTS FOR (c:Chapter) ON (c.id)",
            "CREATE INDEX chapter_book IF NOT EXISTS FOR (c:Chapter) ON (c.book_id)",
            "CREATE INDEX pericope_id IF NOT EXISTS FOR (p:Pericope) ON (p.id)",
            "CREATE INDEX pericope_book IF NOT EXISTS FOR (p:Pericope) ON (p.book_id)",
            "CREATE INDEX verse_id IF NOT EXISTS FOR (v:Verse) ON (v.id)",
            "CREATE INDEX verse_book IF NOT EXISTS FOR (v:Verse) ON (v.book_id)",
            "CREATE INDEX verse_pericope IF NOT EXISTS FOR (v:Verse) ON (v.pericope_id)",
            "CREATE INDEX person_id IF NOT EXISTS FOR (p:Person) ON (p.id)",
            "CREATE INDEX person_name IF NOT EXISTS FOR (p:Person) ON (p.name)",
            "CREATE INDEX place_id IF NOT EXISTS FOR (p:Place) ON (p.id)",
            "CREATE INDEX place_name IF NOT EXISTS FOR (p:Place) ON (p.name)",
            "CREATE INDEX group_id IF NOT EXISTS FOR (g:Group) ON (g.id)",
            "CREATE INDEX group_name IF NOT EXISTS FOR (g:Group) ON (g.name)",
            "CREATE INDEX event_id IF NOT EXISTS FOR (e:Event) ON (e.id)",
            "CREATE INDEX event_name IF NOT EXISTS FOR (e:Event) ON (e.name)",
            "CREATE INDEX topic_id IF NOT EXISTS FOR (t:Topic) ON (t.id)",
            "CREATE INDEX topic_name IF NOT EXISTS FOR (t:Topic) ON (t.name)",
            "CREATE INDEX topic_type IF NOT EXISTS FOR (t:Topic) ON (t.type)",
        ]

        # Full-text indexes for search
        fulltext_indexes = [
            "CREATE FULLTEXT INDEX person_name_ft IF NOT EXISTS FOR (p:Person) ON EACH [p.name]",
            "CREATE FULLTEXT INDEX place_name_ft IF NOT EXISTS FOR (p:Place) ON EACH [p.name]",
            "CREATE FULLTEXT INDEX group_name_ft IF NOT EXISTS FOR (g:Group) ON EACH [g.name]",
            "CREATE FULLTEXT INDEX event_name_ft IF NOT EXISTS FOR (e:Event) ON EACH [e.name]",
            "CREATE FULLTEXT INDEX topic_name_ft IF NOT EXISTS FOR (t:Topic) ON EACH [t.name]",
        ]

        for index in indexes:
            try:
                await Neo4jClient.execute_write(index)
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")

        for index in fulltext_indexes:
            try:
                await Neo4jClient.execute_write(index)
            except Exception as e:
                logger.warning(f"Fulltext index creation warning: {e}")


async def main(
    clear: bool = True,
    indexes_only: bool = False,
) -> None:
    """Main entry point.

    Args:
        clear: Whether to clear existing graph
        indexes_only: Only create indexes (skip node/relationship creation)
    """
    # Initialize Neo4j
    await Neo4jClient.initialize()

    if not Neo4jClient.is_available():
        logger.error("Neo4j is not available. Please ensure Neo4j is running.")
        logger.info("Start Neo4j with: docker compose --profile full up -d neo4j")
        return

    # Create PostgreSQL session
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with async_session() as session:
            builder = GraphBuilder(session)

            if indexes_only:
                logger.info("Creating indexes only...")
                await builder._create_indexes()
            else:
                stats = await builder.build_full_graph(clear_existing=clear)
                print("\nGraph Building Statistics:")
                for key, value in stats.items():
                    print(f"  {key}: {value}")

    finally:
        await engine.dispose()
        await Neo4jClient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build Neo4j knowledge graph from PostgreSQL data"
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing graph (append mode)",
    )
    parser.add_argument(
        "--indexes-only",
        action="store_true",
        help="Only create indexes, skip node/relationship creation",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(main(
        clear=not args.no_clear,
        indexes_only=args.indexes_only,
    ))

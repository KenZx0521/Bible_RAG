"""Compute topic co-occurrence relationships.

This script analyzes verse_topics data to find topics that frequently
co-occur and creates RELATED_TO relationships in Neo4j.

Usage:
    cd backend
    python -m scripts.compute_topic_relations
    python -m scripts.compute_topic_relations --min-cooccurrence 10
    python -m scripts.compute_topic_relations --min-weight 0.2
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.neo4j_client import Neo4jClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Batch size for Neo4j operations
BATCH_SIZE = 500


class TopicRelationComputer:
    """Compute and create topic co-occurrence relationships."""

    def __init__(
        self,
        session: AsyncSession,
        min_cooccurrence: int = 5,
        min_weight: float = 0.1,
    ):
        self.session = session
        self.min_cooccurrence = min_cooccurrence
        self.min_weight = min_weight

    async def compute_relations(self) -> dict[str, int]:
        """Compute topic relations and create Neo4j relationships.

        Returns:
            Statistics dict
        """
        stats = {
            "topic_pairs_found": 0,
            "relationships_created": 0,
            "filtered_by_weight": 0,
        }

        logger.info("Computing topic co-occurrences from PostgreSQL...")

        # Query for topic co-occurrences
        query = text("""
            WITH topic_verse_counts AS (
                SELECT topic_id, COUNT(DISTINCT verse_id) as verse_count
                FROM verse_topics
                GROUP BY topic_id
            ),
            cooccurrences AS (
                SELECT
                    vt1.topic_id AS topic1_id,
                    vt2.topic_id AS topic2_id,
                    COUNT(DISTINCT vt1.verse_id) AS co_occurrence
                FROM verse_topics vt1
                JOIN verse_topics vt2 ON vt1.verse_id = vt2.verse_id
                WHERE vt1.topic_id < vt2.topic_id
                GROUP BY vt1.topic_id, vt2.topic_id
                HAVING COUNT(DISTINCT vt1.verse_id) >= :min_cooccurrence
            )
            SELECT
                c.topic1_id,
                c.topic2_id,
                c.co_occurrence,
                t1.verse_count AS topic1_verses,
                t2.verse_count AS topic2_verses,
                t1_info.name AS topic1_name,
                t2_info.name AS topic2_name
            FROM cooccurrences c
            JOIN topic_verse_counts t1 ON c.topic1_id = t1.topic_id
            JOIN topic_verse_counts t2 ON c.topic2_id = t2.topic_id
            JOIN topics t1_info ON c.topic1_id = t1_info.id
            JOIN topics t2_info ON c.topic2_id = t2_info.id
            ORDER BY c.co_occurrence DESC
        """)

        result = await self.session.execute(
            query, {"min_cooccurrence": self.min_cooccurrence}
        )
        rows = result.fetchall()

        logger.info(f"Found {len(rows)} topic pairs with co-occurrence >= {self.min_cooccurrence}")
        stats["topic_pairs_found"] = len(rows)

        # Calculate Jaccard similarity and filter
        relations = []
        for row in rows:
            # Jaccard similarity: intersection / union
            intersection = row.co_occurrence
            union = row.topic1_verses + row.topic2_verses - intersection
            weight = intersection / union if union > 0 else 0

            if weight >= self.min_weight:
                relations.append({
                    "topic1_id": row.topic1_id,
                    "topic2_id": row.topic2_id,
                    "co_occurrence": row.co_occurrence,
                    "weight": round(weight, 4),
                    "topic1_name": row.topic1_name,
                    "topic2_name": row.topic2_name,
                })
            else:
                stats["filtered_by_weight"] += 1

        logger.info(f"After weight filtering (>= {self.min_weight}): {len(relations)} pairs")

        if not relations:
            logger.warning("No topic relations to create")
            return stats

        # Create Neo4j relationships in batches
        logger.info("Creating Neo4j RELATED_TO relationships...")

        for i in range(0, len(relations), BATCH_SIZE):
            batch = relations[i:i + BATCH_SIZE]
            await self._create_relationships_batch(batch)
            stats["relationships_created"] += len(batch)
            logger.info(f"  Created {stats['relationships_created']}/{len(relations)} relationships...")

        return stats

    async def _create_relationships_batch(self, relations: list[dict]) -> None:
        """Create a batch of RELATED_TO relationships.

        Args:
            relations: List of relation dicts
        """
        cypher = """
        UNWIND $relations AS rel
        MATCH (t1:Topic {id: rel.topic1_id})
        MATCH (t2:Topic {id: rel.topic2_id})
        MERGE (t1)-[r:RELATED_TO]->(t2)
        SET r.weight = rel.weight,
            r.co_occurrence = rel.co_occurrence,
            r.source = 'computed'
        """

        await Neo4jClient.execute_write(cypher, {"relations": relations})

    async def clear_existing_relations(self) -> int:
        """Clear existing RELATED_TO relationships.

        Returns:
            Number of deleted relationships
        """
        # First count
        count_result = await Neo4jClient.execute_read(
            "MATCH ()-[r:RELATED_TO]->() RETURN count(r) as count"
        )
        count = count_result[0]["count"] if count_result else 0

        if count > 0:
            logger.info(f"Clearing {count} existing RELATED_TO relationships...")
            await Neo4jClient.execute_write(
                "MATCH ()-[r:RELATED_TO]->() DELETE r"
            )

        return count


async def main(
    min_cooccurrence: int = 5,
    min_weight: float = 0.1,
    clear_existing: bool = True,
) -> None:
    """Main entry point.

    Args:
        min_cooccurrence: Minimum co-occurrence count threshold
        min_weight: Minimum Jaccard weight threshold
        clear_existing: Whether to clear existing relationships first
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
            computer = TopicRelationComputer(
                session=session,
                min_cooccurrence=min_cooccurrence,
                min_weight=min_weight,
            )

            if clear_existing:
                deleted = await computer.clear_existing_relations()
                if deleted > 0:
                    logger.info(f"Cleared {deleted} existing relationships")

            stats = await computer.compute_relations()

            print("\nTopic Relation Statistics:")
            for key, value in stats.items():
                print(f"  {key}: {value}")

    finally:
        await engine.dispose()
        await Neo4jClient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compute topic co-occurrence relationships"
    )
    parser.add_argument(
        "--min-cooccurrence",
        type=int,
        default=5,
        help="Minimum co-occurrence count (default: 5)",
    )
    parser.add_argument(
        "--min-weight",
        type=float,
        default=0.1,
        help="Minimum Jaccard weight (default: 0.1)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing relationships",
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
        min_cooccurrence=args.min_cooccurrence,
        min_weight=args.min_weight,
        clear_existing=not args.no_clear,
    ))

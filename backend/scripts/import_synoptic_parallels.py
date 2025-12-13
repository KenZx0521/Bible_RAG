"""Import synoptic parallel passages and create Neo4j relationships.

This script imports synoptic gospel parallel passages from JSON and creates
PARALLEL_WITH relationships between pericopes in Neo4j.

Usage:
    cd backend
    python -m scripts.import_synoptic_parallels
    python -m scripts.import_synoptic_parallels --clear
    python -m scripts.import_synoptic_parallels --data-file custom.json -v
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.neo4j_client import Neo4jClient
from app.models.orm import Book, Pericope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SynopticParallelImporter:
    """Import synoptic gospel parallel passages to Neo4j."""

    # Book name mapping (Chinese to book_id lookup cache)
    BOOK_NAMES = {
        "馬太福音": "Matthew",
        "馬可福音": "Mark",
        "路加福音": "Luke",
    }

    def __init__(self, pg_session: AsyncSession):
        """Initialize the importer.

        Args:
            pg_session: PostgreSQL async session
        """
        self.pg_session = pg_session
        self.book_id_cache: dict[str, int] = {}
        self.stats = {
            "parallels_processed": 0,
            "pericopes_matched": 0,
            "relationships_created": 0,
            "skipped": 0,
            "errors": 0,
        }

    async def load_book_ids(self) -> None:
        """Load book IDs into cache for faster lookups."""
        logger.info("Loading book IDs...")
        result = await self.pg_session.execute(
            select(Book.id, Book.name_zh).where(
                Book.name_zh.in_(list(self.BOOK_NAMES.keys()))
            )
        )
        books = result.all()

        for book_id, name_zh in books:
            self.book_id_cache[name_zh] = book_id

        logger.info(f"Loaded {len(self.book_id_cache)} book IDs: {self.book_id_cache}")

    async def find_matching_pericope(
        self,
        book_name_zh: str,
        chapter: int,
        verse_start: int,
        verse_end: int,
    ) -> Pericope | None:
        """Find a pericope that overlaps with the given chapter/verse range.

        Args:
            book_name_zh: Chinese book name (e.g., "馬太福音")
            chapter: Chapter number
            verse_start: Starting verse number
            verse_end: Ending verse number

        Returns:
            Matching Pericope or None if not found
        """
        book_id = self.book_id_cache.get(book_name_zh)
        if not book_id:
            logger.warning(f"Book not found: {book_name_zh}")
            return None

        # Find pericopes that overlap with the given range
        # A pericope overlaps if:
        # 1. It's in the same book
        # 2. Its chapter range intersects with the target chapter
        # 3. If chapters match, verse ranges should overlap
        query = select(Pericope).where(
            and_(
                Pericope.book_id == book_id,
                # Chapter overlap: pericope.start <= target.end AND pericope.end >= target.start
                Pericope.chapter_start <= chapter,
                Pericope.chapter_end >= chapter,
            )
        )

        result = await self.pg_session.execute(query)
        pericopes = result.scalars().all()

        # Further filter by verse overlap if same chapter
        candidates = []
        for p in pericopes:
            # If multi-chapter pericope, it definitely overlaps
            if p.chapter_start < chapter < p.chapter_end:
                candidates.append(p)
            # If pericope starts in this chapter
            elif p.chapter_start == chapter:
                # Check verse overlap
                if p.verse_start <= verse_end:
                    candidates.append(p)
            # If pericope ends in this chapter
            elif p.chapter_end == chapter:
                # Check verse overlap
                if p.verse_end >= verse_start:
                    candidates.append(p)

        if not candidates:
            logger.debug(
                f"No pericope found for {book_name_zh} {chapter}:{verse_start}-{verse_end}"
            )
            return None

        # Prefer the pericope with the best overlap
        # Simple heuristic: choose the one that starts closest to verse_start
        candidates.sort(key=lambda p: abs(p.verse_start - verse_start))
        return candidates[0]

    async def create_parallel_relationships(
        self,
        pericope_ids: list[int],
        parallel_id: int,
        name_zh: str,
        name_en: str,
    ) -> int:
        """Create bidirectional PARALLEL_WITH relationships between pericopes.

        Args:
            pericope_ids: List of pericope IDs to link
            parallel_id: Parallel passage ID from JSON
            name_zh: Chinese name of the parallel
            name_en: English name of the parallel

        Returns:
            Number of relationships created
        """
        if len(pericope_ids) < 2:
            logger.warning(f"Need at least 2 pericopes for parallel {parallel_id}, got {len(pericope_ids)}")
            return 0

        # Create bidirectional relationships between all pairs
        # For n pericopes, this creates n*(n-1) relationships (bidirectional complete graph)
        created = 0
        for i, pericope_id_1 in enumerate(pericope_ids):
            for pericope_id_2 in pericope_ids[i + 1 :]:
                # Create relationship in both directions
                await Neo4jClient.execute_write(
                    """
                    MATCH (p1:Pericope {id: $id1})
                    MATCH (p2:Pericope {id: $id2})
                    MERGE (p1)-[:PARALLEL_WITH {
                        parallel_id: $parallel_id,
                        name_zh: $name_zh,
                        name_en: $name_en,
                        source: $source
                    }]->(p2)
                    MERGE (p2)-[:PARALLEL_WITH {
                        parallel_id: $parallel_id,
                        name_zh: $name_zh,
                        name_en: $name_en,
                        source: $source
                    }]->(p1)
                    """,
                    {
                        "id1": pericope_id_1,
                        "id2": pericope_id_2,
                        "parallel_id": parallel_id,
                        "name_zh": name_zh,
                        "name_en": name_en,
                        "source": "manual",
                    },
                )
                created += 2  # Bidirectional

        return created

    async def import_parallels(self, data_file: Path, verbose: bool = False) -> dict[str, int]:
        """Import parallel passages from JSON file.

        Args:
            data_file: Path to JSON file containing parallel data
            verbose: Enable verbose logging

        Returns:
            Statistics dictionary
        """
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        # Load JSON data
        logger.info(f"Loading parallel data from {data_file}...")
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"Data file not found: {data_file}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in data file: {e}")
            raise

        parallels = data.get("parallels", [])
        logger.info(f"Found {len(parallels)} parallel passages")

        # Load book IDs
        await self.load_book_ids()

        # Process each parallel
        for parallel in parallels:
            parallel_id = parallel["id"]
            name_zh = parallel["name_zh"]
            name_en = parallel["name_en"]

            logger.info(f"Processing parallel {parallel_id}: {name_zh} ({name_en})")
            self.stats["parallels_processed"] += 1

            # Find matching pericopes for each gospel
            pericope_ids = []

            for gospel in ["matthew", "mark", "luke"]:
                passage_info = parallel.get(gospel)

                if passage_info is None:
                    logger.debug(f"  Skipping {gospel} (not present in this parallel)")
                    continue

                book_name = {
                    "matthew": "馬太福音",
                    "mark": "馬可福音",
                    "luke": "路加福音",
                }[gospel]

                pericope = await self.find_matching_pericope(
                    book_name,
                    passage_info["chapter"],
                    passage_info["verse_start"],
                    passage_info["verse_end"],
                )

                if pericope:
                    pericope_ids.append(pericope.id)
                    self.stats["pericopes_matched"] += 1
                    logger.debug(
                        f"  Found pericope for {gospel}: ID={pericope.id}, title={pericope.title}"
                    )
                else:
                    logger.warning(
                        f"  No pericope match for {gospel} "
                        f"{passage_info['chapter']}:{passage_info['verse_start']}-{passage_info['verse_end']}"
                    )

            # Create relationships
            if len(pericope_ids) >= 2:
                try:
                    created = await self.create_parallel_relationships(
                        pericope_ids, parallel_id, name_zh, name_en
                    )
                    self.stats["relationships_created"] += created
                    logger.info(f"  Created {created} relationships")
                except Exception as e:
                    logger.error(f"  Error creating relationships: {e}")
                    self.stats["errors"] += 1
            else:
                logger.warning(
                    f"  Skipping parallel {parallel_id}: only {len(pericope_ids)} pericope(s) matched"
                )
                self.stats["skipped"] += 1

        return self.stats

    async def clear_existing_parallels(self) -> int:
        """Clear all existing PARALLEL_WITH relationships.

        Returns:
            Number of relationships deleted
        """
        logger.info("Clearing existing PARALLEL_WITH relationships...")
        result = await Neo4jClient.execute_read(
            "MATCH ()-[r:PARALLEL_WITH]->() RETURN count(r) as count"
        )
        count_before = result[0]["count"] if result else 0

        await Neo4jClient.execute_write(
            "MATCH ()-[r:PARALLEL_WITH]->() DELETE r"
        )

        logger.info(f"Deleted {count_before} existing relationships")
        return count_before


async def main(
    data_file: Path,
    clear: bool = False,
    verbose: bool = False,
) -> None:
    """Main entry point.

    Args:
        data_file: Path to JSON data file
        clear: Whether to clear existing relationships first
        verbose: Enable verbose logging
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
            importer = SynopticParallelImporter(session)

            # Clear existing relationships if requested
            if clear:
                await importer.clear_existing_parallels()

            # Import parallels
            stats = await importer.import_parallels(data_file, verbose=verbose)

            # Print summary
            print("\n" + "=" * 60)
            print("Synoptic Parallel Import Summary")
            print("=" * 60)
            print(f"Parallels processed:      {stats['parallels_processed']}")
            print(f"Pericopes matched:        {stats['pericopes_matched']}")
            print(f"Relationships created:    {stats['relationships_created']}")
            print(f"Parallels skipped:        {stats['skipped']}")
            print(f"Errors:                   {stats['errors']}")
            print("=" * 60)

    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise
    finally:
        await engine.dispose()
        await Neo4jClient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import synoptic gospel parallel passages to Neo4j"
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "synoptic_parallels.json",
        help="Path to JSON data file (default: data/synoptic_parallels.json)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing PARALLEL_WITH relationships before importing",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    asyncio.run(main(
        data_file=args.data_file,
        clear=args.clear,
        verbose=args.verbose,
    ))

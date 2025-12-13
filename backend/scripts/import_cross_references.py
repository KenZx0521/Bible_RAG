"""Import Bible cross-references from OpenBible data into Neo4j.

This script downloads cross-reference data from OpenBible.info, parses verse references,
maps them to PostgreSQL verse IDs, and creates Neo4j relationships.

Data source: https://www.openbible.info/labs/cross-references/

Relationship types:
- QUOTES: When OT verse (order_index <= 39) is quoted in NT (order_index > 39)
- ALLUDES_TO: All other cross-references

Usage:
    cd backend
    python -m scripts.import_cross_references
    python -m scripts.import_cross_references --data-file data/cross_references.txt
    python -m scripts.import_cross_references --min-votes 3 --clear
    python -m scripts.import_cross_references -v
"""

import argparse
import asyncio
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlretrieve

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.neo4j_client import Neo4jClient
from app.models.orm import Book, Verse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# OpenBible cross-references data URL
OPENBIBLE_URL = "https://a.openbible.info/data/cross-references.txt"

# Batch size for Neo4j bulk operations
RELATIONSHIP_BATCH_SIZE = 1000

# Old Testament threshold (books 1-39)
OT_MAX_ORDER_INDEX = 39


class VerseRef(NamedTuple):
    """Parsed verse reference."""
    book_abbrev: str
    chapter: int
    verse: int


class CrossReference(NamedTuple):
    """Cross-reference between two verses."""
    from_ref: VerseRef
    to_ref: VerseRef
    votes: int


# Book abbreviation mapping from OpenBible to standard English/Chinese names
# Based on common English abbreviations used by OpenBible
BOOK_ABBREV_MAP = {
    # Old Testament
    "Gen": ("創世記", "Genesis"),
    "Exod": ("出埃及記", "Exodus"),
    "Lev": ("利未記", "Leviticus"),
    "Num": ("民數記", "Numbers"),
    "Deut": ("申命記", "Deuteronomy"),
    "Josh": ("約書亞記", "Joshua"),
    "Judg": ("士師記", "Judges"),
    "Ruth": ("路得記", "Ruth"),
    "1Sam": ("撒母耳記上", "1 Samuel"),
    "2Sam": ("撒母耳記下", "2 Samuel"),
    "1Kgs": ("列王紀上", "1 Kings"),
    "2Kgs": ("列王紀下", "2 Kings"),
    "1Chr": ("歷代志上", "1 Chronicles"),
    "2Chr": ("歷代志下", "2 Chronicles"),
    "Ezra": ("以斯拉記", "Ezra"),
    "Neh": ("尼希米記", "Nehemiah"),
    "Esth": ("以斯帖記", "Esther"),
    "Job": ("約伯記", "Job"),
    "Ps": ("詩篇", "Psalms"),
    "Prov": ("箴言", "Proverbs"),
    "Eccl": ("傳道書", "Ecclesiastes"),
    "Song": ("雅歌", "Song of Solomon"),
    "Isa": ("以賽亞書", "Isaiah"),
    "Jer": ("耶利米書", "Jeremiah"),
    "Lam": ("耶利米哀歌", "Lamentations"),
    "Ezek": ("以西結書", "Ezekiel"),
    "Dan": ("但以理書", "Daniel"),
    "Hos": ("何西阿書", "Hosea"),
    "Joel": ("約珥書", "Joel"),
    "Amos": ("阿摩司書", "Amos"),
    "Obad": ("俄巴底亞書", "Obadiah"),
    "Jonah": ("約拿書", "Jonah"),
    "Mic": ("彌迦書", "Micah"),
    "Nah": ("那鴻書", "Nahum"),
    "Hab": ("哈巴谷書", "Habakkuk"),
    "Zeph": ("西番雅書", "Zephaniah"),
    "Hag": ("哈該書", "Haggai"),
    "Zech": ("撒迦利亞書", "Zechariah"),
    "Mal": ("瑪拉基書", "Malachi"),
    # New Testament
    "Matt": ("馬太福音", "Matthew"),
    "Mark": ("馬可福音", "Mark"),
    "Luke": ("路加福音", "Luke"),
    "John": ("約翰福音", "John"),
    "Acts": ("使徒行傳", "Acts"),
    "Rom": ("羅馬書", "Romans"),
    "1Cor": ("哥林多前書", "1 Corinthians"),
    "2Cor": ("哥林多後書", "2 Corinthians"),
    "Gal": ("加拉太書", "Galatians"),
    "Eph": ("以弗所書", "Ephesians"),
    "Phil": ("腓立比書", "Philippians"),
    "Col": ("歌羅西書", "Colossians"),
    "1Thess": ("帖撒羅尼迦前書", "1 Thessalonians"),
    "2Thess": ("帖撒羅尼迦後書", "2 Thessalonians"),
    "1Tim": ("提摩太前書", "1 Timothy"),
    "2Tim": ("提摩太後書", "2 Timothy"),
    "Titus": ("提多書", "Titus"),
    "Phlm": ("腓利門書", "Philemon"),
    "Heb": ("希伯來書", "Hebrews"),
    "Jas": ("雅各書", "James"),
    "1Pet": ("彼得前書", "1 Peter"),
    "2Pet": ("彼得後書", "2 Peter"),
    "1John": ("約翰一書", "1 John"),
    "2John": ("約翰二書", "2 John"),
    "3John": ("約翰三書", "3 John"),
    "Jude": ("猶大書", "Jude"),
    "Rev": ("啟示錄", "Revelation"),
}


class CrossReferenceImporter:
    """Import cross-references from OpenBible into Neo4j."""

    def __init__(self, pg_session: AsyncSession, min_votes: int = 1):
        """Initialize importer.

        Args:
            pg_session: PostgreSQL async session
            min_votes: Minimum votes to include a cross-reference
        """
        self.pg_session = pg_session
        self.min_votes = min_votes
        self.book_cache: dict[str, Book] = {}
        self.verse_cache: dict[tuple[int, int, int], int] = {}

    async def import_cross_references(
        self,
        data_file: Path,
        clear_existing: bool = True,
    ) -> dict:
        """Import cross-references from TSV file.

        Args:
            data_file: Path to cross-references TSV file
            clear_existing: Whether to clear existing relationships first

        Returns:
            Statistics dict
        """
        stats = {
            "total_lines": 0,
            "parsed": 0,
            "filtered": 0,
            "quotes": 0,
            "allusions": 0,
            "errors": 0,
            "skipped_votes": 0,
        }

        # Load book and verse mappings
        logger.info("Loading book and verse mappings from PostgreSQL...")
        await self._load_book_cache()
        await self._load_verse_cache()
        logger.info(f"  Loaded {len(self.book_cache)} books and {len(self.verse_cache)} verses")

        # Clear existing relationships if requested
        if clear_existing:
            logger.info("Clearing existing cross-reference relationships...")
            await self._clear_relationships()

        # Parse cross-references from file
        logger.info(f"Parsing cross-references from {data_file}...")
        cross_refs = self._parse_tsv_file(data_file, stats)
        logger.info(f"  Parsed {len(cross_refs)} cross-references")

        # Map to verse IDs and create relationships
        logger.info("Creating Neo4j relationships...")
        relationships = self._prepare_relationships(cross_refs, stats)

        if relationships["quotes"] or relationships["allusions"]:
            await self._create_relationships(relationships, stats)

        logger.info(f"Import complete: {stats}")
        return stats

    async def _load_book_cache(self) -> None:
        """Load all books into cache for quick lookup."""
        result = await self.pg_session.execute(select(Book))
        books = result.scalars().all()

        for book in books:
            # Cache by Chinese name
            self.book_cache[book.name_zh] = book
            # Cache by Chinese abbreviation
            self.book_cache[book.abbrev_zh] = book
            # Cache by English abbreviation (if in mapping)
            for abbrev, (zh_name, en_name) in BOOK_ABBREV_MAP.items():
                if zh_name == book.name_zh:
                    self.book_cache[abbrev] = book
                    self.book_cache[en_name] = book

    async def _load_verse_cache(self) -> None:
        """Load all verses into cache for quick lookup."""
        # Query in batches to avoid memory issues
        offset = 0
        batch_size = 10000

        while True:
            result = await self.pg_session.execute(
                select(Verse.id, Verse.book_id, Verse.chapter, Verse.verse)
                .order_by(Verse.id)
                .offset(offset)
                .limit(batch_size)
            )
            verses = result.all()

            if not verses:
                break

            for verse_id, book_id, chapter, verse in verses:
                self.verse_cache[(book_id, chapter, verse)] = verse_id

            offset += batch_size

    async def _clear_relationships(self) -> None:
        """Clear existing QUOTES and ALLUDES_TO relationships."""
        await Neo4jClient.execute_write(
            """
            MATCH ()-[r:QUOTES]->()
            WHERE r.source = 'openbible'
            DELETE r
            """
        )
        await Neo4jClient.execute_write(
            """
            MATCH ()-[r:ALLUDES_TO]->()
            WHERE r.source = 'openbible'
            DELETE r
            """
        )

    def _parse_tsv_file(self, file_path: Path, stats: dict) -> list[CrossReference]:
        """Parse TSV file and extract cross-references.

        Args:
            file_path: Path to TSV file
            stats: Statistics dict to update

        Returns:
            List of CrossReference objects
        """
        cross_refs = []

        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                stats["total_lines"] += 1
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                try:
                    # Parse TSV format: from_verse\tto_verse\tvotes
                    parts = line.split("\t")
                    if len(parts) != 3:
                        logger.warning(f"Line {line_num}: Invalid format (expected 3 columns): {line}")
                        stats["errors"] += 1
                        continue

                    from_str, to_str, votes_str = parts
                    votes = int(votes_str)

                    # Filter by minimum votes
                    if votes < self.min_votes:
                        stats["skipped_votes"] += 1
                        continue

                    # Parse verse references
                    from_ref = self._parse_verse_ref(from_str)
                    to_ref = self._parse_verse_ref(to_str)

                    if from_ref and to_ref:
                        cross_refs.append(CrossReference(from_ref, to_ref, votes))
                        stats["parsed"] += 1
                    else:
                        stats["errors"] += 1

                except Exception as e:
                    logger.warning(f"Line {line_num}: Parse error: {e}")
                    stats["errors"] += 1

        return cross_refs

    def _parse_verse_ref(self, ref_str: str) -> VerseRef | None:
        """Parse verse reference string.

        Examples:
            - Gen.1.1 -> VerseRef("Gen", 1, 1)
            - Matt.5.17 -> VerseRef("Matt", 5, 17)
            - 1Cor.15.3 -> VerseRef("1Cor", 15, 3)

        Args:
            ref_str: Verse reference string

        Returns:
            VerseRef object or None if parse failed
        """
        # Pattern: BookAbbrev.Chapter.Verse
        # Handles books like "1Cor", "2Tim", etc.
        match = re.match(r"^(\d?[A-Za-z]+)\.(\d+)\.(\d+)$", ref_str)
        if not match:
            logger.debug(f"Failed to parse verse reference: {ref_str}")
            return None

        book_abbrev, chapter, verse = match.groups()

        try:
            return VerseRef(
                book_abbrev=book_abbrev,
                chapter=int(chapter),
                verse=int(verse),
            )
        except ValueError as e:
            logger.debug(f"Invalid chapter/verse numbers in {ref_str}: {e}")
            return None

    def _prepare_relationships(
        self,
        cross_refs: list[CrossReference],
        stats: dict,
    ) -> dict[str, list]:
        """Prepare relationships data for Neo4j batch creation.

        Args:
            cross_refs: List of CrossReference objects
            stats: Statistics dict to update

        Returns:
            Dict with 'quotes' and 'allusions' lists
        """
        relationships = {
            "quotes": [],
            "allusions": [],
        }

        for cross_ref in cross_refs:
            # Resolve book IDs
            from_book = self.book_cache.get(cross_ref.from_ref.book_abbrev)
            to_book = self.book_cache.get(cross_ref.to_ref.book_abbrev)

            if not from_book or not to_book:
                logger.debug(
                    f"Book not found: {cross_ref.from_ref.book_abbrev} or "
                    f"{cross_ref.to_ref.book_abbrev}"
                )
                stats["filtered"] += 1
                continue

            # Resolve verse IDs
            from_verse_id = self.verse_cache.get(
                (from_book.id, cross_ref.from_ref.chapter, cross_ref.from_ref.verse)
            )
            to_verse_id = self.verse_cache.get(
                (to_book.id, cross_ref.to_ref.chapter, cross_ref.to_ref.verse)
            )

            if not from_verse_id or not to_verse_id:
                logger.debug(
                    f"Verse not found: {cross_ref.from_ref} or {cross_ref.to_ref}"
                )
                stats["filtered"] += 1
                continue

            # Determine relationship type
            # QUOTES: OT -> NT (from_order <= 39 and to_order > 39)
            # ALLUDES_TO: All other cases
            is_quote = (
                from_book.order_index <= OT_MAX_ORDER_INDEX and
                to_book.order_index > OT_MAX_ORDER_INDEX
            )

            rel_data = {
                "from_verse_id": from_verse_id,
                "to_verse_id": to_verse_id,
                "votes": cross_ref.votes,
            }

            if is_quote:
                relationships["quotes"].append(rel_data)
            else:
                relationships["allusions"].append(rel_data)

        return relationships

    async def _create_relationships(
        self,
        relationships: dict[str, list],
        stats: dict,
    ) -> None:
        """Create Neo4j relationships in batches.

        Args:
            relationships: Dict with 'quotes' and 'allusions' lists
            stats: Statistics dict to update
        """
        # Create QUOTES relationships
        quotes = relationships["quotes"]
        if quotes:
            logger.info(f"Creating {len(quotes)} QUOTES relationships...")
            for i in range(0, len(quotes), RELATIONSHIP_BATCH_SIZE):
                batch = quotes[i:i + RELATIONSHIP_BATCH_SIZE]
                await Neo4jClient.execute_write(
                    """
                    UNWIND $data AS d
                    MATCH (from:Verse {id: d.from_verse_id})
                    MATCH (to:Verse {id: d.to_verse_id})
                    CREATE (to)-[:QUOTES {source: 'openbible', votes: d.votes}]->(from)
                    """,
                    {"data": batch}
                )
                stats["quotes"] += len(batch)
                logger.info(f"  Created {stats['quotes']}/{len(quotes)} QUOTES...")

        # Create ALLUDES_TO relationships
        allusions = relationships["allusions"]
        if allusions:
            logger.info(f"Creating {len(allusions)} ALLUDES_TO relationships...")
            for i in range(0, len(allusions), RELATIONSHIP_BATCH_SIZE):
                batch = allusions[i:i + RELATIONSHIP_BATCH_SIZE]
                await Neo4jClient.execute_write(
                    """
                    UNWIND $data AS d
                    MATCH (from:Verse {id: d.from_verse_id})
                    MATCH (to:Verse {id: d.to_verse_id})
                    CREATE (from)-[:ALLUDES_TO {source: 'openbible', votes: d.votes}]->(to)
                    """,
                    {"data": batch}
                )
                stats["allusions"] += len(batch)
                logger.info(f"  Created {stats['allusions']}/{len(allusions)} ALLUDES_TO...")


async def download_data_file(output_path: Path) -> None:
    """Download OpenBible cross-references data.

    Args:
        output_path: Path to save downloaded file
    """
    logger.info(f"Downloading cross-references from {OPENBIBLE_URL}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        urlretrieve(OPENBIBLE_URL, output_path)
        logger.info(f"Downloaded to {output_path}")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise


async def main(
    data_file: Path | None = None,
    min_votes: int = 1,
    clear: bool = True,
    verbose: bool = False,
) -> None:
    """Main entry point.

    Args:
        data_file: Path to TSV file, or download if None
        min_votes: Minimum votes to include a cross-reference
        clear: Whether to clear existing relationships
        verbose: Enable verbose logging
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize Neo4j
    await Neo4jClient.initialize()

    if not Neo4jClient.is_available():
        logger.error("Neo4j is not available. Please ensure Neo4j is running.")
        logger.info("Start Neo4j with: docker compose --profile full up -d neo4j")
        return

    # Download data if not provided
    if data_file is None:
        data_file = Path(__file__).parent.parent / "data" / "cross_references.txt"
        if not data_file.exists():
            await download_data_file(data_file)
    elif not data_file.exists():
        logger.error(f"Data file not found: {data_file}")
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
            importer = CrossReferenceImporter(session, min_votes=min_votes)
            stats = await importer.import_cross_references(
                data_file=data_file,
                clear_existing=clear,
            )

            print("\nCross-Reference Import Statistics:")
            print(f"  Total lines: {stats['total_lines']}")
            print(f"  Parsed: {stats['parsed']}")
            print(f"  Skipped (min votes): {stats['skipped_votes']}")
            print(f"  Filtered (not found): {stats['filtered']}")
            print(f"  Errors: {stats['errors']}")
            print(f"  Created QUOTES: {stats['quotes']}")
            print(f"  Created ALLUDES_TO: {stats['allusions']}")
            print(f"  Total relationships: {stats['quotes'] + stats['allusions']}")

    finally:
        await engine.dispose()
        await Neo4jClient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import Bible cross-references from OpenBible into Neo4j"
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        help="Path to cross-references TSV file (downloads if not provided)",
    )
    parser.add_argument(
        "--min-votes",
        type=int,
        default=1,
        help="Minimum votes to include a cross-reference (default: 1)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing relationships (append mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    asyncio.run(main(
        data_file=args.data_file,
        min_votes=args.min_votes,
        clear=not args.no_clear,
        verbose=args.verbose,
    ))

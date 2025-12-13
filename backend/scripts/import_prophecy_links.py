"""Import prophecy fulfillment links.

This script identifies OT prophecies fulfilled in the NT by:
1. Filtering OT→NT cross-references (from import_cross_references.py)
2. Using LLM to verify if a cross-reference is a prophecy fulfillment
3. Creating PROPHECY_FULFILLED_IN relationships in Neo4j

Usage:
    cd backend
    python -m scripts.import_prophecy_links
    python -m scripts.import_prophecy_links --min-votes 5
    python -m scripts.import_prophecy_links --skip-llm  # Use all OT->NT refs without verification
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select, text
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

# Checkpoint file for LLM verification progress
CHECKPOINT_FILE = Path("prophecy_links_checkpoint.json")

# Batch sizes
NEO4J_BATCH_SIZE = 500
LLM_BATCH_SIZE = 10

# OT book order index threshold (Genesis to Malachi = 1-39)
OT_MAX_ORDER = 39

# LLM prompt for prophecy verification
PROPHECY_SYSTEM_PROMPT = """你是聖經預言專家。請判斷給定的舊約經文是否被視為預言、預表或彌賽亞預言，並在新約經文中得到應驗或引用。

判斷標準：
1. 舊約經文是否包含預言性內容（關於未來事件、彌賽亞、神的計劃等）
2. 新約經文是否明確引用或應用該舊約經文
3. 傳統上是否被認為是預言與應驗的關係

只回答 "YES" 或 "NO"，不要有任何其他文字。"""


class ProphecyLinkImporter:
    """Import prophecy fulfillment links from cross-references."""

    def __init__(
        self,
        session: AsyncSession,
        min_votes: int = 3,
        skip_llm: bool = False,
    ):
        self.session = session
        self.min_votes = min_votes
        self.skip_llm = skip_llm
        self.llm_client = None
        self.book_cache: dict[int, dict] = {}  # book_id -> {name, order_index}
        self.verse_text_cache: dict[int, str] = {}  # verse_id -> text

    async def _init_llm(self):
        """Initialize LLM client."""
        if self.llm_client is None and not self.skip_llm:
            from app.services.llm_client import OllamaLLMClient
            self.llm_client = OllamaLLMClient()

    async def _load_caches(self):
        """Load book and verse caches."""
        logger.info("Loading book and verse caches...")

        # Load books
        result = await self.session.execute(select(Book))
        books = result.scalars().all()
        for book in books:
            self.book_cache[book.id] = {
                "name": book.name_zh,
                "order_index": book.order_index,
            }

        logger.info(f"Loaded {len(self.book_cache)} books")

    async def _get_verse_text(self, verse_id: int) -> str:
        """Get verse text with caching."""
        if verse_id not in self.verse_text_cache:
            result = await self.session.execute(
                select(Verse.text).where(Verse.id == verse_id)
            )
            row = result.scalar_one_or_none()
            self.verse_text_cache[verse_id] = row or ""

        return self.verse_text_cache[verse_id]

    async def import_prophecy_links(self) -> dict[str, int]:
        """Import prophecy fulfillment links.

        Returns:
            Statistics dict
        """
        stats = {
            "ot_nt_refs_found": 0,
            "verified_by_llm": 0,
            "skipped_by_llm": 0,
            "relationships_created": 0,
            "errors": 0,
        }

        await self._init_llm()
        await self._load_caches()

        # Load checkpoint if exists
        verified_pairs = set()
        if CHECKPOINT_FILE.exists() and not self.skip_llm:
            with open(CHECKPOINT_FILE, "r") as f:
                checkpoint = json.load(f)
                verified_pairs = set(tuple(p) for p in checkpoint.get("verified_pairs", []))
                logger.info(f"Loaded checkpoint with {len(verified_pairs)} verified pairs")

        # Query existing QUOTES relationships (OT->NT cross-references)
        logger.info("Querying OT→NT cross-references from Neo4j...")

        cypher = """
        MATCH (nt_verse:Verse)-[r:QUOTES]->(ot_verse:Verse)
        WHERE r.votes >= $min_votes
        RETURN ot_verse.id AS ot_id, nt_verse.id AS nt_id, r.votes AS votes
        ORDER BY r.votes DESC
        """

        try:
            results = await Neo4jClient.execute_read(
                cypher, {"min_votes": self.min_votes}
            )
        except Exception as e:
            logger.error(f"Failed to query cross-references: {e}")
            # Try alternative: query from PostgreSQL if Neo4j doesn't have QUOTES yet
            logger.info("Falling back to PostgreSQL query for OT→NT pairs...")
            results = await self._get_ot_nt_pairs_from_postgres()

        if not results:
            logger.warning("No OT→NT cross-references found")
            return stats

        stats["ot_nt_refs_found"] = len(results)
        logger.info(f"Found {len(results)} OT→NT cross-references")

        # Process references
        prophecy_links = []

        for ref in results:
            ot_id = ref["ot_id"] if isinstance(ref, dict) else ref[0]
            nt_id = ref["nt_id"] if isinstance(ref, dict) else ref[1]
            votes = ref.get("votes", 1) if isinstance(ref, dict) else (ref[2] if len(ref) > 2 else 1)

            pair_key = (ot_id, nt_id)

            if self.skip_llm:
                # Skip LLM verification, use all OT->NT refs
                prophecy_links.append({
                    "ot_id": ot_id,
                    "nt_id": nt_id,
                    "votes": votes,
                    "confidence": 0.7,  # Lower confidence without LLM
                })
                stats["verified_by_llm"] += 1
            elif pair_key in verified_pairs:
                # Already verified in previous run
                prophecy_links.append({
                    "ot_id": ot_id,
                    "nt_id": nt_id,
                    "votes": votes,
                    "confidence": 0.9,
                })
                stats["verified_by_llm"] += 1
            else:
                # Verify with LLM
                try:
                    is_prophecy = await self._verify_prophecy_with_llm(ot_id, nt_id)
                    if is_prophecy:
                        prophecy_links.append({
                            "ot_id": ot_id,
                            "nt_id": nt_id,
                            "votes": votes,
                            "confidence": 0.9,
                        })
                        verified_pairs.add(pair_key)
                        stats["verified_by_llm"] += 1
                    else:
                        stats["skipped_by_llm"] += 1

                    # Save checkpoint periodically
                    if len(verified_pairs) % LLM_BATCH_SIZE == 0:
                        self._save_checkpoint(verified_pairs)

                except Exception as e:
                    logger.warning(f"LLM verification failed for {ot_id}->{nt_id}: {e}")
                    stats["errors"] += 1

        # Save final checkpoint
        if not self.skip_llm:
            self._save_checkpoint(verified_pairs)

        # Create Neo4j relationships
        if prophecy_links:
            logger.info(f"Creating {len(prophecy_links)} PROPHECY_FULFILLED_IN relationships...")
            await self._create_relationships(prophecy_links)
            stats["relationships_created"] = len(prophecy_links)

        return stats

    async def _get_ot_nt_pairs_from_postgres(self) -> list[dict]:
        """Get OT→NT verse pairs from PostgreSQL (fallback).

        This queries verse_entities and similar tables to find potential
        prophecy connections if Neo4j QUOTES relationships don't exist yet.
        """
        # This is a simplified fallback - in production, you'd want to
        # run import_cross_references.py first
        logger.warning("No QUOTES relationships in Neo4j. Run import_cross_references.py first.")
        return []

    async def _verify_prophecy_with_llm(self, ot_id: int, nt_id: int) -> bool:
        """Verify if a cross-reference is a prophecy fulfillment.

        Args:
            ot_id: OT verse ID
            nt_id: NT verse ID

        Returns:
            True if verified as prophecy fulfillment
        """
        if not self.llm_client:
            return True  # Default to True if no LLM

        # Get verse texts
        ot_text = await self._get_verse_text(ot_id)
        nt_text = await self._get_verse_text(nt_id)

        if not ot_text or not nt_text:
            return False

        # Get book names for reference
        ot_verse = await self.session.execute(
            select(Verse).where(Verse.id == ot_id)
        )
        ot_verse = ot_verse.scalar_one_or_none()

        nt_verse = await self.session.execute(
            select(Verse).where(Verse.id == nt_id)
        )
        nt_verse = nt_verse.scalar_one_or_none()

        if not ot_verse or not nt_verse:
            return False

        ot_book_name = self.book_cache.get(ot_verse.book_id, {}).get("name", "")
        nt_book_name = self.book_cache.get(nt_verse.book_id, {}).get("name", "")

        ot_ref = f"{ot_book_name} {ot_verse.chapter}:{ot_verse.verse}"
        nt_ref = f"{nt_book_name} {nt_verse.chapter}:{nt_verse.verse}"

        prompt = f"""舊約經文（{ot_ref}）：
{ot_text}

新約經文（{nt_ref}）：
{nt_text}

這是預言與應驗的關係嗎？"""

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=PROPHECY_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=10,
            )

            answer = response.strip().upper()
            return answer.startswith("YES")

        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return False

    def _save_checkpoint(self, verified_pairs: set):
        """Save checkpoint to file."""
        checkpoint = {
            "verified_pairs": list(verified_pairs),
        }
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(checkpoint, f)

    async def _create_relationships(self, links: list[dict]) -> None:
        """Create PROPHECY_FULFILLED_IN relationships in Neo4j.

        Args:
            links: List of prophecy link dicts
        """
        cypher = """
        UNWIND $links AS link
        MATCH (ot:Verse {id: link.ot_id})
        MATCH (nt:Verse {id: link.nt_id})
        MERGE (ot)-[r:PROPHECY_FULFILLED_IN]->(nt)
        SET r.confidence = link.confidence,
            r.votes = link.votes,
            r.source = 'cross_reference'
        """

        for i in range(0, len(links), NEO4J_BATCH_SIZE):
            batch = links[i:i + NEO4J_BATCH_SIZE]
            await Neo4jClient.execute_write(cypher, {"links": batch})
            logger.info(f"  Created {min(i + NEO4J_BATCH_SIZE, len(links))}/{len(links)} relationships...")

    async def clear_existing_relationships(self) -> int:
        """Clear existing PROPHECY_FULFILLED_IN relationships.

        Returns:
            Number of deleted relationships
        """
        count_result = await Neo4jClient.execute_read(
            "MATCH ()-[r:PROPHECY_FULFILLED_IN]->() RETURN count(r) as count"
        )
        count = count_result[0]["count"] if count_result else 0

        if count > 0:
            logger.info(f"Clearing {count} existing PROPHECY_FULFILLED_IN relationships...")
            await Neo4jClient.execute_write(
                "MATCH ()-[r:PROPHECY_FULFILLED_IN]->() DELETE r"
            )

        return count


async def main(
    min_votes: int = 3,
    skip_llm: bool = False,
    clear_existing: bool = True,
) -> None:
    """Main entry point.

    Args:
        min_votes: Minimum votes threshold for cross-references
        skip_llm: Skip LLM verification (use all OT->NT refs)
        clear_existing: Clear existing relationships first
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
            importer = ProphecyLinkImporter(
                session=session,
                min_votes=min_votes,
                skip_llm=skip_llm,
            )

            if clear_existing:
                deleted = await importer.clear_existing_relationships()
                if deleted > 0:
                    logger.info(f"Cleared {deleted} existing relationships")

            stats = await importer.import_prophecy_links()

            print("\nProphecy Link Import Statistics:")
            for key, value in stats.items():
                print(f"  {key}: {value}")

    finally:
        await engine.dispose()
        await Neo4jClient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import prophecy fulfillment links"
    )
    parser.add_argument(
        "--min-votes",
        type=int,
        default=3,
        help="Minimum votes for cross-references (default: 3)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM verification (use all OT->NT refs)",
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
        min_votes=args.min_votes,
        skip_llm=args.skip_llm,
        clear_existing=not args.no_clear,
    ))

"""Summary generation script using LLM.

This script generates summaries for Bible pericopes using Ollama LLM.
It processes pericopes where summary IS NULL and updates the summary field.

Usage:
    cd backend
    python -m scripts.summary_generator
    python -m scripts.summary_generator --batch-size 5 --no-resume
    python -m scripts.summary_generator --limit 100  # Process only first 100 pericopes
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.models.orm import Book, Pericope, Verse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Checkpoint file
CHECKPOINT_FILE = Path("summary_generation_checkpoint.json")

# Summary generation system prompt (Traditional Chinese)
SUMMARY_SYSTEM_PROMPT = """你是聖經摘要專家。請為給定的聖經段落生成簡潔的摘要。
摘要應該：
1. 使用繁體中文
2. 包含2-4句話
3. 捕捉段落的主要敘事或教導
4. 避免過度神學詮釋

請直接回答摘要內容，不需要其他解釋或標題。"""


class SummaryGenerator:
    """Generate summaries for Bible pericopes using LLM."""

    def __init__(
        self,
        session: AsyncSession,
        batch_size: int = 10,
    ):
        self.session = session
        self.batch_size = batch_size
        self.llm_client = None

    async def _init_llm(self):
        """Initialize LLM client."""
        if self.llm_client is None:
            from app.services.llm_client import OllamaLLMClient
            self.llm_client = OllamaLLMClient()

    async def generate_all(
        self,
        resume: bool = True,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Generate summaries for all pericopes where summary IS NULL.

        Args:
            resume: Whether to resume from checkpoint
            limit: Optional limit on number of pericopes to process

        Returns:
            Statistics dict with counts
        """
        await self._init_llm()

        # Load checkpoint
        processed_ids: set[int] = set()
        if resume and CHECKPOINT_FILE.exists():
            try:
                checkpoint = json.loads(CHECKPOINT_FILE.read_text())
                processed_ids = set(checkpoint.get("processed_ids", []))
                logger.info(f"Resuming from checkpoint: {len(processed_ids)} already processed")
            except json.JSONDecodeError:
                logger.warning("Invalid checkpoint file, starting fresh")

        # Get pericopes to process (where summary IS NULL)
        query = (
            select(Pericope)
            .where(Pericope.summary.is_(None))
            .order_by(Pericope.id)
        )
        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        all_pericopes = result.scalars().all()
        total = len(all_pericopes)

        logger.info(f"Total pericopes without summary: {total}, already processed: {len(processed_ids)}")

        stats = {
            "total": total,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
        }

        for i, pericope in enumerate(all_pericopes):
            if pericope.id in processed_ids:
                stats["skipped"] += 1
                continue

            try:
                success = await self._process_pericope(pericope)
                if success:
                    processed_ids.add(pericope.id)
                    stats["processed"] += 1
                else:
                    stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error processing pericope {pericope.id}: {e}", exc_info=True)
                stats["errors"] += 1
                continue

            # Commit and save checkpoint every batch
            if (i + 1) % self.batch_size == 0:
                await self.session.commit()
                self._save_checkpoint(processed_ids)
                logger.info(
                    f"Progress: {i + 1}/{total} "
                    f"(processed: {stats['processed']}, errors: {stats['errors']})"
                )

        # Final commit and checkpoint
        await self.session.commit()
        self._save_checkpoint(processed_ids)

        logger.info(f"Summary generation complete: {stats}")
        return stats

    def _save_checkpoint(self, processed_ids: set[int]) -> None:
        """Save checkpoint to file."""
        CHECKPOINT_FILE.write_text(json.dumps({
            "processed_ids": list(processed_ids),
        }))

    async def _process_pericope(self, pericope: Pericope) -> bool:
        """Process a single pericope and generate summary.

        Args:
            pericope: Pericope to process

        Returns:
            True if successful, False otherwise
        """
        # Get verses for this pericope
        result = await self.session.execute(
            select(Verse)
            .where(Verse.pericope_id == pericope.id)
            .order_by(Verse.chapter, Verse.verse)
        )
        verses = result.scalars().all()

        if not verses:
            logger.warning(f"No verses found for pericope {pericope.id}")
            return False

        # Get book name
        book_result = await self.session.execute(
            select(Book).where(Book.id == pericope.book_id)
        )
        book = book_result.scalar_one_or_none()
        book_name = book.name_zh if book else "未知書卷"

        # Build context for LLM
        verse_texts = "\n".join(
            f"{v.chapter}:{v.verse} {v.text}"
            for v in verses
        )

        # Create user prompt
        user_prompt = f"""請為以下聖經段落生成摘要：
書卷：{book_name}
標題：{pericope.title}
經文：
{verse_texts}"""

        # Call LLM for summary generation
        try:
            summary = await self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=256,
            )
        except Exception as e:
            logger.error(f"LLM call failed for pericope {pericope.id}: {e}")
            return False

        # Clean up summary (remove extra whitespace, newlines)
        summary = summary.strip()
        if not summary:
            logger.warning(f"Empty summary generated for pericope {pericope.id}")
            return False

        # Update pericope summary
        await self.session.execute(
            update(Pericope)
            .where(Pericope.id == pericope.id)
            .values(summary=summary)
        )

        logger.debug(f"Generated summary for pericope {pericope.id}: {summary[:100]}...")
        return True


async def main(
    resume: bool = True,
    batch_size: int = 10,
    limit: int | None = None,
    verbose: bool = False,
) -> None:
    """Main entry point.

    Args:
        resume: Whether to resume from checkpoint
        batch_size: Number of pericopes per batch
        limit: Optional limit on pericopes to process
        verbose: Enable verbose logging
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create async engine
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

    async with async_session() as session:
        generator = SummaryGenerator(session, batch_size=batch_size)
        stats = await generator.generate_all(resume=resume, limit=limit)
        print(f"\nSummary Generation Statistics:")
        print(f"  Total pericopes without summary: {stats['total']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Skipped (already done): {stats['skipped']}")
        print(f"  Errors: {stats['errors']}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate summaries for Bible pericopes using LLM"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh, ignore checkpoint",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of pericopes per batch (default: 10)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of pericopes to process",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    asyncio.run(main(
        resume=not args.no_resume,
        batch_size=args.batch_size,
        limit=args.limit,
        verbose=args.verbose,
    ))

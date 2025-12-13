"""Sparse retriever using PostgreSQL full-text search."""

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.orm import Pericope, Verse


@dataclass
class SparseRetrievalResult:
    """Result from sparse retrieval."""

    id: int
    book_id: int
    book_name: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    title: str
    text: str
    score: float


class SparseRetriever:
    """Sparse retriever using PostgreSQL full-text search."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def retrieve(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[SparseRetrievalResult]:
        """Retrieve pericopes by full-text search.

        Args:
            query: Query text
            top_k: Number of results to return

        Returns:
            List of retrieval results ordered by relevance
        """
        # Use plainto_tsquery for simple query parsing
        # This handles Chinese text reasonably well with 'simple' configuration
        tsquery = func.plainto_tsquery("simple", query)

        # First, find matching verses
        verse_stmt = (
            select(
                Verse.pericope_id,
                func.ts_rank(Verse.tsv, tsquery).label("rank"),
            )
            .where(Verse.tsv.op("@@")(tsquery))
            .where(Verse.pericope_id.isnot(None))
            .group_by(Verse.pericope_id)
            .order_by(text("rank DESC"))
            .limit(top_k * 2)  # Get more to ensure enough pericopes
        )

        verse_result = await self.db.execute(verse_stmt)
        pericope_ranks = {row.pericope_id: row.rank for row in verse_result.all()}

        if not pericope_ranks:
            return []

        # Get pericope details
        pericope_ids = list(pericope_ranks.keys())[:top_k]

        pericope_stmt = (
            select(Pericope)
            .where(Pericope.id.in_(pericope_ids))
            .options(selectinload(Pericope.book))
        )

        pericope_result = await self.db.execute(pericope_stmt)
        pericopes = pericope_result.scalars().all()

        # Build results
        results = []
        for pericope in pericopes:
            # Get verse texts
            verse_text_stmt = (
                select(Verse.text)
                .where(Verse.pericope_id == pericope.id)
                .order_by(Verse.chapter, Verse.verse)
            )
            verse_result = await self.db.execute(verse_text_stmt)
            verse_texts = verse_result.scalars().all()
            full_text = "\n".join(verse_texts)

            # Normalize rank to 0-1 range (approximate)
            raw_rank = pericope_ranks.get(pericope.id, 0)
            # ts_rank typically returns values between 0 and 1, but can be higher
            normalized_score = min(1.0, raw_rank / 0.5) if raw_rank > 0 else 0.0

            results.append(
                SparseRetrievalResult(
                    id=pericope.id,
                    book_id=pericope.book_id,
                    book_name=pericope.book.name_zh if pericope.book else "Unknown",
                    chapter_start=pericope.chapter_start,
                    verse_start=pericope.verse_start,
                    chapter_end=pericope.chapter_end,
                    verse_end=pericope.verse_end,
                    title=pericope.title,
                    text=full_text,
                    score=normalized_score,
                )
            )

        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

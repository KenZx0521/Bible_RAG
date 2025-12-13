"""Dense retriever using pgvector."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.orm import Pericope, Verse
from app.services.embedding_service import EmbeddingService


@dataclass
class RetrievalResult:
    """Result from retrieval."""

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


class DenseRetriever:
    """Dense retriever using pgvector for semantic similarity search."""

    def __init__(self, db: AsyncSession, embed_service: EmbeddingService):
        self.db = db
        self.embed_service = embed_service

    async def retrieve(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[RetrievalResult]:
        """Retrieve pericopes by semantic similarity.

        Args:
            query: Query text
            top_k: Number of results to return

        Returns:
            List of retrieval results ordered by similarity
        """
        # Generate query embedding
        query_embedding = await self.embed_service.encode(query)

        # Convert numpy array to list for pgvector
        embedding_list = query_embedding.tolist()

        # Query using cosine distance
        # Note: cosine_distance = 1 - cosine_similarity, so lower is better
        stmt = (
            select(
                Pericope.id,
                Pericope.book_id,
                Pericope.chapter_start,
                Pericope.verse_start,
                Pericope.chapter_end,
                Pericope.verse_end,
                Pericope.title,
                Pericope.embedding.cosine_distance(embedding_list).label("distance"),
            )
            .where(Pericope.embedding.isnot(None))
            .order_by("distance")
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Get book names and verse texts
        results = []
        for row in rows:
            # Get book name
            book_result = await self.db.execute(
                select(Pericope)
                .where(Pericope.id == row.id)
                .options(selectinload(Pericope.book))
            )
            pericope = book_result.scalar_one()
            book_name = pericope.book.name_zh if pericope.book else "Unknown"

            # Get verse texts
            verse_result = await self.db.execute(
                select(Verse.text)
                .where(Verse.pericope_id == row.id)
                .order_by(Verse.chapter, Verse.verse)
            )
            verse_texts = verse_result.scalars().all()
            full_text = "\n".join(verse_texts)

            # Convert distance to similarity score (1 - distance)
            similarity = 1.0 - row.distance

            results.append(
                RetrievalResult(
                    id=row.id,
                    book_id=row.book_id,
                    book_name=book_name,
                    chapter_start=row.chapter_start,
                    verse_start=row.verse_start,
                    chapter_end=row.chapter_end,
                    verse_end=row.verse_end,
                    title=row.title,
                    text=full_text,
                    score=similarity,
                )
            )

        return results

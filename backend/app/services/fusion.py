"""RRF (Reciprocal Rank Fusion) for combining retrieval results."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass
class FusedResult:
    """Result after RRF fusion."""

    id: int
    book_id: int
    book_name: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    title: str
    text: str
    score: float  # RRF score
    sources: list[str]  # Which retrievers contributed


class RRFFusion:
    """Reciprocal Rank Fusion for combining multiple retriever results.

    RRF formula: score(d) = Σ 1/(k + rank_i(d))

    Where:
    - d is a document
    - k is a constant (default 60)
    - rank_i(d) is the rank of document d in retriever i (1-indexed)
    """

    def __init__(self, k: int | None = None):
        self.k = k or settings.RRF_K

    def fuse(
        self,
        result_lists: list[tuple[str, list[Any]]],
    ) -> list[FusedResult]:
        """Fuse multiple retrieval result lists using RRF.

        Args:
            result_lists: List of (source_name, results) tuples.
                         Each result should have 'id' attribute.

        Returns:
            List of fused results sorted by RRF score
        """
        # Calculate RRF scores
        doc_scores: dict[int, float] = defaultdict(float)
        doc_data: dict[int, Any] = {}
        doc_sources: dict[int, list[str]] = defaultdict(list)

        for source_name, results in result_lists:
            for rank, result in enumerate(results, start=1):
                doc_id = result.id

                # RRF formula: 1 / (k + rank)
                rrf_score = 1.0 / (self.k + rank)
                doc_scores[doc_id] += rrf_score

                # Store the first occurrence of document data
                if doc_id not in doc_data:
                    doc_data[doc_id] = result

                # Track which sources contributed
                if source_name not in doc_sources[doc_id]:
                    doc_sources[doc_id].append(source_name)

        # Build fused results
        fused_results = []
        for doc_id, rrf_score in sorted(
            doc_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            data = doc_data[doc_id]
            fused_results.append(
                FusedResult(
                    id=doc_id,
                    book_id=data.book_id,
                    book_name=data.book_name,
                    chapter_start=data.chapter_start,
                    verse_start=data.verse_start,
                    chapter_end=data.chapter_end,
                    verse_end=data.verse_end,
                    title=data.title,
                    text=data.text,
                    score=rrf_score,
                    sources=doc_sources[doc_id],
                )
            )

        return fused_results

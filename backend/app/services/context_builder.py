"""Context builder for RAG pipeline."""

from app.core.config import settings
from app.services.fusion import FusedResult


class ContextBuilder:
    """Builds context from retrieved pericopes for LLM prompting."""

    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens or settings.MAX_CONTEXT_TOKENS
        # Approximate characters per token for Chinese text
        self.chars_per_token = 1.5

    def build(
        self,
        results: list[FusedResult],
        query: str | None = None,
    ) -> str:
        """Build context string from fused results.

        Args:
            results: List of fused retrieval results
            query: Optional query for reference

        Returns:
            Formatted context string for LLM
        """
        if not results:
            return "沒有找到相關經文。"

        max_chars = int(self.max_tokens * self.chars_per_token)
        context_parts = []
        total_chars = 0

        for i, result in enumerate(results):
            # Format pericope
            reference = self._format_reference(result)
            pericope_text = self._format_pericope(result)

            # Check if we have room
            part_length = len(pericope_text)
            if total_chars + part_length > max_chars and context_parts:
                # Stop if we've already added some content and would exceed limit
                break

            context_parts.append(pericope_text)
            total_chars += part_length

        return "\n\n---\n\n".join(context_parts)

    def _format_reference(self, result: FusedResult) -> str:
        """Format book and chapter:verse reference."""
        if result.chapter_start == result.chapter_end:
            if result.verse_start == result.verse_end:
                return f"{result.book_name} {result.chapter_start}:{result.verse_start}"
            return f"{result.book_name} {result.chapter_start}:{result.verse_start}-{result.verse_end}"
        return (
            f"{result.book_name} {result.chapter_start}:{result.verse_start}"
            f"-{result.chapter_end}:{result.verse_end}"
        )

    def _format_pericope(self, result: FusedResult) -> str:
        """Format a single pericope for context."""
        reference = self._format_reference(result)

        # Build formatted text
        lines = [
            f"### {result.title}",
            f"**{reference}**",
            "",
            result.text,
        ]

        return "\n".join(lines)

    def build_with_metadata(
        self,
        results: list[FusedResult],
    ) -> tuple[str, list[dict]]:
        """Build context and return metadata about included pericopes.

        Args:
            results: List of fused retrieval results

        Returns:
            Tuple of (context_string, metadata_list)
        """
        if not results:
            return "沒有找到相關經文。", []

        max_chars = int(self.max_tokens * self.chars_per_token)
        context_parts = []
        metadata = []
        total_chars = 0

        for result in results:
            pericope_text = self._format_pericope(result)
            part_length = len(pericope_text)

            if total_chars + part_length > max_chars and context_parts:
                break

            context_parts.append(pericope_text)
            metadata.append({
                "id": result.id,
                "book": result.book_name,
                "reference": self._format_reference(result),
                "title": result.title,
                "score": result.score,
                "sources": result.sources,
            })
            total_chars += part_length

        context = "\n\n---\n\n".join(context_parts)
        return context, metadata

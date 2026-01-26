"""
Hierarchical Chunker for Bible content

Implements the hierarchical chunking strategy:
- Book > Chapter > Pericope > Chunk
- Chunks are created only when pericope exceeds token limit
- Chunks maintain verse boundaries and overlap
"""

from typing import List, Tuple
from copy import deepcopy

from .config import TOKEN_CONFIG
from .tokenizer_wrapper import count_tokens
from .models import Book, Chapter, Pericope, Chunk, Verse


class HierarchicalChunker:
    """
    Chunks pericopes that exceed the token limit.

    Strategy:
    1. Calculate token count for each pericope
    2. If pericope <= max_tokens: no chunking needed
    3. If pericope > max_tokens: split at verse boundaries with overlap
    """

    def __init__(
        self,
        target_tokens: int = None,
        max_tokens: int = None,
        min_tokens: int = None,
        overlap_verses: int = None,
    ):
        self.target_tokens = target_tokens or TOKEN_CONFIG["target_chunk_tokens"]
        self.max_tokens = max_tokens or TOKEN_CONFIG["max_chunk_tokens"]
        self.min_tokens = min_tokens or TOKEN_CONFIG["min_chunk_tokens"]
        self.overlap_verses = overlap_verses or TOKEN_CONFIG["overlap_verses"]

    def process_book(self, book: Book) -> Book:
        """Process all pericopes in a book and add chunks where needed."""
        for chapter in book.chapters:
            for pericope in chapter.pericopes:
                self._process_pericope(pericope, book.name, chapter.chapter_num)

        return book

    def _process_pericope(
        self, pericope: Pericope, book_name: str, chapter_num: int
    ) -> None:
        """Process a single pericope: calculate tokens and chunk if needed."""
        # Calculate token count for the entire pericope
        token_count = count_tokens(pericope.content_for_embedding)
        pericope.metadata["token_count"] = token_count
        pericope.metadata["char_count"] = len(pericope.content)

        # Determine if chunking is needed
        if token_count <= self.max_tokens:
            pericope.metadata["requires_chunking"] = False
            pericope.metadata["chunk_count"] = 0
            return

        # Chunking required
        pericope.metadata["requires_chunking"] = True
        chunks = self._create_chunks(pericope, book_name, chapter_num)
        pericope.chunks = chunks
        pericope.metadata["chunk_count"] = len(chunks)

    def _create_chunks(
        self, pericope: Pericope, book_name: str, chapter_num: int
    ) -> List[Chunk]:
        """Create chunks from a pericope that exceeds the token limit."""
        chunks = []
        current_verses: List[Verse] = []
        current_tokens = 0

        # Calculate context prefix tokens (will be added to each chunk)
        base_prefix = f"{book_name} 第{chapter_num}章 {pericope.title}"
        prefix_tokens = count_tokens(base_prefix)

        # Effective target = target - prefix overhead
        effective_target = self.target_tokens - prefix_tokens - 20  # Buffer for verse range

        for verse in pericope.verses:
            verse_text = verse.text
            verse_tokens = count_tokens(verse_text)

            # Check if adding this verse would exceed target
            if current_tokens + verse_tokens > effective_target and current_verses:
                # Create chunk from current verses
                chunk = self._create_single_chunk(
                    pericope=pericope,
                    verses=current_verses,
                    chunk_index=len(chunks),
                    book_name=book_name,
                    chapter_num=chapter_num,
                )
                chunks.append(chunk)

                # Start new chunk with overlap
                if self.overlap_verses > 0 and len(current_verses) >= self.overlap_verses:
                    # Keep last N verses for overlap
                    overlap_verses = current_verses[-self.overlap_verses :]
                    current_verses = list(overlap_verses)
                    current_tokens = sum(count_tokens(v.text) for v in current_verses)
                else:
                    current_verses = []
                    current_tokens = 0

            current_verses.append(verse)
            current_tokens += verse_tokens

        # Create final chunk if there are remaining verses
        if current_verses:
            # Check if final chunk is too small, merge with previous if possible
            if (
                len(chunks) > 0
                and current_tokens < self.min_tokens
                and len(current_verses) <= 3
            ):
                # Merge with previous chunk
                prev_chunk = chunks[-1]
                for verse in current_verses:
                    if verse not in prev_chunk.verses:
                        prev_chunk.verses.append(verse)
                # Rebuild previous chunk content
                self._rebuild_chunk_content(
                    prev_chunk, pericope, book_name, chapter_num
                )
            else:
                chunk = self._create_single_chunk(
                    pericope=pericope,
                    verses=current_verses,
                    chunk_index=len(chunks),
                    book_name=book_name,
                    chapter_num=chapter_num,
                )
                chunks.append(chunk)

        # Update total_chunks in all chunk metadata
        for i, chunk in enumerate(chunks):
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks

    def _create_single_chunk(
        self,
        pericope: Pericope,
        verses: List[Verse],
        chunk_index: int,
        book_name: str,
        chapter_num: int,
    ) -> Chunk:
        """Create a single chunk from a list of verses."""
        # Determine verse range
        verse_start = verses[0].verse_start
        verse_end = verses[-1].verse_end
        verse_range = f"{verse_start}-{verse_end}" if verse_start != verse_end else str(verse_start)

        # Build chunk ID
        chunk_id = f"{pericope.id}:{chunk_index}"

        # Build content
        content_parts = []
        for verse in verses:
            content_parts.append(f"**{verse.num}** {verse.text}")
        content = "\n\n".join(content_parts)

        # Build content for embedding
        context_prefix = (
            f"{book_name} 第{chapter_num}章 {pericope.title} ({verse_range}節)："
        )
        plain_verses = [v.text for v in verses]
        content_for_embedding = context_prefix + " ".join(plain_verses)

        # Calculate token count
        token_count = count_tokens(content_for_embedding)

        # Determine overlap
        has_overlap = chunk_index > 0
        overlap_verses = []
        if has_overlap and self.overlap_verses > 0:
            overlap_verses = [v.num for v in verses[: self.overlap_verses]]

        chunk = Chunk(
            id=chunk_id,
            parent_id=pericope.id,
            content=content,
            content_for_embedding=content_for_embedding,
            metadata={
                "book_id": pericope.metadata.get("book_id"),
                "book_name": book_name,
                "chapter_num": chapter_num,
                "pericope_id": pericope.id,
                "pericope_title": pericope.title,
                "verse_range": verse_range,
                "verse_start": verse_start,
                "verse_end": verse_end,
                "chunk_index": chunk_index,
                "total_chunks": 0,  # Will be updated later
                "token_count": token_count,
                "char_count": len(content),
                "has_overlap": has_overlap,
                "overlap_verses": overlap_verses,
            },
            verses=deepcopy(verses),
        )

        return chunk

    def _rebuild_chunk_content(
        self,
        chunk: Chunk,
        pericope: Pericope,
        book_name: str,
        chapter_num: int,
    ) -> None:
        """Rebuild chunk content after merging."""
        verses = chunk.verses
        verse_start = verses[0].verse_start
        verse_end = verses[-1].verse_end
        verse_range = f"{verse_start}-{verse_end}" if verse_start != verse_end else str(verse_start)

        # Rebuild content
        content_parts = []
        for verse in verses:
            content_parts.append(f"**{verse.num}** {verse.text}")
        chunk.content = "\n\n".join(content_parts)

        # Rebuild content for embedding
        context_prefix = (
            f"{book_name} 第{chapter_num}章 {pericope.title} ({verse_range}節)："
        )
        plain_verses = [v.text for v in verses]
        chunk.content_for_embedding = context_prefix + " ".join(plain_verses)

        # Update metadata
        chunk.metadata["verse_range"] = verse_range
        chunk.metadata["verse_end"] = verse_end
        chunk.metadata["token_count"] = count_tokens(chunk.content_for_embedding)
        chunk.metadata["char_count"] = len(chunk.content)


def chunk_book(book: Book) -> Book:
    """Convenience function to chunk a book."""
    chunker = HierarchicalChunker()
    return chunker.process_book(book)

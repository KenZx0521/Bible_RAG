#!/usr/bin/env python3
"""
Bible Processing Pipeline

Processes all Bible markdown files and generates JSONL outputs for:
- Books, Chapters, Pericopes, Chunks (hierarchical structure)
- Embedding queue (items to be embedded)
- Neo4j nodes and relationships (knowledge graph)

Usage:
    python scripts/process_bible.py [OPTIONS]

Options:
    --input-dir DIR    Input markdown directory (default: bible_md)
    --output-dir DIR   Output JSONL directory (default: output)
    --verbose         Show detailed progress
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from bible_chunking.config import BOOK_CONFIG, get_all_book_names
from bible_chunking.markdown_parser import MarkdownParser
from bible_chunking.hierarchical_chunker import HierarchicalChunker
from bible_chunking.models import (
    Book,
    Chapter,
    Pericope,
    Chunk,
    EmbeddingQueueItem,
    Neo4jNode,
    Neo4jRelationship,
)
from bible_chunking.nt_cross_references import (
    SUPPLEMENTARY_CROSS_REFS,
    resolve_pericope_id,
)


class BibleProcessor:
    """Main processor for Bible chunking pipeline."""

    def __init__(self, input_dir: Path, output_dir: Path, verbose: bool = False):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.verbose = verbose
        self.parser = MarkdownParser()
        self.chunker = HierarchicalChunker()
        self.books: List[Book] = []

        # Statistics
        self.stats = {
            "total_books": 0,
            "total_chapters": 0,
            "total_pericopes": 0,
            "total_chunks": 0,
            "pericopes_requiring_chunking": 0,
            "total_embedding_items": 0,
            "total_neo4j_nodes": 0,
            "total_neo4j_relationships": 0,
        }

    def run(self) -> bool:
        """Execute the full processing pipeline."""
        logging.info("Starting Bible processing pipeline...")
        logging.info(f"  Input directory: {self.input_dir}")
        logging.info(f"  Output directory: {self.output_dir}")

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Phase 1: Parse all books
        logging.info("\n[Phase 1] Parsing markdown files...")
        if not self._parse_books():
            return False

        # Phase 2: Chunk oversized pericopes
        logging.info("\n[Phase 2] Processing hierarchical chunking...")
        self._chunk_books()

        # Phase 3: Export JSONL files
        logging.info("\n[Phase 3] Exporting JSONL files...")
        self._export_jsonl()

        # Phase 4: Report statistics
        self._report_statistics()

        logging.info("\nProcessing complete!")
        return True

    def _parse_books(self) -> bool:
        """Parse all markdown files in canonical order."""
        book_names = get_all_book_names()
        parsed_count = 0
        missing_files = []

        for book_name in book_names:
            md_file = self.input_dir / f"{book_name}.md"
            if not md_file.exists():
                missing_files.append(book_name)
                continue

            try:
                book = self.parser.parse_file(md_file)
                self.books.append(book)
                parsed_count += 1
                if self.verbose:
                    logging.info(f"  Parsed: {book_name} ({len(book.chapters)} chapters)")
            except Exception as e:
                logging.error(f"  Error parsing {book_name}: {e}")
                return False

        if missing_files:
            logging.warning(f"  Missing files: {', '.join(missing_files)}")

        logging.info(f"  Successfully parsed {parsed_count} books")
        self.stats["total_books"] = parsed_count
        return True

    def _chunk_books(self) -> None:
        """Apply hierarchical chunking to all books."""
        for book in self.books:
            self.chunker.process_book(book)
            if self.verbose:
                # Count chunks in this book
                chunk_count = sum(
                    len(p.chunks)
                    for c in book.chapters
                    for p in c.pericopes
                    if p.requires_chunking
                )
                if chunk_count > 0:
                    logging.info(f"  {book.name}: {chunk_count} chunks created")

        # Update statistics
        for book in self.books:
            self.stats["total_chapters"] += len(book.chapters)
            for chapter in book.chapters:
                self.stats["total_pericopes"] += len(chapter.pericopes)
                for pericope in chapter.pericopes:
                    if pericope.requires_chunking:
                        self.stats["pericopes_requiring_chunking"] += 1
                        self.stats["total_chunks"] += len(pericope.chunks)

        logging.info(f"  Total pericopes: {self.stats['total_pericopes']}")
        logging.info(f"  Pericopes requiring chunking: {self.stats['pericopes_requiring_chunking']}")
        logging.info(f"  Total chunks created: {self.stats['total_chunks']}")

    def _build_verse_lookup(self) -> Dict[str, str]:
        """
        Build a lookup table: (book_id:chapter:verse_num) -> pericope_id.
        Used to upgrade chapter-level cross-references to pericope-level.
        """
        lookup: Dict[str, str] = {}
        for book in self.books:
            for chapter in book.chapters:
                for pericope in chapter.pericopes:
                    for verse in pericope.verses:
                        for v_num in range(verse.verse_start, verse.verse_end + 1):
                            key = f"{book.id}:{chapter.chapter_num}:{v_num}"
                            lookup[key] = pericope.id
        return lookup

    def _resolve_to_pericope(self, verse_lookup: Dict[str, str],
                              book_id: str, chapter: int,
                              verse_start: int | None) -> str | None:
        """Resolve a (book, chapter, verse) to its pericope ID using the lookup."""
        if verse_start:
            key = f"{book_id}:{chapter}:{verse_start}"
            return verse_lookup.get(key)
        # Fallback: return first pericope in that chapter
        key_prefix = f"{book_id}:{chapter}:"
        for k, v in verse_lookup.items():
            if k.startswith(key_prefix):
                return v
        return None

    def _supplement_cross_references(self, neo4j_relationships: List[Dict],
                                      verse_lookup: Dict[str, str]) -> int:
        """
        Add supplementary NT→OT cross-references from the curated list.
        Returns the number of supplementary relationships added.
        """
        count = 0
        all_pericope_ids = set()
        for book in self.books:
            for chapter in book.chapters:
                for pericope in chapter.pericopes:
                    all_pericope_ids.add(pericope.id)

        for ref in SUPPLEMENTARY_CROSS_REFS:
            source_id = ref.source_pericope_id

            # Resolve target pericope: use first target verse to find actual pericope
            target_base = ref.target_pericope_id  # e.g. "isa:28:0"
            parts = target_base.split(":")
            if len(parts) >= 2:
                t_book_id = parts[0]
                t_chapter = int(parts[1])
                # Parse first target verse
                t_verse = None
                if ref.target_verses:
                    first_v = ref.target_verses.split(",")[0].split("-")[0].strip()
                    if first_v.isdigit():
                        t_verse = int(first_v)
                resolved_target = self._resolve_to_pericope(
                    verse_lookup, t_book_id, t_chapter, t_verse
                )
            else:
                resolved_target = None

            target_id = resolved_target or target_base

            # Only add if both source and target exist as nodes
            if source_id not in all_pericope_ids:
                continue
            if target_id not in all_pericope_ids:
                # Fall back to chapter-level if pericope not found
                target_id = f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else target_id

            neo4j_relationships.append({
                "start": source_id,
                "end": target_id,
                "type": "CROSS_REFERENCES",
                "properties": {
                    "source": "supplementary",
                    "ref_type": ref.ref_type,
                    "source_verses": ref.source_verses,
                    "target_verses": ref.target_verses,
                    "description": ref.description,
                },
            })
            count += 1

        return count

    def _export_jsonl(self) -> None:
        """Export all data to JSONL files."""
        books_data: List[Dict] = []
        chapters_data: List[Dict] = []
        pericopes_data: List[Dict] = []
        chunks_data: List[Dict] = []
        embedding_queue: List[Dict] = []
        neo4j_nodes: List[Dict] = []
        neo4j_relationships: List[Dict] = []

        # Build verse lookup for pericope-level cross-reference resolution
        verse_lookup = self._build_verse_lookup()
        logging.info(f"  Built verse lookup with {len(verse_lookup)} entries")

        prev_book_id = None
        verse_embed_count = 0

        for book in self.books:
            # Export book
            books_data.append(book.model_dump_jsonl())
            neo4j_nodes.append(self._create_book_node(book))

            # Book sequence relationship
            if prev_book_id:
                neo4j_relationships.append({
                    "start": prev_book_id,
                    "end": book.id,
                    "type": "NEXT_BOOK",
                    "properties": {},
                })
            prev_book_id = book.id

            prev_chapter_id = None
            for chapter in book.chapters:
                # Export chapter
                chapters_data.append(chapter.model_dump_jsonl())
                neo4j_nodes.append(self._create_chapter_node(chapter, book))

                # Book contains chapter
                neo4j_relationships.append({
                    "start": book.id,
                    "end": chapter.id,
                    "type": "CONTAINS",
                    "properties": {},
                })

                # Chapter sequence
                if prev_chapter_id:
                    neo4j_relationships.append({
                        "start": prev_chapter_id,
                        "end": chapter.id,
                        "type": "NEXT",
                        "properties": {},
                    })
                prev_chapter_id = chapter.id

                prev_pericope_id = None
                for pericope in chapter.pericopes:
                    # Export pericope
                    pericopes_data.append(pericope.model_dump_jsonl())
                    neo4j_nodes.append(self._create_pericope_node(pericope, book, chapter))

                    # Chapter contains pericope
                    neo4j_relationships.append({
                        "start": chapter.id,
                        "end": pericope.id,
                        "type": "CONTAINS",
                        "properties": {},
                    })

                    # Pericope sequence
                    if prev_pericope_id:
                        neo4j_relationships.append({
                            "start": prev_pericope_id,
                            "end": pericope.id,
                            "type": "NEXT",
                            "properties": {},
                        })
                    prev_pericope_id = pericope.id

                    # Cross-references (upgraded to pericope-level when possible)
                    for cr in pericope.cross_references:
                        if cr.book_id and cr.chapter:
                            # Try to resolve to pericope-level
                            resolved = self._resolve_to_pericope(
                                verse_lookup, cr.book_id, cr.chapter, cr.verse_start
                            )
                            target_id = resolved or f"{cr.book_id}:{cr.chapter}"
                            neo4j_relationships.append({
                                "start": pericope.id,
                                "end": target_id,
                                "type": "CROSS_REFERENCES",
                                "properties": {
                                    "ref_text": cr.reference_text,
                                    "verse_start": cr.verse_start,
                                    "verse_end": cr.verse_end,
                                    "source": "markdown",
                                },
                            })

                    # Embedding queue and chunks
                    if pericope.requires_chunking:
                        # Export chunks, add to embedding queue
                        prev_chunk_id = None
                        for chunk in pericope.chunks:
                            chunks_data.append(chunk.model_dump_jsonl())
                            embedding_queue.append(
                                EmbeddingQueueItem(
                                    id=chunk.id,
                                    type="chunk",
                                    text=chunk.content_for_embedding,
                                ).model_dump_jsonl()
                            )
                            neo4j_nodes.append(self._create_chunk_node(chunk, pericope))

                            # Pericope contains chunk
                            neo4j_relationships.append({
                                "start": pericope.id,
                                "end": chunk.id,
                                "type": "CONTAINS",
                                "properties": {},
                            })

                            # Chunk sequence
                            if prev_chunk_id:
                                neo4j_relationships.append({
                                    "start": prev_chunk_id,
                                    "end": chunk.id,
                                    "type": "NEXT",
                                    "properties": {},
                                })
                            prev_chunk_id = chunk.id
                    else:
                        # Add pericope directly to embedding queue
                        embedding_queue.append(
                            EmbeddingQueueItem(
                                id=pericope.id,
                                type="pericope",
                                text=pericope.content_for_embedding,
                            ).model_dump_jsonl()
                        )

                    # Verse-level embeddings for every verse in the pericope
                    for verse in pericope.verses:
                        verse_id = f"{pericope.id}:v:{verse.num}"
                        verse_text = (
                            f"{book.name} 第{chapter.chapter_num}章 "
                            f"{pericope.title} 第{verse.num}節："
                            f"{verse.text}"
                        )
                        embedding_queue.append(
                            EmbeddingQueueItem(
                                id=verse_id,
                                type="verse",
                                text=verse_text,
                            ).model_dump_jsonl()
                        )
                        verse_embed_count += 1

        # Add supplementary cross-references
        supp_count = self._supplement_cross_references(neo4j_relationships, verse_lookup)
        logging.info(f"  Added {supp_count} supplementary cross-references")
        logging.info(f"  Added {verse_embed_count} verse-level embeddings")

        # Write all JSONL files
        self._write_jsonl("books.jsonl", books_data)
        self._write_jsonl("chapters.jsonl", chapters_data)
        self._write_jsonl("pericopes.jsonl", pericopes_data)
        self._write_jsonl("chunks.jsonl", chunks_data)
        self._write_jsonl("embedding_queue.jsonl", embedding_queue)
        self._write_jsonl("neo4j_nodes.jsonl", neo4j_nodes)
        self._write_jsonl("neo4j_relationships.jsonl", neo4j_relationships)

        # Update statistics
        self.stats["total_embedding_items"] = len(embedding_queue)
        self.stats["total_neo4j_nodes"] = len(neo4j_nodes)
        self.stats["total_neo4j_relationships"] = len(neo4j_relationships)

    def _write_jsonl(self, filename: str, data: List[Dict]) -> None:
        """Write data to a JSONL file."""
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        logging.info(f"  Wrote {len(data)} records to {filename}")

    def _create_book_node(self, book: Book) -> Dict:
        """Create Neo4j node for a book."""
        return {
            "labels": ["Bible", "Book"],
            "properties": {
                "id": book.id,
                "name": book.name,
                "name_en": book.name_en,
                "testament": book.testament,
                "category": book.category,
                "order": book.order,
                "total_chapters": book.total_chapters,
                "total_pericopes": book.total_pericopes,
            },
        }

    def _create_chapter_node(self, chapter: Chapter, book: Book) -> Dict:
        """Create Neo4j node for a chapter."""
        return {
            "labels": ["Bible", "Chapter"],
            "properties": {
                "id": chapter.id,
                "book_id": book.id,
                "book_name": book.name,
                "chapter_num": chapter.chapter_num,
                "total_verses": chapter.total_verses,
                "total_pericopes": chapter.total_pericopes,
            },
        }

    def _create_pericope_node(self, pericope: Pericope, book: Book, chapter: Chapter) -> Dict:
        """Create Neo4j node for a pericope."""
        return {
            "labels": ["Bible", "Pericope"],
            "properties": {
                "id": pericope.id,
                "chapter_id": chapter.id,
                "book_id": book.id,
                "book_name": book.name,
                "chapter_num": chapter.chapter_num,
                "title": pericope.title,
                "verse_range": pericope.verse_range,
                "token_count": pericope.metadata.get("token_count", 0),
                "requires_chunking": pericope.requires_chunking,
            },
        }

    def _create_chunk_node(self, chunk: Chunk, pericope: Pericope) -> Dict:
        """Create Neo4j node for a chunk."""
        return {
            "labels": ["Bible", "Chunk"],
            "properties": {
                "id": chunk.id,
                "pericope_id": pericope.id,
                "pericope_title": pericope.title,
                "chunk_index": chunk.metadata.get("chunk_index", 0),
                "total_chunks": chunk.metadata.get("total_chunks", 1),
                "verse_range": chunk.metadata.get("verse_range", ""),
                "token_count": chunk.metadata.get("token_count", 0),
                "has_overlap": chunk.metadata.get("has_overlap", False),
            },
        }

    def _report_statistics(self) -> None:
        """Print processing statistics."""
        print("\n" + "=" * 60)
        print("Processing Statistics")
        print("=" * 60)
        print(f"  Books processed:              {self.stats['total_books']}")
        print(f"  Total chapters:               {self.stats['total_chapters']}")
        print(f"  Total pericopes:              {self.stats['total_pericopes']}")
        print(f"  Pericopes requiring chunking: {self.stats['pericopes_requiring_chunking']}")
        print(f"  Total chunks created:         {self.stats['total_chunks']}")
        print(f"  Embedding queue items:        {self.stats['total_embedding_items']}")
        print(f"  Neo4j nodes:                  {self.stats['total_neo4j_nodes']}")
        print(f"  Neo4j relationships:          {self.stats['total_neo4j_relationships']}")
        print("=" * 60)

        # Count total verses for verification
        total_verses = sum(b.total_verses for b in self.books)
        expected_pericope_embeds = (
            self.stats["total_pericopes"]
            - self.stats["pericopes_requiring_chunking"]
            + self.stats["total_chunks"]
        )
        expected_total = expected_pericope_embeds + total_verses
        print(f"  Pericope/chunk embeddings:    {expected_pericope_embeds}")
        print(f"  Verse embeddings:             {total_verses}")
        if self.stats["total_embedding_items"] == expected_total:
            print("  Embedding queue count verified!")
        else:
            print(f"  WARNING: Embedding queue mismatch "
                  f"(expected {expected_total}, got {self.stats['total_embedding_items']})")


def main():
    parser = argparse.ArgumentParser(
        description="Process Bible markdown files into JSONL outputs"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("bible_md"),
        help="Input markdown directory (default: bible_md)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Output JSONL directory (default: output)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress",
    )
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
    )

    # Run processor
    processor = BibleProcessor(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        verbose=args.verbose,
    )

    success = processor.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

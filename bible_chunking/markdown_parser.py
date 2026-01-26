"""
Markdown Parser for Bible files

Parses the structured Bible markdown files into hierarchical data structures.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .config import BOOK_CONFIG, CROSS_REF_ABBREV, get_book_config
from .models import (
    Book,
    Chapter,
    Pericope,
    Verse,
    CrossReference,
    Footnote,
)


class CrossRefParser:
    """Parses cross-reference strings like '路3‧23－38' or '可1‧1－8；路3‧1－18'."""

    # Pattern for single reference: 書卷名 + 章‧節（-節）
    SINGLE_REF_PATTERN = re.compile(
        r"([一二三約創出利民申書士得撒王代拉尼斯伯詩箴傳歌賽耶哀結但何珥摩俄拿彌鴻哈番該亞瑪太可路徒羅林加弗腓西帖提多門來雅彼猶啟前後上下]+)"
        r"(\d+)"  # Chapter
        r"[‧·\.]"  # Separator
        r"(\d+)"  # Verse start
        r"(?:[－\-](\d+))?"  # Optional verse end
    )

    @classmethod
    def parse(cls, ref_text: str) -> List[CrossReference]:
        """Parse a cross-reference string into CrossReference objects."""
        refs = []

        # Remove parentheses
        ref_text = ref_text.strip("（）()")

        # Split by semicolon for multiple references
        for part in ref_text.split("；"):
            part = part.strip()
            if not part:
                continue

            match = cls.SINGLE_REF_PATTERN.search(part)
            if match:
                book_abbrev = match.group(1)
                chapter = int(match.group(2))
                verse_start = int(match.group(3))
                verse_end = int(match.group(4)) if match.group(4) else verse_start

                # Look up book ID
                book_id = CROSS_REF_ABBREV.get(book_abbrev)

                refs.append(
                    CrossReference(
                        reference_text=part,
                        book_id=book_id,
                        book_name=book_abbrev,
                        chapter=chapter,
                        verse_start=verse_start,
                        verse_end=verse_end,
                    )
                )
            else:
                # Could not parse, store raw text
                refs.append(CrossReference(reference_text=part))

        return refs


class MarkdownParser:
    """Parses Bible markdown files into structured data."""

    # Regex patterns
    H1_PATTERN = re.compile(r"^# (.+)$")
    H2_PATTERN = re.compile(r"^## 第 (\d+) 章$")
    H3_PATTERN = re.compile(r"^### (.+)$")
    VERSE_PATTERN = re.compile(r"^\*\*(\d+(?:-\d+)?)\*\*\s*(.*)$")
    FOOTNOTE_HEADER_PATTERN = re.compile(r"^\*\*註腳：\*\*$")
    FOOTNOTE_PATTERN = re.compile(r"^- (\d+:\d+): (.+)$")
    SEPARATOR_PATTERN = re.compile(r"^---$")

    # Patterns for special markers
    CROSS_REF_PATTERN = re.compile(r"^（.+）$")  # Cross-reference in parentheses
    SELAH_PATTERN = re.compile(r"^（細拉）$")  # Selah marker
    SPEAKER_PATTERN = re.compile(r"^〔.+〕$")  # Speaker marker like 〔新郎〕

    def __init__(self):
        self.current_book: Optional[Book] = None
        self.current_chapter: Optional[Chapter] = None
        self.current_pericope: Optional[Pericope] = None
        self.current_verse_lines: List[str] = []
        self.current_verse_num: Optional[str] = None
        self.in_footnotes: bool = False
        self.footnote_buffer: List[Footnote] = []

    def parse_file(self, filepath: Path) -> Book:
        """Parse a markdown file and return a Book object."""
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return self.parse_content(content, filepath.stem)

    def parse_content(self, content: str, book_name: str) -> Book:
        """Parse markdown content and return a Book object."""
        # Reset state
        self._reset_state()

        # Get book config
        if book_name not in BOOK_CONFIG:
            raise ValueError(f"Unknown book: {book_name}")

        config = BOOK_CONFIG[book_name]
        self.current_book = Book(
            id=config["id"],
            name=book_name,
            name_en=config["name_en"],
            testament=config["testament"],
            category=config["category"],
            order=config["order"],
        )

        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            i = self._process_line(line, lines, i)
            i += 1

        # Finalize any remaining content
        self._finalize_verse()
        self._finalize_pericope()
        self._finalize_chapter()

        return self.current_book

    def _reset_state(self):
        """Reset parser state."""
        self.current_book = None
        self.current_chapter = None
        self.current_pericope = None
        self.current_verse_lines = []
        self.current_verse_num = None
        self.in_footnotes = False
        self.footnote_buffer = []

    def _process_line(self, line: str, lines: List[str], index: int) -> int:
        """Process a single line. Returns the new index (for look-ahead)."""
        line_stripped = line.strip()

        # Check for separator (footnotes section)
        if self.SEPARATOR_PATTERN.match(line_stripped):
            self.in_footnotes = True
            self._finalize_verse()
            return index

        # H2 - Chapter (check before footnotes to handle chapter after footnotes)
        h2_match = self.H2_PATTERN.match(line_stripped)
        if h2_match:
            # Exit footnotes mode if we were in it
            self.in_footnotes = False
            self._finalize_verse()
            self._finalize_pericope()
            self._finalize_chapter()
            chapter_num = int(h2_match.group(1))
            self._start_chapter(chapter_num)
            return index

        # In footnotes section
        if self.in_footnotes:
            return self._process_footnote_line(line_stripped, index)

        # H1 - Book title (skip, we already have it)
        if self.H1_PATTERN.match(line_stripped):
            return index

        # H2 already handled above
        # (This check is removed since H2 is now handled before footnotes check)
            self._finalize_verse()
            self._finalize_pericope()
            self._finalize_chapter()
            chapter_num = int(h2_match.group(1))
            self._start_chapter(chapter_num)
            return index

        # H3 - Section title or cross-reference
        h3_match = self.H3_PATTERN.match(line_stripped)
        if h3_match:
            title = h3_match.group(1)
            return self._process_h3(title, lines, index)

        # Verse
        verse_match = self.VERSE_PATTERN.match(line_stripped)
        if verse_match:
            self._finalize_verse()
            verse_num = verse_match.group(1)
            verse_text = verse_match.group(2)
            self._start_verse(verse_num, verse_text)
            return index

        # Continuation of verse (poetry lines or additional content)
        if line_stripped and self.current_verse_num is not None:
            # Check for speaker marker
            if self.SPEAKER_PATTERN.match(line_stripped):
                # Speaker markers are not part of verse content
                return index
            self.current_verse_lines.append(line_stripped)

        return index

    def _process_h3(self, title: str, lines: List[str], index: int) -> int:
        """Process H3 header (section title or cross-reference)."""
        # Check if this is a cross-reference
        if self.CROSS_REF_PATTERN.match(title):
            # This is a cross-reference for the previous pericope
            if self.current_pericope:
                refs = CrossRefParser.parse(title)
                self.current_pericope.cross_references.extend(refs)
            return index

        # Check if this is Selah
        if self.SELAH_PATTERN.match(title):
            # Selah is a musical marker, not a real pericope
            # We can skip it or handle specially
            return index

        # This is a new pericope
        self._finalize_verse()
        self._finalize_pericope()
        self._start_pericope(title)

        return index

    def _process_footnote_line(self, line: str, index: int) -> int:
        """Process a line in the footnotes section."""
        if self.FOOTNOTE_HEADER_PATTERN.match(line):
            return index

        fn_match = self.FOOTNOTE_PATTERN.match(line)
        if fn_match:
            self.footnote_buffer.append(
                Footnote(verse_ref=fn_match.group(1), text=fn_match.group(2))
            )
        return index

    def _start_chapter(self, chapter_num: int):
        """Start a new chapter."""
        chapter_id = f"{self.current_book.id}:{chapter_num}"
        self.current_chapter = Chapter(
            id=chapter_id,
            parent_id=self.current_book.id,
            chapter_num=chapter_num,
            metadata={
                "book_id": self.current_book.id,
                "book_name": self.current_book.name,
            },
        )
        self.in_footnotes = False
        self.footnote_buffer = []

    def _start_pericope(self, title: str):
        """Start a new pericope."""
        if not self.current_chapter:
            return

        pericope_index = len(self.current_chapter.pericopes)
        pericope_id = f"{self.current_chapter.id}:{pericope_index}"

        self.current_pericope = Pericope(
            id=pericope_id,
            parent_id=self.current_chapter.id,
            title=title,
            content="",
            content_for_embedding="",
            metadata={
                "book_id": self.current_book.id,
                "book_name": self.current_book.name,
                "chapter_num": self.current_chapter.chapter_num,
                "pericope_index": pericope_index,
            },
        )

    def _start_verse(self, verse_num: str, verse_text: str):
        """Start a new verse."""
        self.current_verse_num = verse_num
        self.current_verse_lines = [verse_text] if verse_text else []

    def _finalize_verse(self):
        """Finalize the current verse and add it to the pericope."""
        if self.current_verse_num is None:
            return

        if not self.current_pericope:
            # Create a default pericope if none exists
            if self.current_chapter:
                self._start_pericope("(無標題)")

        if self.current_pericope:
            # Join lines and detect poetry
            full_text = "\n".join(self.current_verse_lines)
            is_poetry = len(self.current_verse_lines) > 1

            verse = Verse(
                num=self.current_verse_num,
                text=full_text.replace("\n", " ") if not is_poetry else full_text,
                is_poetry=is_poetry,
                lines=self.current_verse_lines if is_poetry else [],
            )
            self.current_pericope.verses.append(verse)

        self.current_verse_num = None
        self.current_verse_lines = []

    def _finalize_pericope(self):
        """Finalize the current pericope and add it to the chapter."""
        if not self.current_pericope:
            return

        if not self.current_pericope.verses:
            # Empty pericope, skip
            self.current_pericope = None
            return

        # Build content
        content_parts = []
        for verse in self.current_pericope.verses:
            content_parts.append(f"**{verse.num}** {verse.text}")

        self.current_pericope.content = "\n\n".join(content_parts)

        # Build content for embedding with context prefix
        verse_range = self.current_pericope.verse_range
        context_prefix = (
            f"{self.current_book.name} 第{self.current_chapter.chapter_num}章 "
            f"{self.current_pericope.title}"
        )
        if verse_range:
            context_prefix += f" ({verse_range}節)"
        context_prefix += "："

        # For embedding, use plain text without markdown
        plain_verses = []
        for verse in self.current_pericope.verses:
            plain_verses.append(verse.text)
        self.current_pericope.content_for_embedding = (
            context_prefix + " ".join(plain_verses)
        )

        # Update metadata
        self.current_pericope.metadata["verse_range"] = verse_range
        self.current_pericope.metadata["verse_start"] = (
            self.current_pericope.verses[0].verse_start
        )
        self.current_pericope.metadata["verse_end"] = (
            self.current_pericope.verses[-1].verse_end
        )
        self.current_pericope.metadata["is_poetry"] = any(
            v.is_poetry for v in self.current_pericope.verses
        )

        # Add to chapter
        self.current_chapter.pericopes.append(self.current_pericope)
        self.current_pericope = None

    def _finalize_chapter(self):
        """Finalize the current chapter and add it to the book."""
        if not self.current_chapter:
            return

        # Add footnotes to chapter
        self.current_chapter.footnotes = self.footnote_buffer
        self.footnote_buffer = []

        # Update metadata
        self.current_chapter.metadata["total_verses"] = self.current_chapter.total_verses
        self.current_chapter.metadata["total_pericopes"] = (
            self.current_chapter.total_pericopes
        )
        self.current_chapter.metadata["has_footnotes"] = bool(
            self.current_chapter.footnotes
        )

        # Add to book
        self.current_book.chapters.append(self.current_chapter)
        self.current_chapter = None
        self.in_footnotes = False

"""Bible PDF parser using pdfplumber.

This module parses the Chinese Union Version Bible PDF and extracts:
- Books (書卷)
- Chapters (章)
- Pericopes (段落單元)
- Verses (經文節)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber


@dataclass
class ParsedVerse:
    """Parsed verse data."""

    chapter: int
    verse: int
    text: str


@dataclass
class ParsedPericope:
    """Parsed pericope (passage unit) data."""

    title: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    verses: list[ParsedVerse] = field(default_factory=list)


@dataclass
class ParsedChapter:
    """Parsed chapter data."""

    number: int
    pericopes: list[ParsedPericope] = field(default_factory=list)


@dataclass
class ParsedBook:
    """Parsed book data."""

    name_zh: str
    abbrev_zh: str
    testament: str  # 'OT' or 'NT'
    order_index: int
    chapters: list[ParsedChapter] = field(default_factory=list)


# Bible book metadata (Traditional Chinese)
BIBLE_BOOKS = [
    # Old Testament (OT)
    {"name_zh": "創世記", "abbrev_zh": "創", "testament": "OT"},
    {"name_zh": "出埃及記", "abbrev_zh": "出", "testament": "OT"},
    {"name_zh": "利未記", "abbrev_zh": "利", "testament": "OT"},
    {"name_zh": "民數記", "abbrev_zh": "民", "testament": "OT"},
    {"name_zh": "申命記", "abbrev_zh": "申", "testament": "OT"},
    {"name_zh": "約書亞記", "abbrev_zh": "書", "testament": "OT"},
    {"name_zh": "士師記", "abbrev_zh": "士", "testament": "OT"},
    {"name_zh": "路得記", "abbrev_zh": "得", "testament": "OT"},
    {"name_zh": "撒母耳記上", "abbrev_zh": "撒上", "testament": "OT"},
    {"name_zh": "撒母耳記下", "abbrev_zh": "撒下", "testament": "OT"},
    {"name_zh": "列王紀上", "abbrev_zh": "王上", "testament": "OT"},
    {"name_zh": "列王紀下", "abbrev_zh": "王下", "testament": "OT"},
    {"name_zh": "歷代志上", "abbrev_zh": "代上", "testament": "OT"},
    {"name_zh": "歷代志下", "abbrev_zh": "代下", "testament": "OT"},
    {"name_zh": "以斯拉記", "abbrev_zh": "拉", "testament": "OT"},
    {"name_zh": "尼希米記", "abbrev_zh": "尼", "testament": "OT"},
    {"name_zh": "以斯帖記", "abbrev_zh": "斯", "testament": "OT"},
    {"name_zh": "約伯記", "abbrev_zh": "伯", "testament": "OT"},
    {"name_zh": "詩篇", "abbrev_zh": "詩", "testament": "OT"},
    {"name_zh": "箴言", "abbrev_zh": "箴", "testament": "OT"},
    {"name_zh": "傳道書", "abbrev_zh": "傳", "testament": "OT"},
    {"name_zh": "雅歌", "abbrev_zh": "歌", "testament": "OT"},
    {"name_zh": "以賽亞書", "abbrev_zh": "賽", "testament": "OT"},
    {"name_zh": "耶利米書", "abbrev_zh": "耶", "testament": "OT"},
    {"name_zh": "耶利米哀歌", "abbrev_zh": "哀", "testament": "OT"},
    {"name_zh": "以西結書", "abbrev_zh": "結", "testament": "OT"},
    {"name_zh": "但以理書", "abbrev_zh": "但", "testament": "OT"},
    {"name_zh": "何西阿書", "abbrev_zh": "何", "testament": "OT"},
    {"name_zh": "約珥書", "abbrev_zh": "珥", "testament": "OT"},
    {"name_zh": "阿摩司書", "abbrev_zh": "摩", "testament": "OT"},
    {"name_zh": "俄巴底亞書", "abbrev_zh": "俄", "testament": "OT"},
    {"name_zh": "約拿書", "abbrev_zh": "拿", "testament": "OT"},
    {"name_zh": "彌迦書", "abbrev_zh": "彌", "testament": "OT"},
    {"name_zh": "那鴻書", "abbrev_zh": "鴻", "testament": "OT"},
    {"name_zh": "哈巴谷書", "abbrev_zh": "哈", "testament": "OT"},
    {"name_zh": "西番雅書", "abbrev_zh": "番", "testament": "OT"},
    {"name_zh": "哈該書", "abbrev_zh": "該", "testament": "OT"},
    {"name_zh": "撒迦利亞書", "abbrev_zh": "亞", "testament": "OT"},
    {"name_zh": "瑪拉基書", "abbrev_zh": "瑪", "testament": "OT"},
    # New Testament (NT)
    {"name_zh": "馬太福音", "abbrev_zh": "太", "testament": "NT"},
    {"name_zh": "馬可福音", "abbrev_zh": "可", "testament": "NT"},
    {"name_zh": "路加福音", "abbrev_zh": "路", "testament": "NT"},
    {"name_zh": "約翰福音", "abbrev_zh": "約", "testament": "NT"},
    {"name_zh": "使徒行傳", "abbrev_zh": "徒", "testament": "NT"},
    {"name_zh": "羅馬書", "abbrev_zh": "羅", "testament": "NT"},
    {"name_zh": "哥林多前書", "abbrev_zh": "林前", "testament": "NT"},
    {"name_zh": "哥林多後書", "abbrev_zh": "林後", "testament": "NT"},
    {"name_zh": "加拉太書", "abbrev_zh": "加", "testament": "NT"},
    {"name_zh": "以弗所書", "abbrev_zh": "弗", "testament": "NT"},
    {"name_zh": "腓立比書", "abbrev_zh": "腓", "testament": "NT"},
    {"name_zh": "歌羅西書", "abbrev_zh": "西", "testament": "NT"},
    {"name_zh": "帖撒羅尼迦前書", "abbrev_zh": "帖前", "testament": "NT"},
    {"name_zh": "帖撒羅尼迦後書", "abbrev_zh": "帖後", "testament": "NT"},
    {"name_zh": "提摩太前書", "abbrev_zh": "提前", "testament": "NT"},
    {"name_zh": "提摩太後書", "abbrev_zh": "提後", "testament": "NT"},
    {"name_zh": "提多書", "abbrev_zh": "多", "testament": "NT"},
    {"name_zh": "腓利門書", "abbrev_zh": "門", "testament": "NT"},
    {"name_zh": "希伯來書", "abbrev_zh": "來", "testament": "NT"},
    {"name_zh": "雅各書", "abbrev_zh": "雅", "testament": "NT"},
    {"name_zh": "彼得前書", "abbrev_zh": "彼前", "testament": "NT"},
    {"name_zh": "彼得後書", "abbrev_zh": "彼後", "testament": "NT"},
    {"name_zh": "約翰一書", "abbrev_zh": "約一", "testament": "NT"},
    {"name_zh": "約翰二書", "abbrev_zh": "約二", "testament": "NT"},
    {"name_zh": "約翰三書", "abbrev_zh": "約三", "testament": "NT"},
    {"name_zh": "猶大書", "abbrev_zh": "猶", "testament": "NT"},
    {"name_zh": "啟示錄", "abbrev_zh": "啟", "testament": "NT"},
]

# Build lookup dictionaries
BOOK_NAMES = {b["name_zh"] for b in BIBLE_BOOKS}
BOOK_NAME_TO_INFO = {b["name_zh"]: b for b in BIBLE_BOOKS}


class BiblePDFParser:
    """Parser for Chinese Union Version Bible PDF."""

    # Patterns for identifying elements
    # Verse: number directly followed by Chinese text (e.g., "1起初，上帝創造天地。")
    VERSE_PATTERN = re.compile(r"^(\d+)([^\d\s].+)")
    # Chapter: standalone number at start of line (e.g., "2" indicating chapter 2)
    CHAPTER_PATTERN = re.compile(r"^(\d+)$")
    # Pericope title: Chinese text, 2-30 chars, no numbers (e.g., "上帝的創造")
    PERICOPE_PATTERN = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\s，、：；！？「」『』（）]{1,29}$")
    # Page header pattern to skip (e.g., "創世記1:1 1 創世記2:2")
    PAGE_HEADER_PATTERN = re.compile(r"^[\u4e00-\u9fff]+\d+:\d+")

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        self.books: list[ParsedBook] = []
        self.current_book: ParsedBook | None = None
        self.current_chapter: int = 0
        self.current_pericope: ParsedPericope | None = None
        self.last_verse_num: int = 0  # Track last verse number for chapter detection

    def parse(self) -> list[ParsedBook]:
        """Parse the entire Bible PDF."""
        print(f"Opening PDF: {self.pdf_path}")

        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Total pages: {total_pages}")

            for page_num, page in enumerate(pdf.pages, 1):
                if page_num % 100 == 0:
                    print(f"Processing page {page_num}/{total_pages}...")

                self._parse_page(page)

        # Finalize last book
        self._finalize_current_book()

        print(f"Parsed {len(self.books)} books")
        return self.books

    def _parse_page(self, page: pdfplumber.page.Page) -> None:
        """Parse a single page."""
        text = page.extract_text()
        if not text:
            return

        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            self._parse_line(line)

    def _parse_line(self, line: str) -> None:
        """Parse a single line and update state."""
        # Skip page headers (e.g., "創世記1:1 1 創世記2:2")
        if self.PAGE_HEADER_PATTERN.match(line):
            return

        # Skip table of contents lines with page numbers
        if re.match(r"^[\u4e00-\u9fff]+\s*\.+\s*\d+$", line):
            return

        # Skip Roman numerals (table of contents page numbers)
        if re.match(r"^[ivxlcdm]+$", line.lower()):
            return

        # Check for book title
        if line in BOOK_NAMES:
            self._handle_book_title(line)
            return

        # Check for standalone chapter number (e.g., "2" on its own line)
        chapter_match = self.CHAPTER_PATTERN.match(line)
        if chapter_match:
            chapter_num = int(chapter_match.group(1))
            # Only treat as chapter if it's a reasonable chapter number
            # and we're in a book context
            if self.current_book and 1 <= chapter_num <= 150:
                self._handle_chapter(chapter_num)
            return

        # Check for verse (number directly followed by text)
        verse_match = self.VERSE_PATTERN.match(line)
        if verse_match:
            verse_num = int(verse_match.group(1))
            verse_text = verse_match.group(2).strip()

            # Skip footnotes (format like ":1:就是得的意思")
            if verse_text.startswith(":") or verse_text.startswith("："):
                return

            # Detect chapter change: if verse 1 appears after a higher verse number
            # and we don't have a chapter yet, start chapter 1
            if self.current_book and self.current_chapter == 0 and verse_num == 1:
                self._handle_chapter(1)

            self._handle_verse(verse_num, verse_text)
            return

        # Check for pericope title (Chinese text without numbers)
        if self.current_book and self.PERICOPE_PATTERN.match(line):
            # Additional validation: not too short, not a book name
            if 2 <= len(line) <= 30 and line not in BOOK_NAMES:
                self._handle_pericope_title(line)

    def _handle_book_title(self, name: str) -> None:
        """Handle book title detection."""
        # Finalize previous book
        self._finalize_current_book()

        # Start new book
        info = BOOK_NAME_TO_INFO[name]
        order_index = BIBLE_BOOKS.index(info) + 1
        self.current_book = ParsedBook(
            name_zh=name,
            abbrev_zh=info["abbrev_zh"],
            testament=info["testament"],
            order_index=order_index,
        )
        self.current_chapter = 0
        self.current_pericope = None
        self.last_verse_num = 0
        print(f"  Found book: {name}")

    def _handle_chapter(self, chapter_num: int) -> None:
        """Handle chapter marker."""
        if not self.current_book:
            return

        # Finalize previous pericope
        self._finalize_current_pericope()

        self.current_chapter = chapter_num
        self.last_verse_num = 0

    def _handle_pericope_title(self, title: str) -> None:
        """Handle pericope title."""
        if not self.current_book or self.current_chapter == 0:
            return

        # Finalize previous pericope
        self._finalize_current_pericope()

        # Start new pericope
        self.current_pericope = ParsedPericope(
            title=title,
            chapter_start=self.current_chapter,
            verse_start=0,  # Will be set when first verse is added
            chapter_end=self.current_chapter,
            verse_end=0,
        )

    def _handle_verse(self, verse_num: int, text: str) -> None:
        """Handle verse."""
        if not self.current_book or self.current_chapter == 0:
            return

        verse = ParsedVerse(
            chapter=self.current_chapter,
            verse=verse_num,
            text=text,
        )

        # Create default pericope if needed
        if not self.current_pericope:
            self.current_pericope = ParsedPericope(
                title=f"第{self.current_chapter}章",
                chapter_start=self.current_chapter,
                verse_start=verse_num,
                chapter_end=self.current_chapter,
                verse_end=verse_num,
            )

        # Update pericope range
        if self.current_pericope.verse_start == 0:
            self.current_pericope.verse_start = verse_num
        self.current_pericope.verse_end = verse_num
        self.current_pericope.chapter_end = self.current_chapter

        # Add verse
        self.current_pericope.verses.append(verse)

        # Track last verse number
        self.last_verse_num = verse_num

    def _finalize_current_pericope(self) -> None:
        """Finalize and store current pericope."""
        if not self.current_pericope or not self.current_pericope.verses:
            self.current_pericope = None
            return

        if not self.current_book:
            return

        # Find or create chapter
        chapter = None
        for ch in self.current_book.chapters:
            if ch.number == self.current_pericope.chapter_start:
                chapter = ch
                break

        if not chapter:
            chapter = ParsedChapter(number=self.current_pericope.chapter_start)
            self.current_book.chapters.append(chapter)

        # Add pericope to chapter
        chapter.pericopes.append(self.current_pericope)
        self.current_pericope = None

    def _finalize_current_book(self) -> None:
        """Finalize and store current book."""
        self._finalize_current_pericope()

        if self.current_book and self.current_book.chapters:
            self.books.append(self.current_book)

        self.current_book = None

    def to_dict(self) -> dict[str, Any]:
        """Convert parsed data to dictionary."""
        total_verses = 0
        total_pericopes = 0

        books_data = []
        for book in self.books:
            chapters_data = []
            for chapter in book.chapters:
                pericopes_data = []
                for pericope in chapter.pericopes:
                    verses_data = [
                        {
                            "chapter": v.chapter,
                            "verse": v.verse,
                            "text": v.text,
                        }
                        for v in pericope.verses
                    ]
                    total_verses += len(verses_data)

                    pericopes_data.append({
                        "title": pericope.title,
                        "chapter_start": pericope.chapter_start,
                        "verse_start": pericope.verse_start,
                        "chapter_end": pericope.chapter_end,
                        "verse_end": pericope.verse_end,
                        "verses": verses_data,
                    })
                    total_pericopes += 1

                chapters_data.append({
                    "number": chapter.number,
                    "pericopes": pericopes_data,
                })

            books_data.append({
                "name_zh": book.name_zh,
                "abbrev_zh": book.abbrev_zh,
                "testament": book.testament,
                "order_index": book.order_index,
                "chapters": chapters_data,
            })

        return {
            "metadata": {
                "total_books": len(self.books),
                "total_pericopes": total_pericopes,
                "total_verses": total_verses,
            },
            "books": books_data,
        }

    def save_json(self, output_path: str | Path) -> None:
        """Save parsed data to JSON file."""
        output_path = Path(output_path)
        data = self.to_dict()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"Saved to {output_path}")
        print(f"  Books: {data['metadata']['total_books']}")
        print(f"  Pericopes: {data['metadata']['total_pericopes']}")
        print(f"  Verses: {data['metadata']['total_verses']}")


def main():
    """Main entry point for PDF parsing."""
    import argparse

    parser = argparse.ArgumentParser(description="Parse Bible PDF to JSON")
    parser.add_argument("pdf_path", help="Path to Bible PDF file")
    parser.add_argument(
        "-o", "--output",
        default="bible_parsed.json",
        help="Output JSON file path",
    )
    args = parser.parse_args()

    # Parse PDF
    pdf_parser = BiblePDFParser(args.pdf_path)
    pdf_parser.parse()

    # Save to JSON
    pdf_parser.save_json(args.output)


if __name__ == "__main__":
    main()

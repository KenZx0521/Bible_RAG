"""
Parse bible_md/*.md files into structured pericope data.

Each markdown follows:
  # BookName
  ## 第 N 章
  ### Pericope Title
  **verse_num** verse text ...
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Regex patterns
RE_BOOK = re.compile(r"^# (.+)$")
RE_CHAPTER = re.compile(r"^## 第 (\d+) 章$")
RE_PERICOPE = re.compile(r"^### (.+)$")
RE_VERSE = re.compile(r"^\*\*(\d+)\*\* (.+)$")
RE_CROSS_REF_TITLE = re.compile(r"^（.*[‧·].*）$")
RE_FOOTNOTE_SEP = re.compile(r"^---$")


@dataclass
class PericopeData:
    """Structured pericope parsed from bible_md."""
    book: str
    chapter: int
    title: str
    verses: List[str] = field(default_factory=list)
    verse_numbers: List[int] = field(default_factory=list)
    source_id: str = ""

    @property
    def full_text(self) -> str:
        return " ".join(self.verses)


def parse_bible_md(md_path: Path) -> List[PericopeData]:
    """Parse a single bible_md markdown file into PericopeData list."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    pericopes: List[PericopeData] = []
    book = ""
    chapter = 0
    current: PericopeData | None = None
    in_footnote = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Footnote separator: skip everything until next heading
        if RE_FOOTNOTE_SEP.match(stripped):
            in_footnote = True
            continue

        # Book title
        m = RE_BOOK.match(stripped)
        if m:
            book = m.group(1)
            in_footnote = False
            continue

        # Chapter heading
        m = RE_CHAPTER.match(stripped)
        if m:
            chapter = int(m.group(1))
            in_footnote = False
            continue

        # Pericope heading
        m = RE_PERICOPE.match(stripped)
        if m:
            in_footnote = False
            title = m.group(1).strip()
            # Skip cross-reference titles like （士1‧11－15）
            if RE_CROSS_REF_TITLE.match(title):
                continue
            # Save previous pericope
            if current and current.verses:
                pericopes.append(current)
            source_id = f"{book}:{chapter}:{title}"
            current = PericopeData(
                book=book,
                chapter=chapter,
                title=title,
                source_id=source_id,
            )
            continue

        if in_footnote:
            continue

        # Verse
        m = RE_VERSE.match(stripped)
        if m and current is not None:
            vnum = int(m.group(1))
            vtext = m.group(2)
            current.verse_numbers.append(vnum)
            current.verses.append(vtext)

    # Don't forget last pericope
    if current and current.verses:
        pericopes.append(current)

    return pericopes


def parse_all_bible_md(bible_md_dir: Path) -> List[PericopeData]:
    """Parse all 66 bible_md markdown files."""
    all_pericopes: List[PericopeData] = []
    md_files = sorted(bible_md_dir.glob("*.md"))

    if not md_files:
        logger.warning(f"No .md files found in {bible_md_dir}")
        return all_pericopes

    for md_file in md_files:
        pericopes = parse_bible_md(md_file)
        all_pericopes.extend(pericopes)
        logger.debug(f"Parsed {md_file.name}: {len(pericopes)} pericopes")

    logger.info(f"Parsed {len(md_files)} books, {len(all_pericopes)} total pericopes")
    return all_pericopes

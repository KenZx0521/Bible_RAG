"""
Regex-based Bible verse reference parser.
Parses Chinese verse references like: 羅馬書3:23, 羅3:23, 創世記第1章, 約翰福音3章16節
Reuses BOOK_CONFIG and CROSS_REF_ABBREV from bible_chunking.config.
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass

# Add project root to path so we can import bible_chunking
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from bible_chunking.config import BOOK_CONFIG, CROSS_REF_ABBREV, get_book_by_id


@dataclass
class VerseRef:
    book_id: str
    book_name: str
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None

    @property
    def display(self) -> str:
        s = f"{self.book_name}{self.chapter}"
        if self.verse_start is not None:
            s += f":{self.verse_start}"
            if self.verse_end is not None and self.verse_end != self.verse_start:
                s += f"-{self.verse_end}"
        return s


# Build lookup: full name -> book_id
_FULL_NAME_TO_ID: dict[str, str] = {
    name: cfg["id"] for name, cfg in BOOK_CONFIG.items()
}

# Build lookup: abbreviation -> (book_id, full_name)
_ABBREV_TO_ID: dict[str, str] = dict(CROSS_REF_ABBREV)

# Sort by length descending for greedy matching
_ALL_NAMES = sorted(
    list(_FULL_NAME_TO_ID.keys()) + list(_ABBREV_TO_ID.keys()),
    key=len,
    reverse=True,
)

# Escape names for regex
_NAMES_PATTERN = "|".join(re.escape(n) for n in _ALL_NAMES)

# Pattern: (書名)(第?)(章數)(章)?(：|:)?(節數)?(-節數)?節?
_VERSE_PATTERN = re.compile(
    rf"({_NAMES_PATTERN})"         # group 1: book name/abbrev
    r"(?:第)?"                      # optional 第
    r"(\d+)"                        # group 2: chapter number
    r"(?:章)?"                      # optional 章
    r"(?:[：:])?"                   # optional : or ：
    r"(\d+)?"                       # group 3: verse start (optional)
    r"(?:[—\-–](\d+))?"            # group 4: verse end (optional)
    r"(?:節)?"                      # optional 節
)


def _resolve_book(name_or_abbrev: str) -> tuple[str, str] | None:
    """Resolve a book name or abbreviation to (book_id, full_chinese_name)."""
    # Try full name first
    if name_or_abbrev in _FULL_NAME_TO_ID:
        return _FULL_NAME_TO_ID[name_or_abbrev], name_or_abbrev

    # Try abbreviation
    if name_or_abbrev in _ABBREV_TO_ID:
        book_id = _ABBREV_TO_ID[name_or_abbrev]
        book_info = get_book_by_id(book_id)
        full_name = book_info["name"] if book_info else name_or_abbrev
        return book_id, full_name

    return None


def parse_verse_references(text: str) -> list[VerseRef]:
    """
    Parse all verse references found in the text.

    Examples:
        "羅馬書3:23" -> [VerseRef(book_id='rom', chapter=3, verse_start=23)]
        "羅3:23-24" -> [VerseRef(book_id='rom', chapter=3, verse_start=23, verse_end=24)]
        "創世記第1章" -> [VerseRef(book_id='gen', chapter=1)]
        "約翰福音3章16節" -> [VerseRef(book_id='jhn', chapter=3, verse_start=16)]
    """
    refs = []
    for match in _VERSE_PATTERN.finditer(text):
        name_or_abbrev = match.group(1)
        chapter = int(match.group(2))
        verse_start = int(match.group(3)) if match.group(3) else None
        verse_end = int(match.group(4)) if match.group(4) else None

        resolved = _resolve_book(name_or_abbrev)
        if not resolved:
            continue

        book_id, full_name = resolved
        refs.append(VerseRef(
            book_id=book_id,
            book_name=full_name,
            chapter=chapter,
            verse_start=verse_start,
            verse_end=verse_end,
        ))

    return refs


def has_verse_reference(text: str) -> bool:
    """Quick check if text contains any verse reference."""
    return bool(_VERSE_PATTERN.search(text))

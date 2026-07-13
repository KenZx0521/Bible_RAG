"""
Parse Chinese Bible reference strings into structured ParsedReference objects.

Supported formats:
  - "約翰福音 3:16"           → single verse
  - "詩篇 23:1-3"             → verse range
  - "創世記 6-9章"             → chapter range
  - "路加福音 10章; 約翰福音 11-12章"  → semicolon / comma separated
  - "出埃及記 2-4章, 18章"     → comma within same book
  - "以斯拉記; 尼希米記"       → whole books
  - "詩篇 22篇; 馬太福音 27:35-46" → mixed
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .models import ParsedReference

# Import BOOK_CONFIG from bible_chunking
_BIBLE_CHUNKING = Path(__file__).resolve().parent.parent.parent / "bible_chunking"
if str(_BIBLE_CHUNKING) not in sys.path:
    sys.path.insert(0, str(_BIBLE_CHUNKING))

from config import BOOK_CONFIG  # type: ignore

# Alias mapping for variant Chinese names
_BOOK_ALIASES: dict[str, str] = {
    "尼希米記": "尼西米記",
}


def _normalize_book_name(name: str) -> str:
    return _BOOK_ALIASES.get(name, name)


def _get_book_id(book_name: str) -> str | None:
    normalized = _normalize_book_name(book_name)
    cfg = BOOK_CONFIG.get(normalized)
    return cfg["id"] if cfg else None


def _extract_book_and_rest(text: str) -> tuple[str | None, str]:
    """Match the longest known book name at the start of *text* and return (name, rest)."""
    text = text.strip()
    # Try aliases first (longest match)
    all_names = list(BOOK_CONFIG.keys()) + list(_BOOK_ALIASES.keys())
    candidates = sorted(set(all_names), key=len, reverse=True)
    for name in candidates:
        if text.startswith(name):
            return name, text[len(name):].strip()
    return None, text


# Regex pieces
_CHAP_RANGE = re.compile(r"^(\d+)\s*[-–]\s*(\d+)\s*[章篇]?$")
_SINGLE_CHAP = re.compile(r"^(\d+)\s*[章篇]$")
_CROSS_CHAP_VERSE_RANGE = re.compile(r"^(\d+)\s*:\s*(\d+)\s*[-–]\s*(\d+)\s*:\s*(\d+)$")
_CHAP_VERSE_RANGE = re.compile(r"^(\d+)\s*:\s*(\d+)\s*[-–]\s*(\d+)$")
_CHAP_VERSE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
_CHAPTER_ONLY = re.compile(r"^(\d+)$")


def _parse_single_ref(book_name: str, spec: str) -> list[ParsedReference]:
    """Parse a reference spec (everything after the book name) for one book.

    Returns a list because a cross-chapter verse range ("1:17-2:10") expands
    into multiple ParsedReference units (head partial chapter, whole middle
    chapters, tail partial chapter).
    """
    book_id = _get_book_id(book_name) or book_name
    spec = spec.strip().lstrip("第").strip()

    if not spec:
        return [ParsedReference(book_name=book_name, book_id=book_id, is_whole_book=True)]

    # "6-9章" / "120-134篇" → chapter range
    m = _CHAP_RANGE.match(spec)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        return [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=list(range(start, end + 1)),
        )]

    # "10章" → single chapter
    m = _SINGLE_CHAP.match(spec)
    if m:
        return [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[int(m.group(1))],
        )]

    # "1:17-2:10" → cross-chapter verse range
    m = _CROSS_CHAP_VERSE_RANGE.match(spec)
    if m:
        c1, v1, c2, v2 = (int(g) for g in m.groups())
        if c1 == c2:
            return [ParsedReference(
                book_name=book_name, book_id=book_id,
                chapters=[c1], verse_start=v1, verse_end=v2,
            )]
        refs = [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[c1], verse_start=v1, to_chapter_end=True,
        )]
        if c2 - c1 > 1:
            refs.append(ParsedReference(
                book_name=book_name, book_id=book_id,
                chapters=list(range(c1 + 1, c2)),
            ))
        refs.append(ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[c2], verse_start=1, verse_end=v2,
        ))
        return refs

    # "3:16-18" → chapter + verse range
    m = _CHAP_VERSE_RANGE.match(spec)
    if m:
        return [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[int(m.group(1))],
            verse_start=int(m.group(2)),
            verse_end=int(m.group(3)),
        )]

    # "3:16" → single verse
    m = _CHAP_VERSE.match(spec)
    if m:
        return [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[int(m.group(1))],
            verse_start=int(m.group(2)),
            verse_end=int(m.group(2)),
        )]

    # "3" → chapter only (no 章 suffix)
    m = _CHAPTER_ONLY.match(spec)
    if m:
        return [ParsedReference(
            book_name=book_name, book_id=book_id,
            chapters=[int(m.group(1))],
        )]

    # Fallback: whole book
    return [ParsedReference(book_name=book_name, book_id=book_id, is_whole_book=True)]


def _parse_book_segment(segment: str) -> list[ParsedReference]:
    """Parse a segment that starts with a book name, possibly with comma-separated specs."""
    book_name, rest = _extract_book_and_rest(segment)
    if book_name is None:
        return []

    if not rest:
        return [ParsedReference(
            book_name=book_name,
            book_id=_get_book_id(book_name) or book_name,
            is_whole_book=True,
        )]

    # Split by comma for multi-spec within same book: "2-4章, 18章"
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    refs: list[ParsedReference] = []
    for part in parts:
        # Check if part starts with a new book name
        inner_book, inner_rest = _extract_book_and_rest(part)
        if inner_book and inner_book != book_name:
            refs.extend(_parse_book_segment(part))
        else:
            refs.extend(_parse_single_ref(book_name, part))
    return refs


def parse_reference(reference: str) -> list[ParsedReference]:
    """
    Parse a ground truth reference string into a list of ParsedReference.

    Handles semicolon-separated multi-references and various Chinese Bible formats.
    When a segment doesn't start with a book name, it inherits the previous book.
    """
    if not reference or not reference.strip():
        return []

    # Split by semicolon first (top-level separator)
    segments = [s.strip() for s in reference.split(";") if s.strip()]
    results: list[ParsedReference] = []
    last_book: str | None = None

    for segment in segments:
        book_name, _ = _extract_book_and_rest(segment)
        if book_name is not None:
            refs = _parse_book_segment(segment)
            if refs:
                last_book = refs[0].book_name
                results.extend(refs)
        elif last_book is not None:
            # No book name found — inherit from previous segment
            results.extend(_parse_single_ref(last_book, segment))
        # else: skip unparseable segment with no prior book context

    return results

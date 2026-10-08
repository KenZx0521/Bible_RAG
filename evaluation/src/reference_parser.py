"""GT reference strings to ParsedReference units, through ragcommon.refs (strict).

The whole string must parse: full names and abbreviations, full-width forms,
「；」 and 「，」 lists, 「第3章3節」, 3:16a, chapter ranges, cross-chapter
ranges, and verse numbers the PDF lacks through ref_aliases. Anything else,
including a chapter or verse the PDF verse grid does not have, raises
``RefParseError``. A blank reference names no gold and yields no units.

Units keep the shape relevance_judge and verse_coverage score with: one per
in-chapter verse range or chapter range; a cross-chapter verse range becomes
its head (to the chapter end), the whole middle chapters and its tail; a
reference to every chapter of a book is that whole book.
"""

from __future__ import annotations

from ragcommon import books
from ragcommon.refs import RefParseError, VerseRef, parse_refs
from ragcommon.versification import default_versification

from .models import ParsedReference

__all__ = ["RefParseError", "parse_reference"]


def _whole_book(ref: VerseRef) -> bool:
    return ref.ch == 1 and ref.ch_end == default_versification().chapter_count(ref.book_id)


def _units(ref: VerseRef) -> list[ParsedReference]:
    base = {"book_name": books.get_book(ref.book_id).name, "book_id": ref.book_id}
    if ref.v_start is None:
        if _whole_book(ref):
            return [ParsedReference(**base, is_whole_book=True)]
        return [ParsedReference(**base, chapters=list(range(ref.ch, ref.ch_end + 1)))]
    if ref.ch == ref.ch_end:
        return [ParsedReference(**base, chapters=[ref.ch],
                                verse_start=ref.v_start, verse_end=ref.v_end)]
    head = ParsedReference(**base, chapters=[ref.ch], verse_start=ref.v_start, to_chapter_end=True)
    middle = ([ParsedReference(**base, chapters=list(range(ref.ch + 1, ref.ch_end)))]
              if ref.ch_end - ref.ch > 1 else [])
    tail = ParsedReference(**base, chapters=[ref.ch_end], verse_start=1, verse_end=ref.v_end)
    return [head, *middle, tail]


def parse_reference(reference: str) -> list[ParsedReference]:
    """Parse a GT ``reference`` field; raise RefParseError unless all of it parses."""
    if not reference or not reference.strip():
        return []
    return [unit for ref in parse_refs(reference, strict=True).refs for unit in _units(ref)]

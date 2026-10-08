"""Scripture references in a question, read with ragcommon.refs (design §11.1 R1).

Book names come from ragcommon.books (the PDF title lines; 尼西米記 is only an
input spelling of 尼希米記), and every reference is checked against the PDF verse
grid through ragcommon's versification and ref_aliases. A reference that names no
verse is returned as rejected, so the caller can report it instead of routing on it.
A cross-chapter range becomes one reference per chapter, whole chapters in between
spelled as verse ranges, so a source's verse_range stays chapter-internal.
"""

from __future__ import annotations

from dataclasses import dataclass

from ragcommon import books, refs
from ragcommon.versification import default_versification


@dataclass(frozen=True)
class VerseRef:
    book_id: str
    book_name: str
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None

    @property
    def is_range(self) -> bool:
        return (self.verse_start is not None and self.verse_end is not None
                and self.verse_end > self.verse_start)

    @property
    def display(self) -> str:
        s = f"{self.book_name}{self.chapter}"
        if self.verse_start is not None:
            s += f":{self.verse_start}"
            if self.is_range:
                s += f"-{self.verse_end}"
        return s


@dataclass(frozen=True)
class FoundRefs:
    refs: tuple[VerseRef, ...]
    rejected: tuple[refs.RefRejection, ...]


def _per_chapter(ref: refs.VerseRef) -> list[VerseRef]:
    name = books.get_book(ref.book_id).name
    if ref.v_start is None:
        return [VerseRef(ref.book_id, name, ch) for ch in range(ref.ch, ref.ch_end + 1)]
    vers = default_versification()
    out = []
    for ch in range(ref.ch, ref.ch_end + 1):
        first = ref.v_start if ch == ref.ch else 1
        last = ref.v_end if ch == ref.ch_end else vers.max_verse(ref.book_id, ch)
        out.append(VerseRef(ref.book_id, name, ch, first, last))
    return out


def find_verse_references(text: str) -> FoundRefs:
    """The references in ``text`` and the reference-shaped spans that name no verse."""
    found = refs.find_refs(text)
    return FoundRefs(tuple(r for ref in found.refs for r in _per_chapter(ref)), found.rejected)


def parse_verse_references(text: str) -> list[VerseRef]:
    return list(find_verse_references(text).refs)

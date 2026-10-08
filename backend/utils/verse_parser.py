"""Scripture references in a question, read with ragcommon.refs (design §11.1 R1).

Book names come from ragcommon.books (the PDF title lines; 尼西米記 is only an
input spelling of 尼希米記), and every reference is checked against the PDF verse
grid through ragcommon's versification and ref_aliases. A reference that names no
verse is returned as rejected, so the caller can report it instead of routing on it.

- A cross-chapter verse range (1:30-2:3) becomes one reference per chapter, whole
  chapters in between spelled as verse ranges, so a source's verse_range stays
  chapter-internal.
- A chapter range (利未記1-7章) stays ONE reference: ``chapter`` is its first
  chapter, ``chapter_end`` its last. Retrieval and the chapter pin read only
  ``chapter``, which is what the legacy parser served (it read 「1-7」 as chapter 1
  with verse_end 7); R1 keeps that (design §0.2). One reference per chapter had
  pinned every chapter of the range over the reranker and sent a whole book's
  passages to it.
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
    chapter_end: int | None = None   # last chapter of a chapter range; None: one chapter

    @property
    def is_range(self) -> bool:
        return (self.verse_start is not None and self.verse_end is not None
                and self.verse_end > self.verse_start)

    @property
    def display(self) -> str:
        s = f"{self.book_name}{self.chapter}"
        if self.chapter_end is not None:
            s += f"-{self.chapter_end}"
        if self.verse_start is not None:
            s += f":{self.verse_start}"
            if self.is_range:
                s += f"-{self.verse_end}"
        return s


@dataclass(frozen=True)
class FoundRefs:
    refs: tuple[VerseRef, ...]
    rejected: tuple[refs.RefRejection, ...]


def _backend_refs(ref: refs.VerseRef) -> list[VerseRef]:
    name = books.get_book(ref.book_id).name
    if ref.v_start is None:
        last = ref.ch_end if ref.ch_end > ref.ch else None
        return [VerseRef(ref.book_id, name, ref.ch, chapter_end=last)]
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
    return FoundRefs(tuple(r for ref in found.refs for r in _backend_refs(ref)), found.rejected)


def parse_verse_references(text: str) -> list[VerseRef]:
    return list(find_verse_references(text).refs)

"""S2b: chapter-level texts — Psalm superscriptions and book divisions (design §2.6, §2.23).

A superscription is the black text between a psalm's chapter number and its first
verse. It is not a verse and has no slot. ``order`` records whether it is printed
before the chapter's first heading (詩3 is the only one), after it (115 psalms) or
in a chapter without a heading. A book division (詩篇卷一…五) belongs to the chapter
after it. Both keep the text as printed, including the 、 between the characters of
four divisions.
"""

from __future__ import annotations

from typing import Any, Sequence

from ragcommon import ids
from ragdata.stages import layout
from ragdata.stages.s02_parse.stream import BookStream, Event

PDF = "pdf_deterministic"


def _order(events: Sequence[Event], chapter: int) -> str:
    """Whether the superscription of ``chapter`` stands before or after its first heading."""
    title = heading = None
    for i, event in enumerate(events):
        if event.chapter != chapter:
            continue
        if event.kind == "verse":
            break
        if event.kind == "title" and title is None:
            title = i
        if event.kind == layout.HEADING and heading is None:
            heading = i
    if heading is None:
        return "no_heading"
    return "before_heading" if title is not None and title < heading else "after_heading"


def _row(id_: str, kind: str, key: str, text: str, order: str | None,
         pages: Sequence[int]) -> dict[str, Any]:
    return {"id": id_, "kind": kind, "chapter_key": key, "text_pdf": text, "text": text,
            "order": order, "pages": sorted(set(pages)), "provenance_class": PDF}


def chapter_text_rows(book_id: str, stream: BookStream) -> tuple[dict[str, Any], ...]:
    """Division and superscription records of one book, by chapter (division first)."""
    found: list[tuple[int, int, dict[str, Any]]] = []
    for event in stream.events:
        if event.kind == "division":
            key = ids.chapter_key(book_id, event.chapter)
            found.append((event.chapter, 0, _row(ids.division_id(key), "book_division", key,
                                                 event.text, None, [event.page])))
    for chapter, glyphs in stream.titles.items():
        key = ids.chapter_key(book_id, chapter)
        text = "".join(g.c for g in glyphs)
        found.append((chapter, 1, _row(ids.superscription_id(key), "superscription", key, text,
                                       _order(stream.events, chapter), [g.page for g in glyphs])))
    return tuple(row for _, _, row in sorted(found, key=lambda f: (f[0], f[1])))

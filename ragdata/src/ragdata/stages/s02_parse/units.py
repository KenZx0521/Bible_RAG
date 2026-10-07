"""S2a: the text-layer body of one book — books, chapters, verse_units, verse_slots.

From a BookStream (design §2.2–2.5, D-03(b), D-04(a)):
- one unit per printed verse number; a merged number (``2-3``) is one unit over
  two ``merged`` slots;
- a verse number missing inside a chapter is an ``omitted_variant`` slot, linked
  to the note of the verse before it that starts 有古卷 and typesets the missing
  number (有古卷加：37…); a gap without such a note is a ParseError;
- ``text_pdf`` is the verse as printed with the PDF's line-break spaces removed
  (G45); ``text`` equals it until S4 applies errata;
- ``line_breaks`` record where each PDF line starts: ``indent`` when the line
  starts right of the margin, ``soft`` when the line before reached the right
  margin (a typesetting wrap), ``hard`` otherwise (the line was ended early);
- ``markers`` locate each （細拉） line; ``is_poetry`` is true when the verse
  number sits at the margin (poetry layout) rather than at the paragraph indent.
Footnotes are numbered per unit in page order (``fn:{unit_key}#n``); S2b builds
their records with the same numbers.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

from ragcommon import books, ids
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse.stream import SELAH, BookStream, Footnote, Verse, VerseLine

PDF = "pdf_deterministic"
INDENT_X = 75.0          # continuation lines start at 70.87; anything right of 75 is indented
FULL_LINE_X = 340.0      # justified lines end at about 349; a line ending here or later wrapped
RIGHT_BLOCK_X = 200.0    # a line starting this far right (（細拉） at 301) is a set-off block
POETRY_NUMBER_X = 77.0   # verse numbers sit at 71 in poetry layout and at 83 in prose
VARIANT_PREFIX = "有古卷"


@dataclass(frozen=True)
class BookRecords:
    book: dict[str, Any]
    chapters: tuple[dict[str, Any], ...]
    units: tuple[dict[str, Any], ...]
    slots: tuple[dict[str, Any], ...]
    footnotes: tuple[tuple[str, Footnote], ...]  # (fn id, note) in page order


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _break_kind(prev: VerseLine, line: VerseLine) -> str:
    if line.first.x0 > INDENT_X:
        return "indent"
    if prev.last.x1 >= FULL_LINE_X and prev.first.x0 < RIGHT_BLOCK_X:
        return "soft"
    return "hard"


def line_breaks(verse: Verse) -> list[dict[str, Any]]:
    return [{"offset": line.start, "kind": _break_kind(prev, line)}
            for prev, line in zip(verse.lines, verse.lines[1:])]


def selah_markers(verse: Verse, where: str) -> list[dict[str, Any]]:
    text, found = verse.text, []
    start = text.find(SELAH)
    while start >= 0:
        found.append(start)
        start = text.find(SELAH, start + 1)
    if found != list(verse.selah):
        raise ParseError(f"{where}: （細拉） at {found} but selah lines at {list(verse.selah)}")
    return [{"type": "selah", "start": s, "end": s + len(SELAH)} for s in found]


def unit_key(book_id: str, verse: Verse) -> str:
    return ids.unit_key(book_id, verse.chapter, verse.v_start, verse.v_end)


def unit_row(book_id: str, verse: Verse, pdf_sha256: str, ord_: int) -> dict[str, Any]:
    key = unit_key(book_id, verse)
    text = verse.text
    if not text or any(c.isspace() for c in text):
        raise ParseError(f"{key}: verse text {text!r} is empty or keeps whitespace (G45)")
    first = verse.glyphs[0]
    return {
        "unit_key": key, "book_id": book_id, "chapter": verse.chapter, "label": verse.label,
        "v_start": verse.v_start, "v_end": verse.v_end, "ord": ord_,
        "text_pdf": text, "text": text, "text_sha256": _sha(text), "errata_ids": [],
        "line_breaks": line_breaks(verse), "markers": selah_markers(verse, key),
        "is_poetry": verse.number[0].x0 < POETRY_NUMBER_X,
        "pages": sorted({g.page for g in verse.glyphs}),
        "prov": {"pdf_sha256": pdf_sha256, "first_glyph": [first.x0, first.x1, first.y]},
        "provenance_class": PDF,
    }


def unit_keys(book_id: str, stream: BookStream) -> dict[tuple[int, str], str]:
    """``(chapter, label)`` of every printed verse number -> its unit key."""
    return {(v.chapter, v.label): unit_key(book_id, v) for v in stream.verses}


def number_footnotes(book_id: str, stream: BookStream) -> tuple[tuple[str, Footnote], ...]:
    """Give each footnote its id: the unit its caller names, numbered in page order."""
    keys = unit_keys(book_id, stream)
    counts: dict[str, int] = defaultdict(int)
    out = []
    for note in stream.footnotes:
        chapter, _, label = note.ref.partition(":")
        key = keys.get((int(chapter), label.replace("–", "-").replace("－", "-")))
        if key is None:
            raise ParseError(f"{book_id} p{note.page}: footnote {note.ref} names no verse")
        counts[key] += 1
        out.append((ids.footnote_id(key, counts[key]), note))
    return tuple(out)


def _variant_note(slot: str, before: str | None, number: int,
                  notes: Sequence[tuple[str, Footnote]]) -> str:
    hits = [fid for fid, note in notes if before is not None
            and ids.parse(fid).parent.raw == before
            and note.text.startswith(VARIANT_PREFIX) and number in note.numbers]
    if len(hits) != 1:
        raise ParseError(f"{slot}: missing verse has {len(hits)} 有古卷 footnotes typesetting "
                         f"{number} on the verse before ({before})")
    return hits[0]


def _slot(key: str, unit: str | None, status: str, note: str | None = None) -> dict[str, Any]:
    return {"slot_key": key, "unit_key": unit, "status": status, "variant_footnote_id": note,
            "provenance_class": PDF}


def chapter_slots(book_id: str, chapter: int, verses: Sequence[Verse],
                  notes: Sequence[tuple[str, Footnote]]) -> list[dict[str, Any]]:
    """Slot rows 1..max verse of one chapter, omitted slots linked to their variant note."""
    starts = [v.v_start for v in verses]
    if starts != sorted(starts):
        raise ParseError(f"{book_id}.{chapter}: verses out of order: {starts}")
    by_number = {n: v for v in verses for n in range(v.v_start, v.v_end + 1)}
    rows = []
    for n in range(1, max(by_number) + 1):
        key = ids.slot_key(book_id, chapter, n)
        verse = by_number.get(n)
        if verse is None:
            before = by_number.get(n - 1)
            before_key = unit_key(book_id, before) if before is not None else None
            rows.append(_slot(key, None, "omitted_variant",
                              _variant_note(key, before_key, n, notes)))
        else:
            status = "merged" if verse.v_end > verse.v_start else "present"
            rows.append(_slot(key, unit_key(book_id, verse), status))
    return rows


def chapter_row(book_id: str, chapter: int, stream: BookStream, n_units: int,
                slots: Sequence[dict[str, Any]]) -> dict[str, Any]:
    key = ids.chapter_key(book_id, chapter)
    omitted = [s["slot_key"] for s in slots if s["status"] == "omitted_variant"]
    divided = any(e.kind == "division" and e.chapter == chapter for e in stream.events)
    return {
        "chapter_key": key, "book_id": book_id, "chapter": chapter, "unit_count": n_units,
        "present_slot_count": len(slots) - len(omitted), "slot_rows": len(slots),
        "max_verse": len(slots), "omitted_slots": omitted,
        "has_superscription": bool(stream.titles.get(chapter)),
        "book_division_id": ids.division_id(key) if divided else None, "provenance_class": PDF,
    }


def book_row(book_id: str, file_name: str, name: str, pdf_sha256: str,
             chapters: Sequence[dict[str, Any]]) -> dict[str, Any]:
    meta = books.get_book(book_id)
    total = {k: sum(c[k] for c in chapters)
             for k in ("unit_count", "present_slot_count", "slot_rows")}
    return {
        "book_id": book_id, "ord": meta.ord, "name": name, "name_source": "pdf_title_line",
        "file_name": file_name, "file_name_mismatch": file_name != name,
        "short_names": list(meta.pdf_abbreviations), "name_en": meta.name_en,
        "testament": meta.testament, "category": meta.category,
        "chapter_count": len(chapters), **total,
        "omitted_count": sum(len(c["omitted_slots"]) for c in chapters),
        "pdf_sha256": pdf_sha256, "provenance_class": PDF, "meta_provenance": "curated_metadata",
    }


def build_book(stream: BookStream, book_id: str, file_name: str, pdf_sha256: str,
               ord_start: int) -> BookRecords:
    """Records of one book; unit ``ord`` continues from ``ord_start`` in page order."""
    notes = number_footnotes(book_id, stream)
    units = tuple(unit_row(book_id, v, pdf_sha256, ord_start + i)
                  for i, v in enumerate(stream.verses))
    chapters, slots = [], []
    for chapter in sorted({v.chapter for v in stream.verses}):
        verses = [v for v in stream.verses if v.chapter == chapter]
        rows = chapter_slots(book_id, chapter, verses, notes)
        slots += rows
        chapters.append(chapter_row(book_id, chapter, stream, len(verses), rows))
    book = book_row(book_id, file_name, stream.book_title, pdf_sha256, chapters)
    return BookRecords(book, tuple(chapters), units, tuple(slots), notes)

"""S2: parse the S1 glyph lines of each PDF into text-layer records (design §2.2–2.11, §4).

``parse_book`` walks one book's rows (``stream``) and builds every record type the
PDF determines:

- the text body (S2a, ``units``): books, chapters, verse_units, verse_slots;
- the rest of the page (S2b): chapter_texts (``chapter_texts``), headings,
  parallel_refs and speakers (``navy``, ``headings``, ``parallels``), footnotes
  (``notes``) and name_spans (``names``; merge groups are numbered over the whole
  corpus by ``names.with_merge_groups``).

Every glyph is accounted for by a record or a category dropped by design
(``conserve``, G-CONSERVE). Errata (S4) are not applied: ``text`` equals ``text_pdf``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ragdata.gates.conserve import Tally
from ragdata.stages import layout
from ragdata.stages.s01_extract import S1Book
from ragdata.stages.s02_parse.chapter_texts import chapter_text_rows
from ragdata.stages.s02_parse.conserve import book_tally
from ragdata.stages.s02_parse.headings import navy_records
from ragdata.stages.s02_parse.names import name_spans
from ragdata.stages.s02_parse.navy import place_navy
from ragdata.stages.s02_parse.notes import footnote_rows
from ragdata.stages.s02_parse.stream import BookStream, parse_rows
from ragdata.stages.s02_parse.units import build_book, unit_key, unit_keys

S2_TYPES = ("books", "chapters", "verse_units", "verse_slots", "chapter_texts", "headings",
            "parallel_refs", "footnotes", "speakers", "name_spans")


@dataclass(frozen=True)
class ParsedBook:
    stream: BookStream
    rows: Mapping[str, tuple[dict[str, Any], ...]]  # by record type, every S2_TYPES key
    tally: Tally


def parse_book(book: S1Book, book_id: str, file_name: str, pdf_sha256: str,
               ord_start: int, heading_ord_start: int = 1) -> ParsedBook:
    """Parse one book; unit and heading ``ord`` continue from the given starts."""
    rows = layout.rows_of(book.lines)
    stream = parse_rows(rows, book_id)
    body = build_book(stream, book_id, file_name, pdf_sha256, ord_start)
    navy = navy_records(book_id, place_navy(stream, unit_keys(book_id, stream), book_id),
                        heading_ord_start)
    containers = [*((unit_key(book_id, v), "body", v.glyphs) for v in stream.verses),
                  *((fid, "footnote", note.glyphs) for fid, note in body.footnotes)]
    records = MappingProxyType({
        "books": (body.book,), "chapters": body.chapters, "verse_units": body.units,
        "verse_slots": body.slots, "chapter_texts": chapter_text_rows(book_id, stream),
        "headings": navy.headings, "parallel_refs": navy.parallel_refs,
        "footnotes": footnote_rows(book_id, body.footnotes, body.units, body.slots),
        "speakers": navy.speakers, "name_spans": name_spans(book, rows, containers, book_id),
    })
    return ParsedBook(stream, records, book_tally(book.lines, rows, stream, records))

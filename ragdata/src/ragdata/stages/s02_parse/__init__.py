"""S2: parse the S1 glyph lines of each PDF into text-layer records (design §4).

Part one (S2a, this package today) builds the text body — books, chapters,
verse_units, verse_slots — and accounts for every glyph (G-CONSERVE). The
other rows it walks (headings, parallel references, speakers, footnotes,
superscriptions, divisions) stay in the BookStream for S2b.
"""

from __future__ import annotations

from dataclasses import dataclass

from ragdata.gates.conserve import Tally
from ragdata.stages import layout
from ragdata.stages.s01_extract import S1Book
from ragdata.stages.s02_parse.conserve import book_tally
from ragdata.stages.s02_parse.stream import BookStream, parse_rows
from ragdata.stages.s02_parse.units import BookRecords, build_book


@dataclass(frozen=True)
class ParsedBook:
    stream: BookStream
    records: BookRecords
    tally: Tally


def parse_book(book: S1Book, book_id: str, file_name: str, pdf_sha256: str,
               ord_start: int) -> ParsedBook:
    """Parse one book; unit ``ord`` continues from ``ord_start``."""
    rows = layout.rows_of(book.lines)
    stream = parse_rows(rows, book_id)
    records = build_book(stream, book_id, file_name, pdf_sha256, ord_start)
    return ParsedBook(stream, records, book_tally(book.lines, rows, stream, records.units))

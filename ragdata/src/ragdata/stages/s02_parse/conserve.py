"""Glyph accounting for G-CONSERVE: where every non-space glyph of a book went.

The source side classifies rows by style alone (layout.classify) and counts
their glyphs; the output side counts what the parse produced. They are
computed independently, so a row the state machine dropped or misplaced shows
up as a residual (the old converter lost 268 verses this way, G01).

Categories: ``body`` (verse units and superscriptions), ``verse_number``,
``chapter_number``, ``navy`` (headings, parallel-reference lines, speakers),
``footnote`` (caller and text), ``division``; dropped by design: ``page_header``,
``book_title``, ``colophon``; and ``unclassified`` (must be 0). The output side
of the text categories is counted from the text-layer records the parse wrote,
so every glyph is accounted for by a record or by a category dropped by design.
"""

from __future__ import annotations

from collections import Counter
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.gates.conserve import CATEGORIES, Tally
from ragdata.stages import layout
from ragdata.stages.layout import Line, Row
from ragdata.stages.s02_parse.stream import BookStream

Records = Mapping[str, Sequence[Mapping[str, Any]]]
_ROW_CATEGORY = {
    layout.HEADER: "page_header", layout.BOOK_TITLE: "book_title", layout.DIVISION: "division",
    layout.CHAPTER: "chapter_number", layout.NOTE_START: "footnote",
    layout.NOTE_CONT: "footnote", layout.HEADING: "navy", layout.PARALLEL: "navy",
    layout.BODY: "body", layout.OTHER: "unclassified",
}


def _frozen(counts: Mapping[str, int], keys: Sequence[str]) -> Mapping[str, int]:
    return MappingProxyType({k: counts.get(k, 0) for k in keys})


def source_counts(rows: Sequence[Row], where: str) -> Counter[str]:
    body, colophon = layout.split_colophon(rows, where)
    counts: Counter[str] = Counter(colophon=sum(layout.nonspace(r.glyphs) for r in colophon))
    for row in body:
        kind = layout.classify(row)
        if kind == layout.VERSE:
            counts["verse_number"] += layout.nonspace(row.runs[0].glyphs)
            counts["body"] += sum(layout.nonspace(r.glyphs) for r in row.runs[1:])
        else:
            counts[_ROW_CATEGORY[kind]] += layout.nonspace(row.glyphs)
    return counts


def _chars(texts) -> int:
    return sum(1 for t in texts for c in t if not c.isspace())


def _caller(unit_key: str) -> int:
    """Length of a footnote's caller ``c:v:`` (``c:v-w:`` for a merged unit)."""
    unit = ids.parse(unit_key)
    label = f"{unit.verse}-{unit.verse_end}" if unit.verse_end else str(unit.verse)
    return len(f"{unit.chapter}:{label}:")


def _texts(rows: Records, type_name: str, field: str, kind: str | None = None) -> list[str]:
    return [r[field] for r in rows[type_name] if kind is None or r["kind"] == kind]


def record_counts(rows: Records) -> dict[str, int]:
    """The text categories counted from one book's text-layer records."""
    lines = {r["heading_id"]: r["raw"] for r in rows["parallel_refs"]}  # one line, many segments
    return {
        "body": _chars(_texts(rows, "verse_units", "text_pdf"))
        + _chars(_texts(rows, "chapter_texts", "text_pdf", "superscription")),
        "navy": _chars(_texts(rows, "headings", "text_pdf")) + _chars(lines.values())
        + _chars(_texts(rows, "speakers", "text_pdf")),
        "footnote": _chars(_texts(rows, "footnotes", "text_pdf"))
        + sum(_caller(f["unit_key"]) for f in rows["footnotes"]),
        "division": _chars(_texts(rows, "chapter_texts", "text_pdf", "book_division")),
    }


def output_counts(stream: BookStream, rows: Records) -> dict[str, int]:
    return {
        **stream.skipped,
        "verse_number": sum(layout.nonspace(v.number) for v in stream.verses),
        "chapter_number": sum(len(n) for n in stream.numerals.values()),
        **record_counts(rows),
        "colophon": sum(layout.nonspace(r.glyphs) for r in stream.colophon),
        "unclassified": sum(layout.nonspace(r.glyphs) for r in stream.unclassified),
    }


def book_tally(lines: Sequence[Line], rows: Sequence[Row], stream: BookStream,
               records: Records) -> Tally:
    """Tally one book: ``lines`` as S1 wrote them, ``rows`` merged from them, the parse and
    the text-layer records it produced (by record type)."""
    glyphs = sum(layout.nonspace(ln.glyphs) for ln in lines)
    return Tally(glyphs, _frozen(source_counts(rows, "conserve"), CATEGORIES),
                 _frozen(output_counts(stream, records), CATEGORIES))

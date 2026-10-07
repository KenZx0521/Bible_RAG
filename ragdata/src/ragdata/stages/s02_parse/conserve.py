"""Glyph accounting for G-CONSERVE: where every non-space glyph of a book went.

The source side classifies rows by style alone (layout.classify) and counts
their glyphs; the output side counts what the parse produced. They are
computed independently, so a row the state machine dropped or misplaced shows
up as a residual (the old converter lost 268 verses this way, G01).

Categories: ``body`` (verse text and superscriptions), ``verse_number``,
``chapter_number``, ``navy`` (headings, parallel references, speakers),
``footnote`` (caller and text), ``division``; dropped by design: ``page_header``,
``book_title``, ``colophon``; and ``unclassified`` (must be 0). Text that S2a
parses but does not yet turn into records — superscriptions, navy rows,
footnotes, divisions — is counted under ``pending`` for S2b.
"""

from __future__ import annotations

from collections import Counter
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata.gates.conserve import CATEGORIES, Tally
from ragdata.stages import layout
from ragdata.stages.layout import Line, Row
from ragdata.stages.s02_parse.stream import BookStream
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


def pending_counts(stream: BookStream) -> dict[str, int]:
    return {
        "superscription": sum(layout.nonspace(g) for g in stream.titles.values()),
        "navy": _chars(e.text for e in stream.events
                       if e.kind in (layout.HEADING, layout.PARALLEL)),
        "footnote": sum(_chars([n.text]) + len(n.ref) + 1 for n in stream.footnotes),
        "division": _chars(e.text for e in stream.events if e.kind == "division"),
    }


def output_counts(stream: BookStream, units: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    pending = pending_counts(stream)
    return {
        **stream.skipped,
        "verse_number": sum(layout.nonspace(v.number) for v in stream.verses),
        "chapter_number": sum(len(n) for n in stream.numerals.values()),
        "body": _chars(u["text_pdf"] for u in units) + pending["superscription"],
        "navy": pending["navy"], "footnote": pending["footnote"],
        "division": pending["division"],
        "colophon": sum(layout.nonspace(r.glyphs) for r in stream.colophon),
        "unclassified": sum(layout.nonspace(r.glyphs) for r in stream.unclassified),
    }


def book_tally(lines: Sequence[Line], rows: Sequence[Row], stream: BookStream,
               units: Sequence[Mapping[str, Any]]) -> Tally:
    """Tally one book: ``lines`` as S1 wrote them, ``rows`` merged from them, the parse."""
    glyphs = sum(layout.nonspace(ln.glyphs) for ln in lines)
    pending = pending_counts(stream)
    return Tally(glyphs, _frozen(source_counts(rows, "conserve"), CATEGORIES),
                 _frozen(output_counts(stream, units), CATEGORIES),
                 _frozen(pending, tuple(pending)))

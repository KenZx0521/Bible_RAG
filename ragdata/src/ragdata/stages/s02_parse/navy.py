"""S2b: type the navy rows of a book and place them in the text (design §2.7, §2.8, §2.10).

Navy 11.96 rows are section headings, parallel-reference lines or Song of Songs
speaker labels. They are told apart by how the page sets them, never by what a
title says (audit G09: the old converter promoted the tails of wrapped references
to headings):

- a parallel-reference line starts with （ or * and runs until its brackets close;
  a line too long for the column continues on the next row at the left margin;
- a speaker label is a whole row 〔…〕 at the left margin;
- a heading starts at the heading indent, uses only the heading typefaces (never the
  italic digits of a reference) and its brackets balance.

A navy row that is none of these is a ParseError, so a fragment can never become a
heading. Headings and speakers stand ``before`` the verse that follows them, or
``mid`` a verse at the offset where its text is interrupted; a reference line goes
with the heading right above it (``headings``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.layout import Glyph
from ragdata.stages.s02_parse.stream import BookStream, Event

HEADING, PARALLEL, SPEAKER = "heading", "parallel", "speaker"
HEADING_STYLES = frozenset({
    ("NotoSansCJKjp-Regular", layout.BODY_SIZE, layout.NAVY),
    ("BitstreamCyberbit-Roman", layout.BODY_SIZE, layout.NAVY),
})
STYLE_CLASS = "navy_heading"  # the one typeface the PDF uses for headings of every level
MARGIN_X = 75.0               # rows at the left margin start at 70.87; headings at 88.8
OPENERS, CLOSERS = "（*", "）)"  # one reference line in jhn closes with an ASCII )
_SPEAKER = re.compile(r"〔[^〔〕]+〕")
_BRACKETS = ("（）", "〔〕", "「」")


@dataclass(frozen=True)
class NavyLine:
    """One heading, speaker label or (rejoined) reference line, as printed."""

    kind: str
    glyphs: tuple[Glyph, ...]
    page: int
    chapter: int
    verse: str | None      # the verse open when the row was read (None at a chapter start)
    offset: int | None     # how much of that verse had been read

    @property
    def text(self) -> str:
        return "".join(g.c for g in self.glyphs)


@dataclass(frozen=True)
class Placed:
    line: NavyLine
    unit_key: str
    offset: int            # 0: before the unit; > 0: inside it, after ``offset`` characters

    @property
    def pos(self) -> str:
        return "mid" if self.offset else "before"


def _balanced(text: str) -> bool:
    return all(text.count(a) == text.count(b) for a, b in _BRACKETS)


def closed(text: str) -> bool:
    """Whether a reference line that starts with ``text`` is complete."""
    if text.startswith("*"):
        return len(text) > 1 and text.endswith("*")
    return text[-1] in CLOSERS and text.count("（") == sum(text.count(c) for c in CLOSERS)


def _at_margin(glyphs: Sequence[Glyph]) -> bool:
    return glyphs[0].x0 < MARGIN_X


def _heading_typeface(glyphs: Sequence[Glyph]) -> bool:
    return all(g.style in HEADING_STYLES for g in glyphs)


def _kind(event: Event, where: str) -> str:
    text, glyphs = event.text, event.glyphs
    if text[:1] in OPENERS:
        return PARALLEL
    speaker = _SPEAKER.fullmatch(text) is not None
    if speaker and _at_margin(glyphs) and _heading_typeface(glyphs):
        return SPEAKER
    if speaker or _at_margin(glyphs) or not _heading_typeface(glyphs) or not _balanced(text):
        raise ParseError(f"{where} p{event.page}: navy row {text!r} is not a heading (it is "
                         "not at the heading indent, uses another typeface or leaves a bracket "
                         "open) and continues no reference line")
    return HEADING


class _Walk:
    """Mutable walk state; ``placed`` collects the frozen results in reading order."""

    def __init__(self, keys: Mapping[tuple[int, str], str], where: str):
        self.keys, self.where = keys, where
        self.waiting: list[NavyLine] = []
        self.placed: list[Placed] = []

    def open_line(self) -> NavyLine | None:
        last = self.waiting[-1] if self.waiting else None
        return last if last is not None and last.kind == PARALLEL and not closed(last.text) \
            else None

    def navy(self, event: Event) -> None:
        open_ = self.open_line()
        if open_ is None:
            line = NavyLine(_kind(event, self.where), event.glyphs, event.page, event.chapter,
                            event.verse, event.offset)
            self.waiting.append(line)
        elif not _at_margin(event.glyphs):
            raise ParseError(f"{self.where} p{event.page}: {event.text!r} continues "
                             f"{open_.text!r} but does not start at the left margin")
        else:
            self.waiting[-1] = replace(open_, glyphs=open_.glyphs + event.glyphs)

    def content(self, event: Event) -> None:
        open_ = self.open_line()
        if open_ is not None:
            raise ParseError(f"{self.where} p{open_.page}: reference line {open_.text!r} never "
                             "closes")
        unit = self.keys[(event.chapter, event.verse)]
        for line in self.waiting:
            self.placed.append(Placed(line, unit, self._offset(line, event)))
        self.waiting = []

    def _offset(self, line: NavyLine, event: Event) -> int:
        if event.kind == "verse":
            return 0
        if (line.chapter, line.verse) != (event.chapter, event.verse) or not line.offset:
            raise ParseError(f"{self.where} p{line.page}: {line.text!r} interrupts no verse")
        return line.offset


def place_navy(stream: BookStream, keys: Mapping[tuple[int, str], str],
               where: str) -> tuple[Placed, ...]:
    """Type, rejoin and place every navy row of ``stream`` (``keys`` from ``units.unit_keys``)."""
    walk = _Walk(keys, where)
    for event in stream.events:
        if event.kind in (layout.HEADING, layout.PARALLEL):
            walk.navy(event)
        elif event.kind in ("verse", "cont"):
            walk.content(event)
    if walk.waiting:
        line = walk.waiting[0]
        raise ParseError(f"{where} p{line.page}: navy row {line.text!r} has no verse after it")
    return tuple(walk.placed)

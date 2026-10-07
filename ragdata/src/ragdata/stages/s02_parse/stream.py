"""S2: walk the classified rows of one book into verses, titles, navy rows and footnotes.

The state machine is the audit parser's (``s2_pdf_verses.py`` / ``g4b_prov_parse.py``):
a verse row opens a verse; black rows continue it, or — before the chapter's
first verse — form the chapter's superscription; navy rows (headings, parallel
references, speaker labels) and Psalm book divisions are recorded where they
fall, with the offset into the current verse; footnote rows split on each bold
``c:v:`` caller. Every glyph keeps its page and position.

The stream records; it does not interpret. Turning navy rows into headings,
parallel references and speakers, and footnotes into records, is S2b's job; the
verse units are built in ``units``. Anything the parser cannot place raises
ParseError naming book and page, so text is never dropped quietly (audit G01).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from ragdata.stages import layout
from ragdata.stages.errors import ParseError
from ragdata.stages.layout import Glyph, Row

SELAH = "（細拉）"
_VERSE_NUMBER = re.compile(r"([1-9][0-9]*)(?:[-–－]([1-9][0-9]*))?")
_CALLER = re.compile(r"([1-9][0-9]*):([1-9][0-9]*)(?:[-–－]([1-9][0-9]*))?:")


@dataclass(frozen=True)
class VerseLine:
    """One PDF line of a verse: offsets into the verse text and its edge glyphs."""

    start: int
    end: int
    first: Glyph
    last: Glyph


@dataclass(frozen=True)
class Verse:
    chapter: int
    label: str
    v_start: int
    v_end: int
    number: tuple[Glyph, ...]
    glyphs: tuple[Glyph, ...]
    lines: tuple[VerseLine, ...]
    selah: tuple[int, ...]

    @property
    def text(self) -> str:
        return "".join(g.c for g in self.glyphs)


@dataclass(frozen=True)
class Event:
    """A row in reading order: chapter, division, heading, paral, verse, cont or title.

    ``verse``/``offset`` locate it in the open verse (None before the chapter's first);
    ``glyphs`` are the row's glyphs as cleaned for ``text`` (navy rows, titles, divisions).
    """

    kind: str
    chapter: int
    verse: str | None
    offset: int | None
    text: str
    page: int
    right: float
    glyphs: tuple[Glyph, ...] = ()


@dataclass(frozen=True)
class Footnote:
    page: int
    ref: str
    chapter_ctx: int
    text: str
    numbers: tuple[int, ...]  # verse numbers typeset inside the note (有古卷加：37…)
    glyphs: tuple[Glyph, ...] = ()  # the glyphs of ``text``, one per character


@dataclass(frozen=True)
class BookStream:
    book_title: str
    verses: tuple[Verse, ...]
    titles: Mapping[int, tuple[Glyph, ...]]
    numerals: Mapping[int, str]
    events: tuple[Event, ...]
    footnotes: tuple[Footnote, ...]
    unclassified: tuple[Row, ...]
    colophon: tuple[Row, ...]
    skipped: Mapping[str, int]


@dataclass
class _VerseDraft:
    chapter: int
    label: str
    v_start: int
    v_end: int
    number: tuple[Glyph, ...]
    glyphs: list[Glyph] = field(default_factory=list)
    lines: list[VerseLine] = field(default_factory=list)
    selah: list[int] = field(default_factory=list)

    def add_line(self, kept: Sequence[Glyph]) -> int:
        start = len(self.glyphs)
        if kept:
            self.glyphs.extend(kept)
            self.lines.append(VerseLine(start, len(self.glyphs), kept[0], kept[-1]))
        return start

    def freeze(self) -> Verse:
        return Verse(self.chapter, self.label, self.v_start, self.v_end, self.number,
                     tuple(self.glyphs), tuple(self.lines), tuple(self.selah))


@dataclass
class _NoteDraft:
    page: int
    ref: str
    chapter_ctx: int
    raw: list[Glyph] = field(default_factory=list)
    numbers: list[int] = field(default_factory=list)

    def freeze(self) -> Footnote:
        glyphs = layout.clean(self.raw)
        return Footnote(self.page, self.ref, self.chapter_ctx, "".join(g.c for g in glyphs),
                        tuple(self.numbers), glyphs)


def _text_runs_only(runs: Sequence[layout.Run], where: str) -> None:
    for run in runs:
        if run.color != layout.BLACK or run.size != layout.BODY_SIZE:
            raise ParseError(f"{where}: text run {run.text!r} has style {run.style}")


class _Stream:
    """Mutable walk state; ``finish`` returns the frozen BookStream."""

    def __init__(self, where: str):
        self.where = where
        self.chapter = 0
        self.cur: _VerseDraft | None = None
        self.division: int | None = None
        self.title: list[str] = []
        self.verses: list[_VerseDraft] = []
        self.numbers_seen: set[tuple[int, int]] = set()
        self.titles: dict[int, list[Glyph]] = {}
        self.numerals: dict[int, str] = {}
        self.events: list[Event] = []
        self.notes: list[_NoteDraft] = []
        self.unclassified: list[Row] = []
        self.skipped: Counter[str] = Counter()

    def at(self, row: Row) -> str:
        return f"{self.where} p{row.page}"

    def event(self, kind: str, row: Row, text: str, offset: int | None = None,
              glyphs: tuple[Glyph, ...] = ()) -> None:
        verse = self.cur.label if self.cur is not None else None
        right = max(r.x1 for r in row.runs)
        self.events.append(Event(kind, self.chapter, verse, offset, text, row.page, right, glyphs))

    def feed(self, row: Row) -> None:
        kind = layout.classify(row)
        handlers = {
            layout.HEADER: self.on_skipped, layout.BOOK_TITLE: self.on_skipped,
            layout.DIVISION: self.on_division, layout.CHAPTER: self.on_chapter,
            layout.NOTE_START: self.on_note, layout.NOTE_CONT: self.on_note,
            layout.HEADING: self.on_navy, layout.PARALLEL: self.on_navy,
            layout.VERSE: self.on_verse, layout.BODY: self.on_body,
        }
        handlers.get(kind, self.on_unclassified)(row, kind)

    def on_skipped(self, row: Row, kind: str) -> None:
        name = "page_header" if kind == layout.HEADER else "book_title"
        self.skipped[name] += layout.nonspace(row.glyphs)
        if kind == layout.BOOK_TITLE:
            self.title.append(layout.clean_text(row.text))

    def on_unclassified(self, row: Row, kind: str) -> None:
        self.unclassified.append(row)

    def on_division(self, row: Row, kind: str) -> None:
        self.division = self.chapter + 1
        glyphs = layout.clean(row.glyphs)
        self.events.append(Event("division", self.division, None, None,
                                 "".join(g.c for g in glyphs), row.page,
                                 max(r.x1 for r in row.runs), glyphs))

    def on_chapter(self, row: Row, kind: str) -> None:
        numeral = layout.clean_text(row.runs[0].text)
        rest = layout.clean_text("".join(r.text for r in row.runs[1:]))
        if not numeral.isdigit() or rest:
            raise ParseError(f"{self.at(row)}: chapter row {row.text!r} is not a bare numeral")
        if int(numeral) != self.chapter + 1:
            raise ParseError(f"{self.at(row)}: chapter {numeral} follows chapter {self.chapter}")
        self.chapter, self.cur = int(numeral), None
        self.numerals[self.chapter] = numeral
        self.event("chapter", row, numeral)

    def on_note(self, row: Row, kind: str) -> None:
        for run in row.runs:
            text = layout.clean_text(run.text)
            if run.font == layout.SERIF_BOLD and _CALLER.fullmatch(text):
                self.notes.append(_NoteDraft(row.page, text[:-1], self.chapter))
            elif not self.notes:
                raise ParseError(f"{self.at(row)}: footnote text {text!r} before any c:v: caller")
            else:
                self.notes[-1].raw.extend(run.glyphs)
                if run.style == layout.VERSE_NUMBER_STYLE and text.isdigit():
                    self.notes[-1].numbers.append(int(text))

    def on_navy(self, row: Row, kind: str) -> None:
        self.chapter = self.chapter or 1
        offset = len(self.cur.glyphs) if self.cur is not None else None
        glyphs = layout.clean(row.glyphs)
        self.event(kind, row, "".join(g.c for g in glyphs), offset, glyphs)

    def _open_verse(self, row: Row) -> _VerseDraft:
        number = layout.clean(row.runs[0].glyphs)
        label = "".join(g.c for g in number)
        found = _VERSE_NUMBER.fullmatch(label)
        if found is None or (found.group(2) and int(found.group(2)) <= int(found.group(1))):
            raise ParseError(f"{self.at(row)}: bad verse number {label!r}")
        v_start = int(found.group(1))
        v_end = int(found.group(2) or v_start)
        label = str(v_start) if v_end == v_start else f"{v_start}-{v_end}"
        numbers = {(self.chapter, n) for n in range(v_start, v_end + 1)}
        if numbers & self.numbers_seen:
            raise ParseError(f"{self.at(row)}: verse {self.chapter}:{label} appears twice")
        self.numbers_seen |= numbers
        return _VerseDraft(self.chapter, label, v_start, v_end, number)

    def on_verse(self, row: Row, kind: str) -> None:
        self.chapter = self.chapter or 1
        if self.division is not None and self.division != self.chapter:
            raise ParseError(f"{self.at(row)}: division for chapter {self.division} is followed "
                             f"by chapter {self.chapter}")
        self.division = None
        _text_runs_only(row.runs[1:], self.at(row))
        draft = self._open_verse(row)
        draft.add_line(layout.clean(tuple(g for r in row.runs[1:] for g in r.glyphs)))
        self.verses.append(draft)
        self.cur = draft
        self.event("verse", row, "".join(g.c for g in draft.glyphs), 0)

    def on_body(self, row: Row, kind: str) -> None:
        _text_runs_only(row.runs, self.at(row))
        kept = layout.clean(row.glyphs)
        text = "".join(g.c for g in kept)
        if self.cur is None or self.cur.chapter != self.chapter:
            if self.chapter == 0:
                raise ParseError(f"{self.at(row)}: text {text!r} before the first chapter")
            self.titles.setdefault(self.chapter, []).extend(kept)
            self.event("title", row, text, glyphs=kept)
            return
        offset = self.cur.add_line(kept)
        if text == SELAH:
            self.cur.selah.append(offset)
        self.event("cont", row, text, offset)

    def finish(self, colophon: Sequence[Row]) -> BookStream:
        if self.division is not None:
            raise ParseError(f"{self.where}: division for chapter {self.division} has no verse")
        if not self.title:
            raise ParseError(f"{self.where}: no book title row")
        missing = sorted(set(range(1, self.chapter + 1)) - {v.chapter for v in self.verses})
        if not self.verses or missing:
            raise ParseError(f"{self.where}: chapters without verses: {missing or 'all'}")
        return BookStream(
            book_title="".join(self.title), verses=tuple(v.freeze() for v in self.verses),
            titles=MappingProxyType({c: tuple(g) for c, g in self.titles.items()}),
            numerals=MappingProxyType(dict(self.numerals)), events=tuple(self.events),
            footnotes=tuple(n.freeze() for n in self.notes),
            unclassified=tuple(self.unclassified), colophon=tuple(colophon),
            skipped=MappingProxyType(dict(self.skipped)))


def parse_rows(rows: Sequence[Row], where: str) -> BookStream:
    """Walk one book's rows (colophon included) into its BookStream."""
    body, colophon = layout.split_colophon(rows, where)
    walk = _Stream(where)
    for row in body:
        walk.feed(row)
    return walk.finish(colophon)

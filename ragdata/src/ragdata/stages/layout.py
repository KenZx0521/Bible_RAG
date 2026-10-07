"""The typeset page as S1 saw it: glyphs, style runs, visual rows and row classes.

Ported from the audit parser (corpus ``s2_pdf_verses.py`` and its per-glyph twin
``g4b_prov_parse.py``), which read all 66 PDFs this way with zero anomalies and
three identical runs (REPORT §2.3). Rows are classified by style alone — font,
size and colour, never position:

    header     any blue glyph (running heads, page numbers)
    colophon   NotoSansCJKjp-Black 11.96 row containing 新標點和合本
    booktitle  NotoSansCJKjp-Black 17.93
    volume     a 15.94 glyph (Psalms book divisions 詩篇卷一…五)
    chapter    leftmost run NotoSerif-ExtraBold 17.93 (the chapter numeral)
    fnstart    navy, ≤8.97, leftmost run NotoSerif-ExtraBold (the c:v: caller)
    fncont     navy, ≤8.97 otherwise
    paral      navy 11.96 starting with （ (parallel reference)
    heading    navy 11.96 otherwise (section headings, Song of Songs speakers)
    verse      leftmost run NotoSerif-Regular 8.97 navy (verse number) and black text
    body       black only (verse continuation, Psalm superscription)
    other      anything else (never seen; G-CONSERVE counts it as unclassified)
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple, Sequence

from ragdata.stages.errors import ParseError

NAVY, BLACK, BLUE = "#000080", "#000000", "#0000ff"
BODY_SIZE, NOTE_SIZE, TITLE_SIZE, DIVISION_SIZE = 11.96, 8.97, 17.93, 15.94
SERIF, SERIF_BOLD, SANS_BLACK = "NotoSerif-Regular", "NotoSerif-ExtraBold", "NotoSansCJKjp-Black"
VERSE_NUMBER_STYLE = (SERIF, NOTE_SIZE, NAVY)
COLOPHON_MARK = "新標點和合本"
ROW_MERGE_PT = 4.0  # stext splits a raised verse number or justified line; rejoin within 4 pt
_CJK_SPACE = re.compile(r"(?<=[^\x00-\x7f])[ \t]+|[ \t]+(?=[^\x00-\x7f])")

HEADER, COLOPHON, BOOK_TITLE, DIVISION, CHAPTER = "header", "colophon", "booktitle", "volume", \
    "chapter"
NOTE_START, NOTE_CONT, PARALLEL, HEADING = "fnstart", "fncont", "paral", "heading"
VERSE, BODY, OTHER = "verse", "body", "other"


class Glyph(NamedTuple):
    c: str
    x0: float
    x1: float
    y: float
    font: str
    size: float
    color: str
    page: int

    @property
    def style(self) -> tuple[str, float, str]:
        return (self.font, self.size, self.color)


class Run(NamedTuple):
    """Consecutive glyphs of one style within a line."""

    glyphs: tuple[Glyph, ...]

    @property
    def style(self) -> tuple[str, float, str]:
        return self.glyphs[0].style

    @property
    def font(self) -> str:
        return self.glyphs[0].font

    @property
    def size(self) -> float:
        return self.glyphs[0].size

    @property
    def color(self) -> str:
        return self.glyphs[0].color

    @property
    def text(self) -> str:
        return "".join(g.c for g in self.glyphs)

    @property
    def x0(self) -> float:
        return self.glyphs[0].x0

    @property
    def x1(self) -> float:
        return self.glyphs[-1].x1


class Line(NamedTuple):
    """One structured-text line: its page, baseline and style runs (left to right)."""

    page: int
    y: float
    runs: tuple[Run, ...]

    @property
    def glyphs(self) -> tuple[Glyph, ...]:
        return tuple(g for r in self.runs for g in r.glyphs)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


Row = Line  # a visual row: one or more lines merged on a shared baseline


def _runs(glyphs: Sequence[Glyph]) -> tuple[Run, ...]:
    groups: list[list[Glyph]] = []
    for g in glyphs:
        if groups and groups[-1][-1].style == g.style:
            groups[-1].append(g)
        else:
            groups.append([g])
    return tuple(sorted((Run(tuple(group)) for group in groups), key=lambda r: r.x0))


def _baseline(glyphs: Sequence[Glyph]) -> float:
    """The most common baseline; on a tie, the one that reached the top count first."""
    counts: dict[float, int] = {}
    best, top = glyphs[0].y, 0
    for g in glyphs:
        counts[g.y] = counts.get(g.y, 0) + 1
        if counts[g.y] > top:
            best, top = g.y, counts[g.y]
    return best


def to_line(page: int, chars: Sequence[Sequence]) -> Line:
    """A line from S1 ``chars`` rows ``[c, x0, x1, y, font, size, color]``."""
    glyphs = tuple(Glyph(*ch, page) for ch in chars)
    return Line(page, _baseline(glyphs), _runs(glyphs))


def rows_of(lines: Iterable[Line]) -> tuple[Row, ...]:
    rows: list[Row] = []
    for ln in lines:
        prev = rows[-1] if rows else None
        if prev is not None and prev.page == ln.page and abs(prev.y - ln.y) < ROW_MERGE_PT:
            runs = tuple(sorted(prev.runs + ln.runs, key=lambda r: r.x0))
            rows[-1] = Row(prev.page, prev.y, runs)
        else:
            rows.append(ln)
    return tuple(rows)


def clean_text(text: str) -> str:
    """Drop spaces and tabs next to non-ASCII (justification) and edge whitespace."""
    return _CJK_SPACE.sub("", text).strip()


def clean(glyphs: Sequence[Glyph]) -> tuple[Glyph, ...]:
    """``clean_text`` on glyphs, keeping each surviving glyph's provenance."""
    text = "".join(g.c for g in glyphs)
    drop = {i for m in _CJK_SPACE.finditer(text) for i in range(m.start(), m.end())}
    kept = [g for i, g in enumerate(glyphs) if i not in drop]
    start, end = 0, len(kept)
    while start < end and kept[start].c.isspace():
        start += 1
    while end > start and kept[end - 1].c.isspace():
        end -= 1
    return tuple(kept[start:end])


def nonspace(glyphs: Iterable[Glyph]) -> int:
    return sum(1 for g in glyphs if not g.c.isspace())


def _is_note(runs: Sequence[Run], colors: set[str]) -> bool:
    return max(r.size for r in runs) <= NOTE_SIZE and colors == {NAVY}


def classify(row: Row) -> str:
    runs = row.runs
    colors = {r.color for r in runs}
    text = "".join(r.text for r in runs)
    if BLUE in colors:
        return HEADER
    if any(r.font == SANS_BLACK and r.size == BODY_SIZE for r in runs) and COLOPHON_MARK in text:
        return COLOPHON
    if any(r.font == SANS_BLACK and r.size == TITLE_SIZE for r in runs):
        return BOOK_TITLE
    if any(r.size == DIVISION_SIZE for r in runs):
        return DIVISION
    if runs[0].font == SERIF_BOLD and runs[0].size == TITLE_SIZE:
        return CHAPTER
    if _is_note(runs, colors):
        return NOTE_START if runs[0].font == SERIF_BOLD else NOTE_CONT
    if colors == {NAVY} and max(r.size for r in runs) == BODY_SIZE:
        return PARALLEL if clean_text(text).startswith("（") else HEADING
    if runs[0].style == VERSE_NUMBER_STYLE and any(r.color == BLACK for r in runs[1:]):
        return VERSE
    if colors == {BLACK}:
        return BODY
    return OTHER


def split_colophon(rows: Sequence[Row], where: str) -> tuple[tuple[Row, ...], tuple[Row, ...]]:
    """Split off the colophon: it must stand alone, after any page header, on the last page.

    Returns ``(rows before it plus page headers on its page, colophon rows)``.
    """
    start = next((i for i, r in enumerate(rows) if classify(r) == COLOPHON), None)
    if start is None:
        raise ParseError(f"{where}: no colophon row")
    page = rows[start].page
    later = [r for r in rows[start:] if r.page != page]
    if later:
        raise ParseError(f"{where}: page {later[0].page} has rows after the colophon page {page}")
    before = [r for r in rows[:start] if r.page == page and classify(r) != HEADER]
    if before:
        raise ParseError(f"{where}: {before[0].text!r} stands before the colophon on page {page}")
    headers = tuple(r for r in rows[start:] if classify(r) == HEADER)
    colophon = tuple(r for r in rows[start:] if classify(r) != HEADER)
    return tuple(rows[:start]) + headers, colophon

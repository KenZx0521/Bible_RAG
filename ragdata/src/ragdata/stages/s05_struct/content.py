"""Passage content and the v1c text whose tokens S5 counts (design §2.14, §6, D-11(a)).

``content`` keeps the format of the old ``output/pericopes.jsonl``, which backend
and evaluation read: blocks separated by a blank line, a verse block is
``**{label}** {text}`` (``**2-3**`` for a merged unit; a half verse keeps its
integer label), and a poetry verse keeps its printed lines (a ``hard`` or
``indent`` break becomes ``\\n``; a ``soft`` break is a typesetting wrap and is
dropped; prose stays on one line). In the order of design §2.14 it also holds what
the old converter dropped: the superscription (only in the passage that opens
its chapter) and the speaker labels (before their verse, or on their own line
inside it), and （細拉） stays in the verse as printed.

``v1c_text`` is the embedding template of the old build with only its values
fixed: ``{書名} 第{章}章 {標題} ({verse_range}節)：`` followed by the block texts
joined by a space; an untitled book opening leaves the title out. Passage and
chunk token counts are counts of this text, so S6 must embed exactly it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ragdata.stages.s05_struct.view import Piece, TextView

TEMPLATE_ID = "v1c"
LINE_KINDS = frozenset({"hard", "indent"})   # line breaks that end a printed poetry line


@dataclass(frozen=True)
class Block:
    """A superscription or speaker label (no label), or a verse (its printed label)."""

    body: str
    label: str | None = None

    def render(self) -> str:
        return self.body if self.label is None else f"**{self.label}** {self.body}"


def verse_body(unit: Any, start: int, end: int | None, speakers: Iterable[Any]) -> str:
    """``unit.text[start:end]`` with poetry lines and mid-verse speaker labels laid out."""
    stop = len(unit.text) if end is None else end
    cuts = {b.offset for b in unit.line_breaks
            if unit.is_poetry and b.kind in LINE_KINDS and start < b.offset < stop}
    marks = {s.offset: s.text for s in speakers if s.pos == "mid" and start <= s.offset < stop}
    out, at = [], start
    for pos in sorted(cuts | set(marks)):
        out.append(unit.text[at:pos])
        if pos > start:
            out.append("\n")
        if pos in marks:
            out.append(marks[pos] + "\n")
        at = pos
    out.append(unit.text[at:stop])
    return "".join(out)


def opens_chapter(view: TextView, piece: Piece) -> bool:
    return piece.start == 0 and view.chapter_opener[piece.chapter_key] == piece.unit.unit_key


def superscription_of(view: TextView, pieces: Sequence[Piece]) -> Any | None:
    """The superscription a range of pieces carries: its chapter's, if it opens it."""
    first = pieces[0]
    return view.superscriptions.get(first.chapter_key) if opens_chapter(view, first) else None


def _piece_blocks(view: TextView, piece: Piece) -> list[Block]:
    speakers = view.speakers.get(piece.unit.unit_key, ())
    before = [Block(s.text) for s in speakers if s.pos == "before" and piece.start == 0]
    verse = Block(verse_body(piece.unit, piece.start, piece.end, speakers), piece.unit.label)
    return [*before, verse]


def piece_blocks(view: TextView, pieces: Sequence[Piece]) -> tuple[tuple[Block, ...], ...]:
    """The blocks of each piece, in order; the first group starts with the superscription."""
    sp = superscription_of(view, pieces)
    groups = [_piece_blocks(view, p) for p in pieces]
    if sp is not None:
        groups[0] = [Block(sp.text), *groups[0]]
    return tuple(tuple(g) for g in groups)


def _flat(groups: Iterable[Iterable[Block]]) -> list[Block]:
    return [b for group in groups for b in group]


def render(groups: Iterable[Iterable[Block]]) -> str:
    return "\n\n".join(b.render() for b in _flat(groups))


def v1c_head(book_name: str, chapter: int, title: str | None) -> str:
    return " ".join(x for x in (book_name, f"第{chapter}章", title) if x)


def v1c_text(book_name: str, chapter: int, title: str | None, verse_range: str,
             bodies: Iterable[str]) -> str:
    return f"{v1c_head(book_name, chapter, title)} ({verse_range}節)：" + " ".join(bodies)


def bodies(groups: Iterable[Iterable[Block]]) -> list[str]:
    return [b.body for b in _flat(groups)]

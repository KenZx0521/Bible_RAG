"""S5 segmentation (design §2.13, §2.14, §2.23; D-10(a)).

Every heading position opens a section (a pericope); headings stacked at one
position open one section, titled by the lowest of them, whose parent is the
stacked heading above it. A book whose text starts before its first heading
opens with an untitled section. A mid-verse heading cuts its unit: the section
before it ends at the heading's offset and the next starts there. Sections run
across chapters; their passages are cut at chapter ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import Any, Sequence

from ragcommon import ids
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct.view import Piece, TextView

__all__ = ["Piece", "Section", "passage_pieces", "sections"]
UNTITLED_REASON = "book_opening"


@dataclass(frozen=True)
class Section:
    """One pericope before it is written out."""

    book_id: str
    headings: tuple[Any, ...]   # stacked at its start, outermost first; () for a book opening
    pieces: tuple[Piece, ...]

    @property
    def heading(self) -> Any | None:
        return self.headings[-1] if self.headings else None

    @property
    def section_heading_id(self) -> str | None:
        return None if self.heading is None else self.heading.parent_heading_id

    @property
    def title(self) -> str | None:
        return None if self.heading is None else self.heading.display_title

    @property
    def pericope_id(self) -> str:
        return ids.pericope_id(self.pieces[0].first_key)


def _check_stack(stack: Sequence[Any]) -> None:
    for upper, lower in zip(stack, stack[1:]):
        if lower.parent_heading_id != upper.heading_id:
            raise StageError(f"{upper.heading_id} is stacked above {lower.heading_id} but is not "
                             f"its parent heading; merging them would lose {upper.heading_id}")


def _pieces(units: Sequence[Any], start: tuple[int, int], stop: tuple[int, int]
            ) -> tuple[Piece, ...]:
    """The text from position ``start`` up to (not including) position ``stop``."""
    (first, offset), (last, end) = start, stop
    out = []
    for i in range(first, last + (1 if end > 0 else 0)):
        piece = Piece(units[i], offset if i == first else 0, end if i == last and end > 0 else None)
        text_end = len(piece.unit.text) if piece.end is None else piece.end
        if not piece.start < text_end:
            raise StageError(f"{piece.unit.unit_key}: a heading at offset {piece.start} leaves an "
                             "empty piece of text")
        out.append(piece)
    return tuple(out)


def sections(view: TextView, book_id: str) -> list[Section]:
    """The sections of one book in order; together they hold every character once."""
    units = view.units[book_id]
    stacks = dict(view.stacks.get(book_id, {}))
    for stack in stacks.values():
        _check_stack(stack)
    starts = sorted(stacks) if (0, 0) in stacks else [(0, 0), *sorted(stacks)]
    stops = [*starts[1:], (len(units), 0)]
    return [Section(book_id, stacks.get(start, ()), _pieces(units, start, stop))
            for start, stop in zip(starts, stops)]


def passage_pieces(section: Section) -> list[tuple[Piece, ...]]:
    """The pieces of a section, cut at chapter ends."""
    return [tuple(group) for _, group in groupby(section.pieces, key=lambda p: p.chapter_key)]

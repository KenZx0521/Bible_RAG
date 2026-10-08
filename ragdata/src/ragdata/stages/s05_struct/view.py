"""What S5 reads of the text layer, indexed once: units in canonical order, heading
stacks by position, superscriptions and speakers. G-STRUCT reads the same view."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.gates.base import Snapshot
from ragdata.stages.errors import StageError

# (index of the unit in its book, offset in the unit) -> headings stacked there, outermost first
Stacks = Mapping[tuple[int, int], tuple[Any, ...]]


@dataclass(frozen=True)
class Piece:
    """The part ``[start, end)`` of a unit's text (``end`` None: to the end of the unit)."""

    unit: Any
    start: int = 0
    end: int | None = None

    @property
    def chapter_key(self) -> str:
        return ids.chapter_key(self.unit.book_id, self.unit.chapter)

    @property
    def first_key(self) -> str:
        """The key a range starting here begins with (``b`` on a second half)."""
        u = self.unit
        return ids.verse_key(u.book_id, u.chapter, u.v_start, half=self.start > 0)

    @property
    def last_key(self) -> str:
        """The key a range ending here ends with (the last slot of a merged unit)."""
        u = self.unit
        return ids.verse_key(u.book_id, u.chapter, u.v_end, half=self.start > 0)

    def ref(self) -> dict[str, Any]:
        return {"unit_key": self.unit.unit_key, "from": self.start, "to": self.end}


def slot_of(key: str) -> str:
    p = ids.parse(key)
    return ids.slot_key(p.book_id, p.chapter, p.verse)


def key_range(pieces: Sequence[Piece]) -> tuple[str, str, str]:
    """(start_key, end_key, verse_range) of consecutive pieces within one chapter."""
    start, end = pieces[0].first_key, pieces[-1].last_key
    first, last = ids.parse(start).verse, ids.parse(end).verse
    return start, end, str(first) if first == last else f"{first}-{last}"


@dataclass(frozen=True)
class TextView:
    books: tuple[Any, ...]                       # canonical order
    units: Mapping[str, tuple[Any, ...]]         # book_id -> units in canonical order
    unit: Mapping[str, Any]                      # unit_key -> unit
    stacks: Mapping[str, Stacks]                 # book_id -> heading stacks by position
    superscriptions: Mapping[str, Any]           # chapter_key -> superscription
    speakers: Mapping[str, tuple[Any, ...]]      # unit_key -> speakers in order
    chapter_opener: Mapping[str, str]            # chapter_key -> its first unit_key
    omitted: frozenset[str]                      # slot keys the PDF omits (omitted_variant)

    def book_name(self, book_id: str) -> str:
        return next(b.name for b in self.books if b.book_id == book_id)


def _seq(record_id: str) -> int:
    return ids.parse(record_id).seq


def _stacks(snapshot: Snapshot, units: Mapping[str, tuple[Any, ...]]) -> dict[str, Stacks]:
    index = {u.unit_key: i for book in units.values() for i, u in enumerate(book)}
    found: dict[str, dict[tuple[int, int], list[Any]]] = defaultdict(lambda: defaultdict(list))
    for h in sorted(snapshot.of("headings"), key=lambda h: _seq(h.heading_id)):
        if h.anchor_unit_key not in index:
            raise StageError(f"{h.heading_id}: anchor {h.anchor_unit_key} is not a unit")
        found[h.book_id][(index[h.anchor_unit_key], h.anchor_offset)].append(h)
    return {book: MappingProxyType({pos: tuple(hs) for pos, hs in sorted(stacks.items())})
            for book, stacks in found.items()}


def text_view(snapshot: Snapshot) -> TextView:
    """Index the text records of ``snapshot`` (records that passed their contracts)."""
    books = tuple(sorted(snapshot.of("books"), key=lambda b: b.ord))
    by_book: dict[str, list[Any]] = defaultdict(list)
    for u in sorted(snapshot.of("verse_units"), key=lambda u: u.ord):
        by_book[u.book_id].append(u)
    units = {b.book_id: tuple(by_book[b.book_id]) for b in books}
    openers: dict[str, str] = {}
    for u in (u for book in units.values() for u in book):
        openers.setdefault(ids.chapter_key(u.book_id, u.chapter), u.unit_key)
    speakers: dict[str, list[Any]] = defaultdict(list)
    for s in sorted(snapshot.of("speakers"), key=lambda s: _seq(s.sk_id)):
        speakers[s.unit_key].append(s)
    return TextView(
        books=books, units=MappingProxyType(units),
        unit=MappingProxyType({u.unit_key: u for book in units.values() for u in book}),
        stacks=MappingProxyType(_stacks(snapshot, units)),
        superscriptions=MappingProxyType({t.chapter_key: t for t in snapshot.of("chapter_texts")
                                          if t.kind == "superscription"}),
        speakers=MappingProxyType({k: tuple(v) for k, v in speakers.items()}),
        chapter_opener=MappingProxyType(openers),
        omitted=frozenset(s.slot_key for s in snapshot.of("verse_slots")
                          if s.status == "omitted_variant"),
    )

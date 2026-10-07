"""Struct-layer record contracts (design §2.13–2.15, decision D-10(a)).

A pericope may cross chapters; its passages are cut at chapter boundaries.
Keys with a ``b`` suffix mark the second half of a verse split by a mid-verse
heading: the split verse appears in the integer ``verse_range`` of both sides.
"""

from __future__ import annotations

from dataclasses import dataclass

from ragcommon import ids
from ragdata.contract.fields import (
    Record, boolean, hex64, id_of, integer, list_of, nested, one_of, optional, parsed,
    require, sha256_text, spec, string, verse_order,
)

PDF = one_of("pdf_deterministic")
CHUNK_MAX_TOKENS = 768


def _range_label(first: int, last: int) -> str:
    return str(first) if first == last else f"{first}-{last}"


def _slot_of(key: str) -> str:
    p = parsed(key)
    return ids.slot_key(p.book_id, p.chapter, p.verse)


def _in_unit(slot: str, unit_key: str) -> bool:
    s, u = parsed(slot), parsed(unit_key)
    return ((s.book_id, s.chapter) == (u.book_id, u.chapter)
            and u.verse <= s.verse <= (u.verse_end or u.verse))


def _check_key_range(start_key: str, end_key: str, verse_range: str) -> None:
    """Both keys in one chapter, ascending, and ``verse_range`` spells their verses."""
    s, e = parsed(start_key), parsed(end_key)
    require((s.book_id, s.chapter) == (e.book_id, e.chapter), "range must stay in one chapter")
    require(verse_order(start_key) <= verse_order(end_key), "range descends")
    label = _range_label(s.verse, e.verse)
    require(verse_range == label, f"verse_range must be {label!r}")


@dataclass(frozen=True)
class Position(Record):
    unit_key: str = spec(id_of("unit"))
    offset: int | None = spec(optional(integer(0)))


@dataclass(frozen=True)
class UnitRef(Record):
    unit_key: str = spec(id_of("unit"))
    from_: int = spec(integer(0), key="from")
    to: int | None = spec(optional(integer(1)))

    def check(self) -> None:
        require(self.to is None or self.to > self.from_, "unit ref must not be empty")


@dataclass(frozen=True)
class Pericope(Record):
    pericope_id: str = spec(id_of("pericope"))
    book_id: str = spec(id_of("book"))
    heading_id: str | None = spec(optional(id_of("heading")))
    section_heading_id: str | None = spec(optional(id_of("heading")))
    title: str | None = spec(optional(string()))
    untitled_reason: str | None = spec(optional(one_of("book_opening")))
    start: Position = spec(nested(Position))
    end: Position = spec(nested(Position))
    start_slot: str = spec(id_of("slot"))
    end_slot: str = spec(id_of("slot"))
    chapters: tuple = spec(list_of(integer(1), min_len=1))
    passage_ids: tuple = spec(list_of(id_of("passage"), min_len=1))
    prev_id: str | None = spec(optional(id_of("pericope")))
    next_id: str | None = spec(optional(id_of("pericope")))
    next_book_id: str | None = spec(optional(id_of("book")))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        titled = self.heading_id is not None
        require(titled == (self.untitled_reason is None), "untitled_reason iff no heading")
        require(not titled or self.title is not None, "a titled pericope has a title")
        require(self.start.offset is not None, "start offset is required")
        half = self.start.offset > 0
        expected = ids.pericope_id(ids.verse_key(*_book_ch_v(self.start_slot), half=half))
        require(self.pericope_id == expected, f"pericope_id must be {expected!r}")
        require(_in_unit(self.start_slot, self.start.unit_key)
                and _in_unit(self.end_slot, self.end.unit_key), "slots must lie in their units")
        require(parsed(self.start_slot).book_id == self.book_id == parsed(self.end_slot).book_id,
                "pericope must stay in its book")
        require(verse_order(self.start_slot) <= verse_order(self.end_slot), "range descends")
        first, last = parsed(self.start_slot).chapter, parsed(self.end_slot).chapter
        require(list(self.chapters) == list(range(first, last + 1)), "chapters must be contiguous")
        require(self.pericope_id not in (self.prev_id, self.next_id), "pericope links to itself")


def _book_ch_v(slot: str) -> tuple[str, int, int]:
    p = parsed(slot)
    return p.book_id, p.chapter, p.verse


@dataclass(frozen=True)
class Passage(Record):
    passage_id: str = spec(id_of("passage"))
    pericope_id: str = spec(id_of("pericope"))
    chapter_key: str = spec(id_of("chapter"))
    seg_idx: int = spec(integer(0))
    seg_count: int = spec(integer(1))
    continued: bool = spec(boolean())
    title: str | None = spec(optional(string()))
    start_slot: str = spec(id_of("slot"))
    end_slot: str = spec(id_of("slot"))
    verse_range: str = spec(string())
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    start_partial: bool = spec(boolean())
    end_partial: bool = spec(boolean())
    unit_refs: tuple = spec(list_of(nested(UnitRef), min_len=1))
    superscription_id: str | None = spec(optional(id_of("superscription")))
    content: str = spec(string())
    content_sha: str = spec(hex64())
    token_count: int = spec(integer(0))
    requires_chunking: bool = spec(boolean())
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        require(self.passage_id == ids.passage_id(self.start_key), "passage_id must be ps:{start_key}")
        require(self.start_slot == _slot_of(self.start_key) and self.end_slot == _slot_of(self.end_key),
                "start_slot/end_slot must be the slots of start_key/end_key")
        _check_key_range(self.start_key, self.end_key, self.verse_range)
        p = parsed(self.start_key)
        require(self.chapter_key == ids.chapter_key(p.book_id, p.chapter), "chapter_key mismatch")
        require(self.seg_idx < self.seg_count, "seg_idx must be below seg_count")
        require(self.continued == (self.seg_idx > 0), "continued iff seg_idx > 0")
        require(self.start_partial == p.half, "start_partial iff start_key has b")
        require(not (self.end_partial and parsed(self.end_key).half),
                "a b end key runs to the end of its verse")
        require(self.superscription_id in (None, ids.superscription_id(self.chapter_key)),
                "superscription_id must be sp:{chapter_key}")
        require(self.content_sha == sha256_text(self.content), "content_sha is not sha256(content)")
        require(self.requires_chunking == (self.token_count > CHUNK_MAX_TOKENS),
                f"requires_chunking iff token_count > {CHUNK_MAX_TOKENS}")


@dataclass(frozen=True)
class Chunk(Record):
    chunk_id: str = spec(id_of("chunk"))
    passage_id: str = spec(id_of("passage"))
    idx: int = spec(integer(0))
    unit_refs: tuple = spec(list_of(nested(UnitRef), min_len=1))
    overlap_unit_keys: tuple = spec(list_of(id_of("unit")))
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    verse_range: str = spec(string())
    token_count: int = spec(integer(1, CHUNK_MAX_TOKENS))
    provenance_class: str = spec(PDF)

    def check(self) -> None:
        expected = ids.chunk_id(self.start_key, self.end_key)
        require(self.chunk_id == expected, f"chunk_id must be {expected!r}")
        _check_key_range(self.start_key, self.end_key, self.verse_range)

"""Pinned RCUV text access for bt.py and annotate.py (verse text, passages, books, keys).

Reads the text and struct layers through the same pinned reader as gd_common (manifest
digest → layer version, then each file's sha256), so the agents' tool and the §4 gold see
one and the same layer. Key resolution is gd.resolve_key (bt.py:43-70 find_unit/resolve)
and passages are gd's verse_index (passage_id first, then split_passage_ids).
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from _ho_common import gd  # first: puts the experiment directory on sys.path

import _gd_store  # noqa: E402  pinned layer reader shared with gd_common (_layer_bytes)

__all__ = ["Verse", "Book", "verses", "passage_meta", "books", "resolve", "unit_passages",
           "KeyStatus"]


@dataclass(frozen=True)
class Verse:
    key: str              # unit_key (whole verse, or merged like gen.24.29-30)
    book_id: str
    text: str


@dataclass(frozen=True)
class Book:
    book_id: str
    name: str
    chapters: int


@dataclass(frozen=True)
class KeyStatus:
    """bt-style resolution of one slot key: its units, or why it has none."""
    key: str
    units: tuple[str, ...]
    problem: str | None = None        # "not found" | "half verse"


def _rows(layer: str, name: str) -> list[dict]:
    data = _gd_store._layer_bytes(gd.LAYERS_ROOT, layer, name)
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


@functools.cache
def verses() -> Mapping[str, Verse]:
    """unit_key -> Verse, in verse_units.jsonl order."""
    out = {r["unit_key"]: Verse(r["unit_key"], r["book_id"], r["text"])
           for r in _rows("text", "verse_units.jsonl")}
    gd.expect("verse units", len(out), gd.N_VERSE_UNITS)
    return MappingProxyType(out)


@functools.cache
def passage_meta() -> Mapping[str, tuple[str, str, str]]:
    """passage_id -> (title, start_key, end_key)."""
    return MappingProxyType({p.passage_id: (p.title, p.start_key, p.end_key)
                             for p in gd.load_passages()})


@functools.cache
def books() -> tuple[Book, ...]:
    out = tuple(Book(r["book_id"], r["name"], int(r["chapter_count"]))
                for r in _rows("text", "books.jsonl"))
    gd.expect("books", len(out), gd.N_BOOKS)
    return out


def resolve(key: str) -> KeyStatus:
    """Units of one slot key (a whole, merged or range key); half-verse and unknown keys
    resolve to nothing, with the reason."""
    if gd.is_half_verse_key(key):
        return KeyStatus(key, (), "half verse")
    try:
        return KeyStatus(key, gd.resolve_key(key))
    except gd.GoldError:
        return KeyStatus(key, (), "not found")


def unit_passages(unit_key: str) -> tuple[str, ...]:
    """§4 passages of a unit: passage_id, then its split_passage_ids."""
    vi = gd.load_verse_index()
    return (vi.passage_of[unit_key], *vi.split_of[unit_key])

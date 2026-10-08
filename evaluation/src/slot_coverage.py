"""Verse coverage on the GT v2 slot universe (design §11.2): one ruler for both arms.

* Gold is the item's ``gold_slots``: slots of the GT header's slot_universe
  that hold text. Omitted slots (verses found only in a variant footnote) are
  never gold.
* Anchors split each structured ref per chapter (a chapter range gives one per
  chapter; a cross-chapter verse range its head, middle chapters and tail).
  An anchor holds its gold slots; one without gold is dropped.
* A source maps to the slots it holds. A legacy-20261004 source keeps the
  legacy numbering (31,102 verses), which is the PDF numbering except for the
  ghost verses, so book/chapter/verse_range map to slots by number: a ghost
  verse lands on its omitted slot and is never gold. A source of a new build
  maps through that build's ``contracts/{build_id}/verse_index.json``, by
  start_key/end_key when it has them, else by book/chapter/verse_range, and a
  merged unit counts whole.

Chapter-level sources take the chapter's actual slots, never 1..N of a count
table. A verse number without a slot goes through ref_aliases (jhn.7.53 →
jhn.8.1). Anything the ruler cannot map raises SlotCoverageError.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from ragcommon import ids
from ragcommon.versification import Versification, default_versification

from .book_names import book_id_of
from .gt_v2 import GroundTruthItemV2
from .models import SourceInfo

VERSE_INDEX_SCHEMA = "ragdata.contract.verse_index.v1"
_VERSE_RANGE = re.compile(r"(\d+)(?:\s*[-–~]\s*(\d+))?")

Chapter = tuple[str, int]
SourceMapper = Callable[[SourceInfo], frozenset[str]]


class SlotCoverageError(ValueError):
    """A ruler that cannot be built, or a source it cannot map to slots."""


@dataclass(frozen=True)
class SlotGrid:
    """One verse grid: each chapter's (verse, slot key) pairs, in order."""

    chapters: Mapping[Chapter, tuple[tuple[int, str], ...]]
    order: tuple[str, ...]
    position: Mapping[str, int]
    unit_mates: Mapping[str, tuple[str, ...]]   # slot -> every slot of its merged unit

    def chapter(self, book_id: str, chapter: int) -> tuple[tuple[int, str], ...]:
        found = self.chapters.get((book_id, chapter))
        if found is None:
            raise SlotCoverageError(f"no chapter {book_id} {chapter} in the verse grid")
        return found

    def verses(self, book_id: str, chapter: int, first: int, last: int | None) -> tuple[str, ...]:
        return tuple(key for verse, key in self.chapter(book_id, chapter)
                     if verse >= first and (last is None or verse <= last))

    def span(self, first: str, last: str) -> tuple[str, ...]:
        """Slots from ``first`` to ``last`` (inclusive) in grid order."""
        missing = [key for key in (first, last) if key not in self.position]
        if missing:
            raise SlotCoverageError(f"slots {missing} are not in the verse grid")
        start, end = self.position[first], self.position[last]
        if end < start or ids.parse(first).book_id != ids.parse(last).book_id:
            raise SlotCoverageError(f"span {first}..{last} is not ascending within one book")
        return self.order[start:end + 1]

    def with_units(self, slots: Iterable[str]) -> frozenset[str]:
        return frozenset(mate for slot in slots for mate in self.unit_mates.get(slot, (slot,)))


def _grid(rows: Iterable[tuple[str, int, int, str]],
          units: Mapping[str, tuple[str, ...]] | None = None) -> SlotGrid:
    chapters: dict[Chapter, list[tuple[int, str]]] = {}
    position: dict[str, int] = {}
    for book_id, chapter, verse, key in rows:
        chapters.setdefault((book_id, chapter), []).append((verse, key))
        position[key] = len(position)
    return SlotGrid(MappingProxyType({c: tuple(v) for c, v in chapters.items()}),
                    tuple(position), MappingProxyType(position),
                    MappingProxyType(dict(units or {})))


def grid_from_versification(vers: Versification) -> SlotGrid:
    """The slot universe of a versification: every slot, omitted ones included."""
    return _grid((book_id, chapter, verse, f"{book_id}.{chapter}.{verse}")
                 for book_id, per_chapter in vers.max_verses.items()
                 for chapter, top in enumerate(per_chapter, start=1)
                 for verse in range(1, top + 1))


def grid_from_verse_index(slots: list[Mapping]) -> SlotGrid:
    """A build's grid from its verse_index slots, with merged units."""
    rows, by_unit = [], {}
    for rec in slots:
        parsed = ids.validate(rec["slot_key"], "slot")
        rows.append((parsed.book_id, parsed.chapter, parsed.verse, parsed.raw))
        if rec.get("unit_key"):
            by_unit.setdefault(rec["unit_key"], []).append(parsed.raw)
    units = {slot: tuple(mates) for mates in by_unit.values() if len(mates) > 1 for slot in mates}
    return _grid(rows, units)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise SlotCoverageError(f"cannot read {path}: {exc}") from None


def load_verse_index(contracts_dir: Path, build_id: str) -> SlotGrid:
    """The build's verse grid; its manifest must name ``build_id`` and the file's sha256."""
    manifest = _read_json(contracts_dir / "manifest.json")
    if manifest.get("build_id") != build_id:
        raise SlotCoverageError(f"{contracts_dir} holds build {manifest.get('build_id')!r}, "
                                f"not {build_id!r}")
    path = contracts_dir / "verse_index.json"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SlotCoverageError(f"cannot read {path}: {exc}") from None
    expected = manifest.get("files", {}).get("verse_index.json")
    if hashlib.sha256(data).hexdigest() != expected:
        raise SlotCoverageError(f"{path} does not match the sha256 in its manifest")
    doc = json.loads(data)
    if doc.get("schema") != VERSE_INDEX_SCHEMA:
        raise SlotCoverageError(f"{path}: schema {doc.get('schema')!r}, not {VERSE_INDEX_SCHEMA}")
    return grid_from_verse_index(doc["slots"])


# ---------------------------------------------------------------- sources


def _verse_span(verse_range: str, source_id: str) -> tuple[int, int]:
    m = _VERSE_RANGE.fullmatch(verse_range)
    first, last = (int(m.group(1)), int(m.group(2) or m.group(1))) if m else (0, -1)
    if first < 1 or last < first:
        raise SlotCoverageError(f"{source_id}: unreadable verse_range {verse_range!r}")
    return first, last


def _slot_or_alias(by_verse: Mapping[int, str], universe: Versification,
                   book_id: str, chapter: int, verse: int) -> str:
    if verse in by_verse:
        return by_verse[verse]
    alias = universe.alias(ids.slot_key(book_id, chapter, verse))
    if alias is None:
        raise SlotCoverageError(f"no slot or ref alias for {book_id} {chapter}:{verse}")
    return alias.target


def numbered_slots(grid: SlotGrid, universe: Versification, source: SourceInfo) -> frozenset[str]:
    """Slots named by a source's book, chapter and verse_range ("" = the whole chapter)."""
    book_id = book_id_of(source.book)
    if book_id is None or source.chapter is None:
        raise SlotCoverageError(f"{source.id}: no book/chapter to map ({source.book!r}, "
                                f"{source.chapter!r})")
    in_chapter = grid.chapter(book_id, source.chapter)
    verse_range = (source.verse_range or "").strip()
    if not verse_range:
        return frozenset(key for _, key in in_chapter)
    first, last = _verse_span(verse_range, source.id)
    by_verse = dict(in_chapter)
    return frozenset(_slot_or_alias(by_verse, universe, book_id, source.chapter, v)
                     for v in range(first, last + 1))


def _key_slot(key: str, last: bool) -> str:
    try:
        parsed = ids.parse(key)
    except ids.IdError as exc:
        raise SlotCoverageError(str(exc)) from None
    if parsed.kind not in ("slot", "key", "unit"):
        raise SlotCoverageError(f"{key!r} is a {parsed.kind}, not a verse key")
    verse = parsed.verse_end if last and parsed.verse_end else parsed.verse
    return ids.slot_key(parsed.book_id, parsed.chapter, verse)


def keyed_slots(grid: SlotGrid, source: SourceInfo) -> frozenset[str]:
    """Slots from a source's start_key to its end_key, in grid order."""
    if not (source.start_key and source.end_key):
        raise SlotCoverageError(f"{source.id}: start_key and end_key come together")
    return frozenset(grid.span(_key_slot(source.start_key, False), _key_slot(source.end_key, True)))


def legacy_mapper(universe_grid: SlotGrid, universe: Versification) -> SourceMapper:
    """legacy-20261004: verse numbers straight onto the universe's slots."""
    return lambda source: numbered_slots(universe_grid, universe, source)


def build_mapper(grid: SlotGrid, universe: Versification) -> SourceMapper:
    """A new build: start/end keys, else book/chapter/verse_range, on the build's grid."""
    def mapped(source: SourceInfo) -> frozenset[str]:
        if source.start_key or source.end_key:
            return grid.with_units(keyed_slots(grid, source))
        return grid.with_units(numbered_slots(grid, universe, source))
    return mapped


# ---------------------------------------------------------------- ruler


def gold_anchors(item: GroundTruthItemV2, universe: SlotGrid) -> list[frozenset[str]]:
    """Per-chapter pieces of the item's refs, each reduced to its gold slots."""
    gold = frozenset(item.gold_slots)
    anchors: list[frozenset[str]] = []
    for ref in item.refs:
        for chapter in range(ref.ch, ref.ch_end + 1):
            first = ref.v_start if chapter == ref.ch and ref.v_start is not None else 1
            last = ref.v_end if chapter == ref.ch_end else None
            anchor = frozenset(universe.verses(ref.book_id, chapter, first, last)) & gold
            if anchor and anchor not in anchors:
                anchors.append(anchor)
    return anchors


@dataclass(frozen=True)
class SlotRuler:
    build_id: str
    universe: SlotGrid
    map_source: SourceMapper

    def source_slots(self, sources: Iterable[SourceInfo]) -> frozenset[str]:
        return frozenset().union(*(self.map_source(s) for s in sources))

    def verse_metrics(self, item: GroundTruthItemV2,
                      sources: list[SourceInfo]) -> tuple[float, float]:
        """(verse_recall, anchor_coverage) of one item's top-k sources."""
        gold = frozenset(item.gold_slots)
        anchors = gold_anchors(item, self.universe)
        retrieved = self.source_slots(sources)
        recall = len(gold & retrieved) / len(gold) if gold else 0.0
        coverage = sum(1 for a in anchors if a & retrieved) / len(anchors) if anchors else 0.0
        return round(recall, 4), round(coverage, 4)


def universe_versification(slot_universe: str) -> Versification:
    """ragcommon's verse grid, which must be the one GT v2 froze its slots against."""
    vers = default_versification()
    layer = vers.source.get("layer_version")
    if layer != slot_universe:
        raise SlotCoverageError(f"ragcommon's verse grid is {layer}, the GT slot_universe "
                                f"is {slot_universe}")
    return vers


def build_ruler(slot_universe: str, build_id: str, contracts_dir: Path | None) -> SlotRuler:
    """The ruler for one arm: the GT universe plus how this build's sources map to slots."""
    vers = universe_versification(slot_universe)
    universe = grid_from_versification(vers)
    if build_id == ids.LEGACY_BUILD_ID:
        return SlotRuler(build_id, universe, legacy_mapper(universe, vers))
    if contracts_dir is None:
        raise SlotCoverageError(f"build {build_id} needs its contracts directory")
    return SlotRuler(build_id, universe, build_mapper(load_verse_index(contracts_dir, build_id), vers))

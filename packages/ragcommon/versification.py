"""Verse grid of the PDF edition plus the external-reference alias table.

``data/versification.json`` holds every chapter's max verse and the 11 omitted
slots (``status=omitted_variant``); it is interim data derived from the audit
prototype (see its ``source`` field) until the text layer overwrites it.
``data/ref_aliases.jsonl`` lists external verse numbers that have no PDF slot
(design §2.12), e.g. ``jhn.7.53 → contained_in jhn.8.1``. Resolution never
falls back silently: a verse with neither a slot nor an alias raises.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from ragcommon import books, ids

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_PATH = DATA_DIR / "versification.json"
ALIASES_PATH = DATA_DIR / "ref_aliases.jsonl"
SCHEMA = "ragcommon.versification.v1"
ALIAS_RELATIONS = frozenset({"contained_in"})


class VersificationError(ValueError):
    """Bad versification data, or a verse the PDF edition has no slot for."""


@dataclass(frozen=True)
class OmittedSlot:
    slot_key: str
    variant_in_footnote_of: str


@dataclass(frozen=True)
class RefAlias:
    external_ref: str
    relation: str
    target: str
    note: str
    provenance_class: str


@dataclass(frozen=True)
class Versification:
    max_verses: Mapping[str, tuple[int, ...]]
    omitted: Mapping[str, OmittedSlot]
    aliases: Mapping[str, RefAlias]
    source: Mapping[str, str]

    def chapter_count(self, book_id: str) -> int:
        if book_id not in self.max_verses:
            raise books.UnknownBookError(book_id)
        return len(self.max_verses[book_id])

    def has_chapter(self, book_id: str, chapter: int) -> bool:
        return 1 <= chapter <= self.chapter_count(book_id)

    def max_verse(self, book_id: str, chapter: int) -> int:
        if not self.has_chapter(book_id, chapter):
            raise VersificationError(f"{book_id} has no chapter {chapter}")
        return self.max_verses[book_id][chapter - 1]

    def has_slot(self, book_id: str, chapter: int, verse: int) -> bool:
        return self.has_chapter(book_id, chapter) and 1 <= verse <= self.max_verse(book_id, chapter)

    def is_omitted(self, slot_key: str) -> bool:
        return slot_key in self.omitted

    def alias(self, external_ref: str) -> RefAlias | None:
        return self.aliases.get(external_ref)

    def resolve(self, book_id: str, chapter: int, verse: int) -> tuple[str, RefAlias | None]:
        """Map a verse number to its PDF slot key, through ref_aliases if needed."""
        if self.has_slot(book_id, chapter, verse):
            return ids.slot_key(book_id, chapter, verse), None
        external = f"{book_id}.{chapter}.{verse}"
        alias = self.aliases.get(external)
        if alias is None:
            raise VersificationError(f"no PDF slot or alias for {external}")
        return alias.target, alias

    def slot_count(self) -> int:
        return sum(sum(per_chapter) for per_chapter in self.max_verses.values())

    def iter_slot_keys(self) -> Iterator[str]:
        for book_id, per_chapter in self.max_verses.items():
            for chapter, top in enumerate(per_chapter, start=1):
                for verse in range(1, top + 1):
                    yield f"{book_id}.{chapter}.{verse}"


def _max_verses(raw: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    expected = books.book_ids()
    if set(raw) != set(expected):
        diff = sorted(set(raw) ^ set(expected))
        raise VersificationError(f"max_verse books differ from books.json: {diff}")
    result = {}
    for book_id in expected:
        values = raw[book_id]
        if not values or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in values):
            raise VersificationError(f"{book_id}: max_verse must be a non-empty list of ints >= 1")
        result[book_id] = tuple(values)
    return result


def _slot_of(key: str, grid: Mapping[str, tuple[int, ...]], what: str) -> ids.ParsedId:
    try:
        parsed = ids.validate(key, "slot")
    except ids.IdError as exc:
        raise VersificationError(f"{what}: not a slot key {key!r}") from exc
    per_chapter = grid[parsed.book_id]
    if parsed.chapter > len(per_chapter) or parsed.verse > per_chapter[parsed.chapter - 1]:
        raise VersificationError(f"{what}: {key} is outside the verse grid")
    return parsed


def _omitted(raw: list[Mapping[str, str]], grid) -> dict[str, OmittedSlot]:
    result: dict[str, OmittedSlot] = {}
    for rec in raw:
        slot = _slot_of(rec.get("slot_key", ""), grid, "omitted slot")
        if slot.raw in result:
            raise VersificationError(f"duplicate omitted slot {slot.raw}")
        note = rec.get("variant_in_footnote_of", "")
        if not ids.is_valid(note, "unit"):
            raise VersificationError(f"{slot.raw}: bad variant_in_footnote_of {note!r}")
        result[slot.raw] = OmittedSlot(slot.raw, note)
    return result


def _alias(rec: Mapping[str, Any], grid, omitted) -> RefAlias:
    for field in ("external_ref", "relation", "target", "provenance_class"):
        if not rec.get(field):
            raise VersificationError(f"ref alias missing {field}: {rec!r}")
    if rec["relation"] not in ALIAS_RELATIONS:
        raise VersificationError(f"unknown alias relation {rec['relation']!r}")
    try:
        external = ids.validate(rec["external_ref"], "slot")
    except ids.IdError as exc:
        raise VersificationError(f"alias external_ref must be a slot key: {rec!r}") from exc
    per_chapter = grid[external.book_id]
    if external.chapter <= len(per_chapter) and external.verse <= per_chapter[external.chapter - 1]:
        raise VersificationError(f"{external.raw} exists in the PDF; it needs no alias")
    target = _slot_of(rec["target"], grid, "alias target")
    if target.raw in omitted:
        raise VersificationError(f"alias target {target.raw} is an omitted slot")
    return RefAlias(external.raw, rec["relation"], target.raw, rec.get("note", ""), rec["provenance_class"])


def _read_alias_records(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_versification(path: Path | str = DATA_PATH,
                       aliases_path: Path | str = ALIASES_PATH) -> Versification:
    """Load and validate the verse grid and the alias table (JSONL or JSON array)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise VersificationError(f"unexpected schema {doc.get('schema')!r}")
    grid = _max_verses(doc.get("max_verse", {}))
    omitted = _omitted(doc.get("omitted_slots", []), grid)
    aliases: dict[str, RefAlias] = {}
    for rec in _read_alias_records(Path(aliases_path)):
        alias = _alias(rec, grid, omitted)
        if alias.external_ref in aliases:
            raise VersificationError(f"duplicate alias {alias.external_ref}")
        aliases[alias.external_ref] = alias
    return Versification(
        max_verses=MappingProxyType(grid),
        omitted=MappingProxyType(omitted),
        aliases=MappingProxyType(aliases),
        source=MappingProxyType(dict(doc.get("source", {}))),
    )


@lru_cache(maxsize=1)
def default_versification() -> Versification:
    return load_versification(DATA_PATH, ALIASES_PATH)

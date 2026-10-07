"""The service text GT v2 is aligned to: ``verse_units.text`` of one text layer.

Clauses are matched on Han characters only (``textnorm.norm``). Units are
joined in layer order within a chapter, so a quotation may run across verse
boundaries but never across chapters. At errata positions the PDF glyph
(``text_pdf``) is accepted as well (design §11.3): both texts have the same
length, so they share one offset table.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from ragdata.gt.textnorm import norm
from ragdata.store import LayerData

CHAPTER_SEP = "|"
GOLD_STATUSES = frozenset({"present", "merged"})
OMITTED_STATUS = "omitted_variant"
DOT = "‧"


class CorpusError(ValueError):
    """The text layer cannot serve as the GT slot universe."""


@dataclass(frozen=True)
class _Index:
    text: str           # normalised service text, chapters joined by CHAPTER_SEP
    text_pdf: str       # the same with the PDF glyphs at errata positions
    starts: tuple[int, ...]
    unit_keys: tuple[str, ...]


@dataclass(frozen=True)
class ServiceText:
    version: str
    slot_status: Mapping[str, str]
    slot_unit: Mapping[str, str | None]
    unit_first_slot: Mapping[str, str]
    raw: str            # verse_units.text joined by newlines, for counting written forms
    errata_words: tuple[tuple[str, str, tuple[str, ...]], ...]   # (pdf word, word, containers)
    dotted_names: tuple[str, ...]    # ‧ names whose bare form is never written; longest first
    _index: _Index
    _unit_norm: Mapping[str, str]
    _unit_chapter: Mapping[str, tuple[str, int]]

    @classmethod
    def from_layer(cls, layer: LayerData) -> "ServiceText":
        if layer.layer != "text":
            raise CorpusError(f"{layer.version}: GT v2 needs a text layer")
        return cls.from_rows(layer.version, layer.rows)

    @classmethod
    def from_rows(cls, version: str, rows: Mapping[str, Sequence[Mapping]]) -> "ServiceText":
        units = rows["verse_units.jsonl"]
        slots = rows["verse_slots.jsonl"]
        unit_keys = {u["unit_key"] for u in units}
        first_slot: dict[str, str] = {}
        for s in slots:
            if s["unit_key"] is not None and s["unit_key"] not in unit_keys:
                raise CorpusError(f"slot {s['slot_key']} points at missing unit {s['unit_key']}")
            if s["unit_key"] is not None:
                first_slot.setdefault(s["unit_key"], s["slot_key"])
        raw = "\n".join(u["text"] for u in units)
        return cls(
            version=version,
            slot_status=MappingProxyType({s["slot_key"]: s["status"] for s in slots}),
            slot_unit=MappingProxyType({s["slot_key"]: s["unit_key"] for s in slots}),
            unit_first_slot=MappingProxyType(first_slot),
            raw=raw,
            errata_words=_errata_words(rows["errata_applied.jsonl"]),
            dotted_names=_dotted_names(rows["name_spans.jsonl"], raw),
            _index=_build_index(units),
            _unit_norm=MappingProxyType({u["unit_key"]: norm(u["text"]) for u in units}),
            _unit_chapter=MappingProxyType({u["unit_key"]: (u["book_id"], u["chapter"])
                                            for u in units}),
        )

    def contains(self, clause: str, accept_pdf: bool = True) -> bool:
        """``clause`` occurs in the service text (or, with ``accept_pdf``, in text_pdf)."""
        if not clause:
            return False
        return clause in self._index.text or (accept_pdf and clause in self._index.text_pdf)

    def count(self, form: str) -> int:
        return self.raw.count(form)

    def locate(self, clause: str, within: Iterable[str] | None = None) -> str | None:
        """The slot of the unit where ``clause`` first starts (within the given slots, if any)."""
        if not clause:
            return None
        if within is not None:
            return self._locate_local(clause, tuple(within))
        for text in (self._index.text, self._index.text_pdf):
            at = text.find(clause)
            if at >= 0:
                return self._slot_at(at)
        return None

    def local(self, slot_keys: Iterable[str]) -> str:
        """Normalised text of the units behind ``slot_keys`` (omitted slots have none)."""
        return self._joined(self._units_of(slot_keys))[0]

    def _units_of(self, slot_keys: Iterable[str]) -> list[str]:
        seen: dict[str, None] = {}
        for key in slot_keys:
            if key not in self.slot_status:
                raise CorpusError(f"{key} is not a slot of {self.version}")
            unit = self.slot_unit[key]
            if unit is not None:
                seen.setdefault(unit, None)
        return list(seen)

    def _joined(self, units: Sequence[str]) -> tuple[str, list[int]]:
        """Unit texts joined as in the layer index: CHAPTER_SEP only between chapters."""
        parts, ends, pos, chapter = [], [], 0, None
        for unit in units:
            here = self._unit_chapter[unit]
            if chapter is not None and here != chapter:
                parts.append(CHAPTER_SEP)
                pos += len(CHAPTER_SEP)
            chapter = here
            parts.append(self._unit_norm[unit])
            pos += len(self._unit_norm[unit])
            ends.append(pos)
        return "".join(parts), ends

    def _locate_local(self, clause: str, within: tuple[str, ...]) -> str | None:
        units = self._units_of(within)
        joined, ends = self._joined(units)
        at = joined.find(clause)
        if at < 0:
            return None
        return self.unit_first_slot[units[bisect.bisect_right(ends, at)]]

    def _slot_at(self, offset: int) -> str:
        i = bisect.bisect_right(self._index.starts, offset) - 1
        return self.unit_first_slot[self._index.unit_keys[i]]


def _build_index(units: Sequence[Mapping]) -> _Index:
    parts: list[str] = []
    parts_pdf: list[str] = []
    starts: list[int] = []
    keys: list[str] = []
    pos = 0
    chapter = None
    for u in units:
        if chapter is not None and (u["book_id"], u["chapter"]) != chapter:
            parts.append(CHAPTER_SEP)
            parts_pdf.append(CHAPTER_SEP)
            pos += len(CHAPTER_SEP)
        chapter = (u["book_id"], u["chapter"])
        text, text_pdf = norm(u["text"]), norm(u["text_pdf"])
        if len(text) != len(text_pdf):
            raise CorpusError(f"{u['unit_key']}: text and text_pdf differ in length")
        starts.append(pos)
        keys.append(u["unit_key"])
        parts.append(text)
        parts_pdf.append(text_pdf)
        pos += len(text)
    return _Index("".join(parts), "".join(parts_pdf), tuple(starts), tuple(keys))


def _errata_words(errata: Sequence[Mapping]) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Word-level errata of verse units: (word as the PDF prints it, corrected word, units)."""
    found: dict[tuple[str, str], list[str]] = {}
    for e in sorted(errata, key=lambda r: r["errata_id"]):
        word = e.get("evidence", {}).get("word")
        if e["container_kind"] != "unit" or not word:
            continue
        if e["corrected_char"] not in word:
            raise CorpusError(f"{e['errata_id']}: word {word!r} lacks {e['corrected_char']!r}")
        pdf_word = word.replace(e["corrected_char"], e["pdf_char"])
        containers = found.setdefault((pdf_word, word), [])
        if e["container_id"] not in containers:
            containers.append(e["container_id"])
    return tuple((w, r, tuple(c)) for (w, r), c in found.items())


def _dotted_names(spans: Sequence[Mapping], raw: str) -> tuple[str, ...]:
    """Underlined names written with ``‧`` whose bare form the service text never writes."""
    names = {s["surface"] for s in spans if DOT in s["surface"]}
    names = {n for n in names if n.replace(DOT, "") not in raw}
    return tuple(sorted(names, key=lambda n: (-len(n), n)))

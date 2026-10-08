"""Legacy id map (design §3.3): the old build's ids to the new struct records.

Read from the old build's ``output/`` (a reference only, never an input of the new
records): ``pericopes.jsonl`` and ``chunks.jsonl``, in the store's copy
(``paths.LEGACY_OUTPUT``), which must be the bytes its SHA256SUMS lists. Old
verse records were ``{pericope id}:v:{label}`` (scripts/process_bible.py:374),
one per verse of each old pericope. Ranges compare as sets of integer verse numbers within a
chapter, as passages and chunks spell them (a verse cut by a mid-verse heading
counts in both halves):

- ``exact``: a new record covers the same verses;
- ``contained``: one new record covers them all (the first such);
- ``split``: no single record does; every overlapping record is listed.

Containment, not "only one record overlaps" (the design prototype e2_legacy_map):
the old converter kept only the part of a cut verse before its mid-verse heading
(G15), so an old range ending on a cut verse lies inside the passage before the
heading even though the next passage also counts that verse (2sa:19:1, 9–18).

Old pericopes map to passages; old chunks to the new chunks and the passages
that are not chunked. An old verse maps to the unit of the same label, or is
``retired`` when the PDF omits its slots (the ghost verses). Anything else stops
the build.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

from ragcommon import ids
from ragdata import reference
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct.view import TextView

FILES = ("pericopes.jsonl", "chunks.jsonl")
PROVENANCE = "external_legacy"
_RANGE = re.compile(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?")
Targets = Mapping[str, Sequence[tuple[str, frozenset[int]]]]   # chapter_key -> (id, verses)


class LegacyInputs(NamedTuple):
    pericopes: tuple[Mapping[str, Any], ...]
    chunks: tuple[Mapping[str, Any], ...]
    sha256: Mapping[str, str]


class OldRange(NamedTuple):
    book_id: str
    chapter: int
    first: int
    last: int

    def slot(self, verse: int) -> str:
        return ids.slot_key(self.book_id, self.chapter, verse)

    @property
    def verses(self) -> frozenset[int]:
        return frozenset(range(self.first, self.last + 1))


def _decode(name: str, data: bytes) -> tuple[dict[str, Any], ...]:
    rows = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StageError(f"{name}:{n}: {exc.msg}") from None
        if not isinstance(row, dict):
            raise StageError(f"{name}:{n}: not a JSON object")
        rows.append(row)
    return tuple(rows)


def load_legacy(directory: Path) -> LegacyInputs:
    paths = {name: Path(directory) / name for name in FILES}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise StageError(f"legacy directory {directory} lacks {', '.join(missing)}")
    data = {name: path.read_bytes() for name, path in paths.items()}
    shas = {name: hashlib.sha256(b).hexdigest() for name, b in data.items()}
    reference.check(Path(directory), shas)
    return LegacyInputs(_decode("pericopes.jsonl", data["pericopes.jsonl"]),
                        _decode("chunks.jsonl", data["chunks.jsonl"]), shas)


def _label(text: Any, where: str) -> tuple[int, int]:
    m = _RANGE.fullmatch(text) if isinstance(text, str) else None
    if m is None or (m.group(2) is not None and int(m.group(2)) <= int(m.group(1))):
        raise StageError(f"{where}: bad verse range {text!r}")
    return int(m.group(1)), int(m.group(2) or m.group(1))


def old_id(row: Mapping[str, Any]) -> str:
    value = row.get("id")
    if not isinstance(value, str) or not value:
        raise StageError(f"old row without an id: {str(row)[:80]}")
    return value


def old_range(row: Mapping[str, Any], label: Any | None = None) -> OldRange:
    """The chapter and verses an old row (or one of its verses, by ``label``) covered."""
    where = old_id(row)
    meta = row.get("metadata")
    try:
        book, chapter = meta["book_id"], meta["chapter_num"]
        ids.chapter_key(book, chapter)
        first, last = _label(meta["verse_range"] if label is None else label, where)
    except (KeyError, TypeError, ids.IdError) as exc:
        raise StageError(f"{where}: unreadable old row ({exc})") from None
    return OldRange(book, chapter, first, last)


def _verses(start_key: str, end_key: str) -> frozenset[int]:
    return frozenset(range(ids.parse(start_key).verse, ids.parse(end_key).verse + 1))


def targets(struct: Mapping[str, Sequence[Mapping[str, Any]]]) -> tuple[Targets, Targets]:
    """(passages, chunks or unchunked passages) by chapter, in canonical order."""
    chunks = defaultdict(list)
    for c in struct["chunks"]:
        chunks[c["passage_id"]].append((c["chunk_id"], _verses(c["start_key"], c["end_key"])))
    passages, retrieval = defaultdict(list), defaultdict(list)
    for p in struct["passages"]:
        own = (p["passage_id"], _verses(p["start_key"], p["end_key"]))
        passages[p["chapter_key"]].append(own)
        retrieval[p["chapter_key"]] += chunks.get(p["passage_id"], [own])
    return passages, retrieval


def relate(old_id: str, want: frozenset[int], candidates: Iterable[tuple[str, frozenset[int]]]
           ) -> tuple[str, list[str]]:
    overlapping = [(i, v) for i, v in candidates if v & want]
    if not overlapping:
        raise StageError(f"{old_id}: no new record covers its verses")
    for relation, fits in (("exact", lambda v: v == want), ("contained", lambda v: v >= want)):
        found = [i for i, v in overlapping if fits(v)]
        if found:
            return relation, found[:1]
    return "split", [i for i, _ in overlapping]


def _row(legacy_id: str, kind: str, relation: str, new_ids: Sequence[str], r: OldRange
         ) -> dict[str, Any]:
    return {"legacy_id": legacy_id, "kind": kind, "relation": relation, "new_ids": list(new_ids),
            "start_slot": r.slot(r.first), "end_slot": r.slot(r.last),
            "provenance_class": PROVENANCE}


def _ranged(rows: Iterable[Mapping[str, Any]], kind: str, by_chapter: Targets
            ) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        r = old_range(row)
        cands = by_chapter.get(ids.chapter_key(r.book_id, r.chapter), ())
        out.append(_row(old_id(row), kind, *relate(old_id(row), r.verses, cands), r))
    return out


def _verse_rows(pericopes: Iterable[Mapping[str, Any]], view: TextView) -> list[dict[str, Any]]:
    out = []
    for row in pericopes:
        for verse in row.get("verses") or ():
            num = verse.get("num") if isinstance(verse, dict) else None
            legacy_id = f"{old_id(row)}:v:{num}"
            r = old_range({**row, "id": legacy_id}, num)
            unit = ids.unit_key(r.book_id, r.chapter, r.first, r.last)
            if unit in view.unit:
                out.append(_row(legacy_id, "verse", "exact", [ids.verse_record_id(unit)], r))
            elif {r.slot(v) for v in r.verses} <= view.omitted:
                out.append(_row(legacy_id, "verse", "retired", [], r))
            else:
                raise StageError(f"{legacy_id}: {unit} is neither a unit nor an omitted slot")
    return out


def legacy_rows(legacy: LegacyInputs, struct: Mapping[str, Sequence[Mapping[str, Any]]],
                view: TextView) -> list[dict[str, Any]]:
    """Old pericopes, then old chunks, then old verse records, each in old file order."""
    passages, retrieval = targets(struct)
    return [*_ranged(legacy.pericopes, "pericope", passages),
            *_ranged(legacy.chunks, "chunk", retrieval),
            *_verse_rows(legacy.pericopes, view)]

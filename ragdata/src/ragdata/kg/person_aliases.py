"""The alias registry of the kinship identity (``config/registries/person_aliases.yaml``).

A rename joins two names' people within its scope; a footnote pair only makes a child's two
fathers agree. Each pair names the verse or footnote that says it; ``check_evidence`` holds the
pairs to the text layer, so the table cannot carry a pair the PDF does not write.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

from ragdata.kg.registries import RegistryError, registry_version

NAME = "person_aliases"
SCHEMA = "ragdata.person_aliases.v1"
SCOPES = ("O", "N")


@dataclass(frozen=True)
class Rename:
    old: str
    new: str
    scope: str
    evidence: str         # a unit key


@dataclass(frozen=True)
class FootnotePair:
    name: str
    other: str
    evidence: str         # a footnote id


def _table(pairs: Iterable[tuple[str, str]]) -> Mapping[str, frozenset[str]]:
    table: dict[str, set[str]] = defaultdict(set)
    for first, second in pairs:
        table[first].add(second)
        table[second].add(first)
    return MappingProxyType({k: frozenset(v) for k, v in table.items()})


@dataclass(frozen=True)
class Aliases:
    version: str
    renames: tuple[Rename, ...]
    footnotes: tuple[FootnotePair, ...]

    @property
    def same(self) -> Mapping[str, frozenset[str]]:
        """Each name's other names, over every pair."""
        return _table([*self.renamed_pairs, *((f.name, f.other) for f in self.footnotes)])

    @property
    def renamed_pairs(self) -> list[tuple[str, str]]:
        return [(r.old, r.new) for r in self.renames]

    @property
    def renamed(self) -> Mapping[str, frozenset[str]]:
        """Each name's other names, over the renames: a footnote pair holds of one person only (亞撒利雅 is
        亞哈謝 for one king), so no other person's name can stand in for it."""
        return _table(self.renamed_pairs)


def _rows(doc: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = doc.get(key)
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise RegistryError(f"{NAME}.{key}: expected a list of mappings")
    return rows


def _text(row: Mapping[str, Any], key: str, where: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{where}.{key}: expected a non-empty string")
    return value


def _rename(row: Mapping[str, Any], where: str) -> Rename:
    if row.get("scope") not in SCOPES:
        raise RegistryError(f"{where}: scope must be one of {SCOPES}, got {row.get('scope')!r}")
    return Rename(_text(row, "old", where), _text(row, "new", where), row["scope"],
                  _text(row, "evidence", where))


def _footnote(row: Mapping[str, Any], where: str) -> FootnotePair:
    return FootnotePair(_text(row, "name", where), _text(row, "other", where),
                        _text(row, "evidence", where))


def parse(doc: Mapping[str, Any], version: str) -> Aliases:
    if doc.get("schema") != SCHEMA:
        raise RegistryError(f"{NAME}: schema must be {SCHEMA}")
    return Aliases(
        version,
        tuple(_rename(r, f"{NAME}.rename[{i}]") for i, r in enumerate(_rows(doc, "rename"))),
        tuple(_footnote(r, f"{NAME}.footnote[{i}]") for i, r in enumerate(_rows(doc, "footnote"))))


def load(directory: Path) -> Aliases:
    path = Path(directory) / f"{NAME}.yaml"
    try:
        data = path.read_bytes()
        doc = yaml.safe_load(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RegistryError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, Mapping):
        raise RegistryError(f"{path}: expected a mapping")
    return parse(doc, registry_version(NAME, data))


def check_evidence(aliases: Aliases, verses: Mapping[str, str],
                   footnotes: Mapping[str, Mapping[str, str]]) -> list[str]:
    """Problems: a pair whose evidence is missing or does not write both names.

    ``verses``: text by unit key; ``footnotes``: ``{"text": ..., "unit_key": ...}`` by footnote id."""
    out = []
    for r in aliases.renames:
        text = verses.get(r.evidence)
        if text is None or r.old not in text or r.new not in text:
            out.append(f"rename {r.old}/{r.new}: {r.evidence} does not write both names")
    for f in aliases.footnotes:
        note = footnotes.get(f.evidence)
        joined = None if note is None else note["text"] + verses.get(note["unit_key"], "")
        if joined is None or f.name not in joined or f.other not in joined:
            out.append(f"footnote {f.name}/{f.other}: {f.evidence} does not write both names")
    return out

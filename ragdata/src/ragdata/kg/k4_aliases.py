"""The registries K4 reads besides kg0's: the query aliases and the exclusion contexts.

- ``query_aliases.yaml`` (design §5.2, §9.1 ``external_query``): spellings a user may type
  for a kg0 name or a divine surface, each with its source and note, and the question-side
  exclusion contexts (``question_exclusions``);
- ``name_normalization.yaml`` ``lexicon.exclude_contexts``: the contexts in which a name
  is not that name, which the router honours too.

Both are versioned ``{name}@{sha256(file)[:12]}`` (``kg.registries``). What the aliases
point at, and that their surfaces are new, is checked when K4 joins them to the lexicon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ragdata.kg.registries import NORMALIZATION, RegistryError, registry_version

NAME = "query_aliases"
SCHEMA = "ragdata.query_aliases.v1"
DOC_KEYS = frozenset({"schema", "aliases", "question_exclusions"})
ALIAS_KEYS = frozenset({"id", "surface", "target", "source", "note"})
EXCLUSION_KEYS = frozenset({"surface", "context", "why"})
ALIAS_ID = re.compile(r"qa\.\d{3}")
ASCII_LETTER = re.compile(r"[A-Za-z]")
QUESTION_SOURCE = "config/registries/query_aliases.yaml#question_exclusions"
LEXICON_SOURCE = "config/registries/name_normalization.yaml#lexicon.exclude_contexts"


@dataclass(frozen=True)
class QueryAlias:
    alias_id: str
    surface: str
    target: str
    source: str
    note: str


@dataclass(frozen=True)
class Exclusion:
    """A hit on ``surface`` inside ``context`` is no hit."""

    surface: str
    context: str
    why: str
    source: str


@dataclass(frozen=True)
class QueryAliases:
    version: str
    aliases: tuple[QueryAlias, ...]
    exclusions: tuple[Exclusion, ...]     # question_exclusions only


def _load(path: Path) -> tuple[Any, str]:
    try:
        data = path.read_bytes()
        return yaml.safe_load(data.decode("utf-8")), registry_version(path.stem, data)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RegistryError(f"{path}: unreadable: {exc}") from None


def _row(raw: Any, keys: frozenset[str], where: str) -> Mapping[str, str]:
    if not isinstance(raw, Mapping) or set(raw) != keys:
        found = sorted(raw) if isinstance(raw, Mapping) else type(raw).__name__
        raise RegistryError(f"{where}: keys {found} are not {sorted(keys)}")
    for key in keys:
        if not isinstance(raw[key], str) or not raw[key]:
            raise RegistryError(f"{where}.{key}: expected a non-empty string")
    return raw


def _alias(raw: Any, where: str) -> QueryAlias:
    row = _row(raw, ALIAS_KEYS, where)
    if not ALIAS_ID.fullmatch(row["id"]):
        raise RegistryError(f"{where}.id {row['id']!r} is not qa.NNN")
    for key in ("surface", "target"):
        if ASCII_LETTER.search(row[key]):
            raise RegistryError(f"{where}.{key} {row[key]!r} has latin letters")
    return QueryAlias(row["id"], row["surface"], row["target"], row["source"], row["note"])


def exclusion(raw: Any, source: str, where: str) -> Exclusion:
    row = _row(raw, EXCLUSION_KEYS, where)
    if row["surface"] not in row["context"]:
        raise RegistryError(f"{where}: {row['context']!r} does not contain {row['surface']!r}")
    return Exclusion(row["surface"], row["context"], row["why"], source)


def _list(doc: Mapping[str, Any], key: str) -> list:
    if not isinstance(doc[key], list):
        raise RegistryError(f"{NAME}.{key}: expected a list")
    return doc[key]


def load_query_aliases(directory: Path | str) -> QueryAliases:
    path = Path(directory) / f"{NAME}.yaml"
    doc, version = _load(path)
    if not isinstance(doc, Mapping) or set(doc) != DOC_KEYS or doc["schema"] != SCHEMA:
        raise RegistryError(f"{path}: keys must be {sorted(DOC_KEYS)}, schema {SCHEMA}")
    aliases = tuple(_alias(a, f"aliases[{i}]") for i, a in enumerate(_list(doc, "aliases")))
    for field in ("alias_id", "surface"):
        values = [getattr(a, field) for a in aliases]
        if len(set(values)) != len(values):
            raise RegistryError(f"{path}: an alias {field} is listed twice")
    rows = _list(doc, "question_exclusions")
    return QueryAliases(version, aliases, tuple(
        exclusion(r, QUESTION_SOURCE, f"question_exclusions[{i}]") for i, r in enumerate(rows)))


def lexicon_exclusions(directory: Path | str) -> tuple[Exclusion, ...]:
    """``name_normalization.yaml`` ``lexicon.exclude_contexts``, with their reasons (K0 keeps
    only the pairs)."""
    path = Path(directory) / f"{NORMALIZATION}.yaml"
    doc, _ = _load(path)
    lexicon = doc.get("lexicon") if isinstance(doc, Mapping) else None
    rows = lexicon.get("exclude_contexts", []) if isinstance(lexicon, Mapping) else None
    if not isinstance(rows, list):
        raise RegistryError(f"{path}: lexicon.exclude_contexts must be a list")
    return tuple(exclusion(r, LEXICON_SOURCE, f"exclude_contexts[{i}]")
                 for i, r in enumerate(rows))

"""The registries K0 reads besides the text layer (``config/registries/``, design §2.17, §5.2).

- ``name_normalization.yaml``: how underline spans become names (suffixes outside the
  line, generic nouns inside it, the four split names, ``‧`` names, truncation) and
  how the name lexicon is matched in the regions the PDF does not underline;
- ``divine_refs.yaml``: the divine names and titles the PDF never underlines, with the
  words in which a single 主 or 神 is not a title;
- ``underline_fixes.yaml``: underlines the PDF draws wrongly (``not_entity``) or
  misses (``curated_underline``), each decided by a named person.

Each registry is versioned ``{name}@{sha256(file)[:12]}``; the version is written into
every span it produced. A malformed registry raises RegistryError.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from ragcommon import books, ids
from ragdata.stages.errors import StageError

NORMALIZATION, DIVINE, FIXES = "name_normalization", "divine_refs", "underline_fixes"
SCHEMAS = {NORMALIZATION: "ragdata.name_normalization.v1", DIVINE: "ragdata.divine_refs.v1",
           FIXES: "ragdata.underline_fixes.v1"}
NORM_RULES = ("suffix_outside", "generic_inside", "merge", "interpunct", "truncation")
LEXICON_REGIONS = ("superscription", "heading", "footnote")


class RegistryError(StageError):
    """A KG registry is malformed or does not fit the text it applies to."""


def registry_version(name: str, data: bytes) -> str:
    return f"{name}@{hashlib.sha256(data).hexdigest()[:12]}"


def _mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise RegistryError(f"{where}: expected a mapping")
    return raw


def _list(raw: Any, where: str) -> list:
    if not isinstance(raw, list):
        raise RegistryError(f"{where}: expected a list")
    return raw


def _text(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise RegistryError(f"{where}: expected a non-empty string")
    return raw


def _read(directory: Path, name: str) -> tuple[Mapping[str, Any], str]:
    path = Path(directory) / f"{name}.yaml"
    try:
        data = path.read_bytes()
        doc = yaml.safe_load(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RegistryError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMAS[name]:
        raise RegistryError(f"{path}: schema must be {SCHEMAS[name]}")
    return doc, registry_version(name, data)


# ------------------------------------------------------------------ name_normalization


@dataclass(frozen=True)
class LexiconRules:
    rule_id: str
    regions: tuple[str, ...]
    min_len: int
    book_citation_id: str
    book_citation: re.Pattern[str]
    book_titles: tuple[str, ...]                 # a name that opens a book title cites it
    exclude_contexts: tuple[tuple[str, str], ...]  # (surface, context)


@dataclass(frozen=True)
class Normalization:
    version: str
    rule_ids: Mapping[str, str]                  # rule name -> rule id
    suffixes: tuple[str, ...]
    generic_nouns: tuple[str, ...]
    generic_exceptions: frozenset[str]
    generic_type: str
    merges: tuple[str, ...]
    interpunct: str
    truncations: tuple[tuple[str, str], ...]     # (truncated, full)
    lexicon: LexiconRules

    def generic(self, norm_key: str) -> bool:
        """The name ends with a generic noun drawn inside its line (not a transliteration)."""
        return len(norm_key) > 1 and norm_key[-1] in self.generic_nouns \
            and norm_key not in self.generic_exceptions


def _chars(raw: Any, where: str) -> tuple[str, ...]:
    chars = tuple(_text(c, where) for c in _list(raw, where))
    if any(len(c) != 1 for c in chars):
        raise RegistryError(f"{where}: every entry must be one character")
    return chars


def _pattern(raw: Any, where: str) -> re.Pattern[str]:
    try:
        return re.compile(_text(raw, where))
    except re.error as exc:
        raise RegistryError(f"{where}: bad pattern: {exc}") from None


def _lexicon(raw: Any) -> LexiconRules:
    lex = _mapping(raw, "lexicon")
    regions = tuple(_list(lex.get("regions"), "lexicon.regions"))
    if not regions or not set(regions) <= set(LEXICON_REGIONS):
        raise RegistryError(f"lexicon.regions must be some of {LEXICON_REGIONS}")
    min_len = lex.get("min_len")
    if not isinstance(min_len, int) or min_len < 1:
        raise RegistryError("lexicon.min_len must be a positive integer")
    _text(lex.get("min_len_why"), "lexicon.min_len_why")
    cite = _mapping(lex.get("book_citation"), "lexicon.book_citation")
    contexts = []
    for i, entry in enumerate(_list(lex.get("exclude_contexts", []), "lexicon.exclude_contexts")):
        entry = _mapping(entry, f"lexicon.exclude_contexts[{i}]")
        surface, context = (_text(entry.get(k), f"exclude_contexts[{i}].{k}")
                            for k in ("surface", "context"))
        _text(entry.get("why"), f"exclude_contexts[{i}].why")
        if surface not in context:
            raise RegistryError(f"exclude_contexts[{i}]: {context!r} does not contain {surface!r}")
        contexts.append((surface, context))
    if not isinstance(cite.get("book_titles"), bool):
        raise RegistryError("lexicon.book_citation.book_titles must be true or false")
    titles = tuple(sorted({n for b in books.all_books() for n in (b.name, *b.name_variants)})) \
        if cite["book_titles"] else ()
    return LexiconRules(_text(lex.get("id"), "lexicon.id"), regions, min_len,
                        _text(cite.get("id"), "book_citation.id"),
                        _pattern(cite.get("pattern"), "book_citation.pattern"), titles,
                        tuple(contexts))


def _rules(doc: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    rules = _mapping(doc.get("rules"), "rules")
    if set(rules) != set(NORM_RULES):
        raise RegistryError(f"rules must be exactly {list(NORM_RULES)}, got {sorted(rules)}")
    for name, rule in rules.items():
        _text(_mapping(rule, f"rules.{name}").get("id"), f"rules.{name}.id")
        _text(rule.get("what"), f"rules.{name}.what")
    return rules


def load_normalization(directory: Path) -> Normalization:
    doc, version = _read(directory, NORMALIZATION)
    rules = _rules(doc)
    generic, trunc = rules["generic_inside"], rules["truncation"]
    examples = [_mapping(x, "truncation.examples")
                for x in _list(trunc.get("examples"), "truncation.examples")]
    truncations = tuple((_text(e.get("truncated"), "truncation"),
                         _text(e.get("full"), "truncation")) for e in examples)
    return Normalization(
        version=version, rule_ids=MappingProxyType({n: r["id"] for n, r in rules.items()}),
        suffixes=_chars(rules["suffix_outside"].get("suffixes"), "suffix_outside.suffixes"),
        generic_nouns=_chars(generic.get("nouns"), "generic_inside.nouns"),
        generic_exceptions=frozenset(_text(x, "generic_inside.exceptions")
                                     for x in _list(generic.get("exceptions"), "exceptions")),
        generic_type=_text(generic.get("type_candidate"), "generic_inside.type_candidate"),
        merges=tuple(_text(x, "merge.groups") for x in _list(rules["merge"].get("groups"),
                                                             "merge.groups")),
        interpunct=_chars([rules["interpunct"].get("char")], "interpunct.char")[0],
        truncations=truncations, lexicon=_lexicon(doc.get("lexicon")),
    )


# ------------------------------------------------------------------ divine_refs


@dataclass(frozen=True)
class DivineRefs:
    version: str
    region: str
    patterns: tuple[tuple[str, str], ...]          # (rule id, surface)
    exclusions: Mapping[str, tuple[str, ...]]      # single-character pattern -> words


def _exclusions(raw: Any, singles: set[str]) -> Mapping[str, tuple[str, ...]]:
    found = {}
    for char, words in _mapping(raw, "exclusions").items():
        if char not in singles:
            raise RegistryError(f"exclusions.{char}: not a single-character pattern")
        entries = [_mapping(w, f"exclusions.{char}") for w in _list(words, f"exclusions.{char}")]
        for entry in entries:
            _text(entry.get("why"), f"exclusions.{char}.{entry.get('word')}.why")
            if char not in _text(entry.get("word"), f"exclusions.{char}.word"):
                raise RegistryError(f"exclusions.{char}: {entry['word']!r} does not contain {char}")
        found[char] = tuple(e["word"] for e in entries)
    return MappingProxyType(found)


def load_divine(directory: Path) -> DivineRefs:
    doc, version = _read(directory, DIVINE)
    patterns = []
    for i, raw in enumerate(_list(doc.get("span_patterns"), "span_patterns")):
        raw = _mapping(raw, f"span_patterns[{i}]")
        _text(raw.get("what"), f"span_patterns[{i}].what")
        patterns.append((_text(raw.get("id"), f"span_patterns[{i}].id"),
                         _text(raw.get("surface"), f"span_patterns[{i}].surface")))
    for column in (0, 1):
        values = [p[column] for p in patterns]
        if len(set(values)) != len(values):
            raise RegistryError("span_patterns: an id or surface is listed twice")
    singles = {surface for _, surface in patterns if len(surface) == 1}
    if doc.get("region") != "body":
        raise RegistryError("divine_refs applies to the body region only")
    return DivineRefs(version, "body", tuple(patterns),
                      _exclusions(doc.get("exclusions", {}), singles))


# ------------------------------------------------------------------ underline_fixes


@dataclass(frozen=True)
class NotEntity:
    fix_id: str
    span_id: str
    surface: str
    decided_by: str


@dataclass(frozen=True)
class CuratedUnderline:
    fix_id: str
    container_id: str
    start: int
    surface: str
    decided_by: str


@dataclass(frozen=True)
class UnderlineFixes:
    version: str
    not_entity: Mapping[str, NotEntity]           # span id -> fix
    curated: tuple[CuratedUnderline, ...]


def _decided(entry: Mapping[str, Any], where: str) -> tuple[str, str, str]:
    _text(entry.get("why"), f"{where}.why")
    return (_text(entry.get("id"), f"{where}.id"), _text(entry.get("surface"), f"{where}.surface"),
            _text(entry.get("decided_by"), f"{where}.decided_by"))


def _not_entity(raw: Any) -> Mapping[str, NotEntity]:
    found: dict[str, NotEntity] = {}
    for i, entry in enumerate(_list(raw, "not_entity")):
        entry = _mapping(entry, f"not_entity[{i}]")
        fix_id, surface, decided = _decided(entry, f"not_entity[{i}]")
        span_id = entry.get("span_id")
        if not ids.is_valid(span_id, "name_span"):
            raise RegistryError(f"not_entity[{i}]: {span_id!r} is not a name span id")
        found[span_id] = NotEntity(fix_id, span_id, surface, decided)
    return MappingProxyType(found)


def _curated(raw: Any) -> tuple[CuratedUnderline, ...]:
    found = []
    for i, entry in enumerate(_list(raw, "curated_underline")):
        entry = _mapping(entry, f"curated_underline[{i}]")
        fix_id, surface, decided = _decided(entry, f"curated_underline[{i}]")
        start = entry.get("start")
        if not isinstance(start, int) or start < 0:
            raise RegistryError(f"curated_underline[{i}].start must be a non-negative integer")
        found.append(CuratedUnderline(fix_id, _text(entry.get("container_id"), "container_id"),
                                      start, surface, decided))
    return tuple(found)


def load_fixes(directory: Path) -> UnderlineFixes:
    doc, version = _read(directory, FIXES)
    return UnderlineFixes(version, _not_entity(doc.get("not_entity", [])),
                          _curated(doc.get("curated_underline", [])))


@dataclass(frozen=True)
class K0Registries:
    normalization: Normalization
    divine: DivineRefs
    fixes: UnderlineFixes

    def versions(self) -> dict[str, str]:
        return {NORMALIZATION: self.normalization.version, DIVINE: self.divine.version,
                FIXES: self.fixes.version}


def load_k0(directory: Path | str) -> K0Registries:
    directory = Path(directory)
    return K0Registries(load_normalization(directory), load_divine(directory),
                        load_fixes(directory))

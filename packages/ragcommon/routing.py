"""The routing lexicon (v2, R2): the words the backend router matches in a question.

The build compiles it (K4) from the PDF layers: kg0 names and their spellings
without ‧, the divine_refs surfaces, the query aliases (external_query), the event
registry's triggers, and the book names. Every term carries all of its candidate
targets, the route types the router counts (K4 resolves them, so the backend has
no type policy of its own), a routable flag with the rule that cleared it, and its
provenance (design §5.3, §9.1). The R2 image accepts no other schema.

``RoutingLexicon.match`` is the one matcher, shared by the K4 gates and the
backend: the books' full names are masked first; every occurrence of a routable term
or another book form is a candidate unless the exclusion table vetoes it in its
context; the candidates are taken longest first (then leftmost) where they overlap
none already taken; and every hit returns all targets of its term (the matcher never
chooses among them). ``render_lexicon`` is the one canonical byte form.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, NoReturn, Sequence

from ragcommon import books, ids

SCHEMA = "ragdata.routing_lexicon.v2"
VARIANT = "R2"
MASK = "□"
MIN_LEN = 2  # rt.min_len: a one-character term is never routable
CATEGORY_KINDS = {"names": ("name", "dotless"), "divine": ("divine",), "aliases": ("alias",),
                  "events": ("event",), "books": ("book",)}
CATEGORIES = tuple(CATEGORY_KINDS)
CATEGORY_OF_KIND = {kind: cat for cat, kinds in CATEGORY_KINDS.items() for kind in kinds}
DOC_KEYS = frozenset({"schema", "variant", "header", *CATEGORIES, "exclusions"})
TERM_KEYS = frozenset({
    "surface", "kind", "targets", "routable", "unroutable_rule", "provenance_class", "source",
    "evidence_span_id", "rule_id", "norm_rule_ids", "at", "decided_by", "note", "alias_id",
    "book_id", "full_name"})
TARGET_KEYS = frozenset({"ref", "label", "type_candidates", "route_types"})
EXCLUSION_KEYS = frozenset({"surface", "context", "why", "source"})
ROUTE_TYPES = frozenset({"Person", "Place"})
LEGACY_CLASS = "external_legacy"

QUERY_ALIASES_SCHEMA = "ragdata.contract.query_aliases.v1"
QUERY_ALIASES_KEYS = frozenset({"schema", "kg0", "registry", "aliases"})
QUERY_ALIAS_ROW_KEYS = frozenset({"alias_id", "surface", "target", "target_ref",
                                  "provenance_class", "source", "note"})


class RoutingLexiconError(ValueError):
    """A routing lexicon (or the query-alias contract) does not follow the contract."""


@dataclass(frozen=True)
class Target:
    ref: str                        # nm:… (kg0 name), dr.span.NNN (divine) or ev id (event)
    label: str
    route_types: tuple[str, ...]    # sorted subset of Person, Place


@dataclass(frozen=True)
class Term:
    surface: str
    kind: str
    targets: tuple[Target, ...]
    routable: bool


@dataclass(frozen=True)
class Hit:
    surface: str
    start: int
    end: int
    kind: str
    targets: tuple[Target, ...]


@dataclass(frozen=True)
class BookName:
    name: str        # the surface
    book_id: str
    full_name: str


@dataclass(frozen=True)
class Exclusion:
    surface: str
    context: str


@dataclass(frozen=True)
class QueryAlias:
    alias_id: str
    surface: str
    target: str
    target_ref: str


class RoutingLexicon:
    """The parsed lexicon: terms (no books), books in contract order, the exclusion table.

    A book's full name is masked wherever it occurs. Its other forms (撒上, 約三, 尼西米記)
    are short and common inside names and triggers, so they are words of the scan like
    the terms: a longer term over one wins (亞伯拉罕之約三, 以斯帖前去), an equally long
    one wins where it starts first (以撒上山), and a form names a book only where the
    scan reads it.

    Overlaps go to the longer word wherever it stands, not to the one that starts
    first: a question has no word boundaries, and the character before a name is often
    a word of its own (他, 以, 比) that starts a shorter name across the boundary
    (他拉撒路 is 他 + 拉撒路, not 他拉 + 撒路). The longer reading is the one more
    characters agree on.
    """

    def __init__(self, terms: Sequence[Term], book_names: Sequence[BookName],
                 exclusions: Sequence[Exclusion] = ()) -> None:
        self.terms = tuple(terms)
        self.books = tuple(book_names)
        self.exclusions = tuple(exclusions)
        forms = [Term(b.name, "book", (), True) for b in self.books
                 if b.name != b.full_name and len(b.name) >= MIN_LEN]
        self._by_first = _first_char_index([*(t for t in self.terms if t.routable), *forms])
        self._contexts = _contexts(self.exclusions)
        self.full_names = tuple(sorted({b.name for b in self.books if b.name == b.full_name},
                                       key=lambda s: (-len(s), s)))

    def mask_books(self, text: str) -> str:
        """Every book's full name blanked to MASK (longest first); offsets are preserved."""
        for name in self.full_names:
            text = text.replace(name, MASK * len(name))
        return text

    def match(self, text: str) -> list[Hit]:
        """Non-overlapping hits of the routable terms (longest first), full names masked."""
        return [hit for hit in self._scan(text) if hit.kind != "book"]

    def match_books(self, text: str) -> list[str]:
        """Full names of the books named in ``text`` (a full name anywhere, another form where
        the scan reads it): books in list order, each book once."""
        read = {hit.surface for hit in self._scan(text) if hit.kind == "book"}
        seen: set[str] = set()
        found: list[str] = []
        for book in self.books:
            named = book.name in text if book.name == book.full_name else book.name in read
            if named and book.book_id not in seen:
                seen.add(book.book_id)
                found.append(book.full_name)
        return found

    def count_books(self, text: str) -> int:
        return len(self.match_books(text))

    def _scan(self, text: str) -> list[Hit]:
        """Hits of the terms and the book forms in text order: every candidate no exclusion
        vetoes, taken longest first (then leftmost) where it overlaps no hit taken before."""
        masked = self.mask_books(text)
        candidates = [Hit(t.surface, i, i + len(t.surface), t.kind, t.targets)
                      for i, char in enumerate(masked) for t in self._by_first.get(char, ())
                      if masked.startswith(t.surface, i)
                      and not self._excluded(masked, i, t.surface)]
        hits: list[Hit] = []
        taken: set[int] = set()
        for hit in sorted(candidates, key=lambda h: (h.start - h.end, h.start)):
            span = range(hit.start, hit.end)
            if taken.isdisjoint(span):
                taken.update(span)
                hits.append(hit)
        return sorted(hits, key=lambda h: h.start)

    def _excluded(self, text: str, i: int, surface: str) -> bool:
        for context in self._contexts.get(surface, ()):
            k = context.find(surface)
            if i - k >= 0 and text[i - k:i - k + len(context)] == context:
                return True
        return False


def _first_char_index(terms: Iterable[Term]) -> dict[str, tuple[Term, ...]]:
    index: dict[str, list[Term]] = {}
    for term in sorted(terms, key=lambda t: (-len(t.surface), t.surface)):
        index.setdefault(term.surface[0], []).append(term)
    return {first: tuple(found) for first, found in index.items()}


def _contexts(exclusions: Iterable[Exclusion]) -> dict[str, tuple[str, ...]]:
    found: dict[str, list[str]] = {}
    for row in exclusions:
        found.setdefault(row.surface, []).append(row.context)
    return {surface: tuple(contexts) for surface, contexts in found.items()}


# ---------------------------------------------------------------- parsing


def _fail(message: str) -> NoReturn:
    raise RoutingLexiconError(message)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _keys(raw: Any, expected: frozenset[str], where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        _fail(f"{where}: expected an object")
    if set(raw) != expected:
        _fail(f"{where}: keys {sorted(raw)} are not {sorted(expected)}")
    return raw


def _list(value: Any, where: str) -> list:
    if not isinstance(value, list):
        _fail(f"{where}: expected a list")
    return value


def legacy_mark(node: Any, where: str = "$") -> str | None:
    """Where ``node`` carries legacy provenance (external_legacy or a retire_by key), or None."""
    if isinstance(node, Mapping):
        if "retire_by" in node:
            return f"{where}.retire_by"
        if node.get("provenance_class") == LEGACY_CLASS:
            return f"{where}.provenance_class"
        found = (legacy_mark(v, f"{where}.{k}") for k, v in node.items())
    elif isinstance(node, list):
        found = (legacy_mark(v, f"{where}[{i}]") for i, v in enumerate(node))
    else:
        return None
    return next((mark for mark in found if mark), None)


def _target(raw: Any, kind: str, where: str) -> Target:
    raw = _keys(raw, TARGET_KEYS, where)
    _list(raw["type_candidates"], f"{where}.type_candidates")
    types = tuple(_list(raw["route_types"], f"{where}.route_types"))
    if not set(types) <= ROUTE_TYPES:
        _fail(f"{where}.route_types: {list(types)} are not among {sorted(ROUTE_TYPES)}")
    ref = _text(raw["ref"], f"{where}.ref")
    if kind == "event" and not ids.is_valid(ref, "event"):
        _fail(f"{where}.ref: {ref!r} is not an event id")
    return Target(ref, _text(raw["label"], f"{where}.label"), types)


def _term(raw: Any, category: str, where: str) -> Term:
    raw = _keys(raw, TERM_KEYS, where)
    kind, surface = raw["kind"], _text(raw["surface"], f"{where}.surface")
    if kind not in CATEGORY_KINDS[category]:
        _fail(f"{where}.kind: {kind!r} does not belong in {category}")
    if not isinstance(raw["routable"], bool):
        _fail(f"{where}.routable: expected true or false")
    if raw["routable"] and len(surface) < MIN_LEN:
        _fail(f"{where}: {surface!r} is shorter than {MIN_LEN} but routable")
    _text(raw["provenance_class"], f"{where}.provenance_class")
    _text(raw["source"], f"{where}.source")
    targets = tuple(_target(t, kind, f"{where}.targets[{j}]")
                    for j, t in enumerate(_list(raw["targets"], f"{where}.targets")))
    return Term(surface, kind, targets, raw["routable"])


def _book(raw: Mapping[str, Any], where: str) -> BookName:
    if not books.is_book_id(raw["book_id"]):
        _fail(f"{where}.book_id: unknown book {raw['book_id']!r}")
    return BookName(raw["surface"], raw["book_id"], _text(raw["full_name"], f"{where}.full_name"))


def _exclusion(raw: Any, where: str) -> Exclusion:
    raw = _keys(raw, EXCLUSION_KEYS, where)
    surface = _text(raw["surface"], f"{where}.surface")
    context = _text(raw["context"], f"{where}.context")
    if surface not in context:
        _fail(f"{where}: context {context!r} does not contain {surface!r}")
    return Exclusion(surface, context)


def _check_document(doc: Any) -> None:
    if not isinstance(doc, Mapping):
        _fail(f"a lexicon must be an object, got {type(doc).__name__}")
    if doc.get("schema") != SCHEMA:
        _fail(f"schema must be {SCHEMA}, got {doc.get('schema')!r}")
    if doc.get("variant") != VARIANT:
        _fail(f"variant must be {VARIANT}, got {doc.get('variant')!r}")
    if set(doc) != DOC_KEYS:
        _fail(f"lexicon keys {sorted(doc)} are not {sorted(DOC_KEYS)}")
    mark = legacy_mark(doc)
    if mark:
        _fail(f"legacy provenance at {mark}")


def parse_lexicon(doc: Any) -> RoutingLexicon:
    """Validate a v2 lexicon document and build its matcher; raise RoutingLexiconError."""
    _check_document(doc)
    terms, book_names, seen = [], [], set()
    for category in CATEGORIES:
        for i, raw in enumerate(_list(doc[category], category)):
            where = f"{category}[{i}]"
            term = _term(raw, category, where)
            if term.surface in seen:
                _fail(f"{where}: duplicate surface {term.surface!r}")
            seen.add(term.surface)
            if category == "books":
                book_names.append(_book(raw, where))
            else:
                terms.append(term)
    exclusions = [_exclusion(raw, f"exclusions[{i}]")
                  for i, raw in enumerate(_list(doc["exclusions"], "exclusions"))]
    return RoutingLexicon(terms, book_names, exclusions)


def load_lexicon(path: Path | str) -> RoutingLexicon:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingLexiconError(f"{path}: unreadable: {exc}") from None
    return parse_lexicon(doc)


def render_lexicon(doc: Mapping[str, Any]) -> bytes:
    """The canonical bytes of a lexicon document (sorted keys, one-space indent, UTF-8)."""
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def _query_alias(raw: Any, where: str) -> QueryAlias:
    raw = _keys(raw, QUERY_ALIAS_ROW_KEYS, where)
    for key in sorted(QUERY_ALIAS_ROW_KEYS):
        _text(raw[key], f"{where}.{key}")
    return QueryAlias(raw["alias_id"], raw["surface"], raw["target"], raw["target_ref"])


def parse_query_aliases(doc: Any) -> tuple[QueryAlias, ...]:
    """Validate the query-alias contract (query_aliases.json); raise RoutingLexiconError.

    The backend does not match with it (the alias terms are already in the
    lexicon); its presence and shape are what tell an R2 build from an R1 build.
    """
    if not isinstance(doc, Mapping) or doc.get("schema") != QUERY_ALIASES_SCHEMA:
        _fail(f"query aliases schema must be {QUERY_ALIASES_SCHEMA}")
    _keys(doc, QUERY_ALIASES_KEYS, "query aliases")
    mark = legacy_mark(doc)
    if mark:
        _fail(f"legacy provenance at {mark}")
    return tuple(_query_alias(raw, f"aliases[{i}]")
                 for i, raw in enumerate(_list(doc["aliases"], "aliases")))

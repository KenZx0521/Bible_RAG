"""The routing lexicon: the words the backend router matches in a question.

R1 serves the legacy vocabulary frozen from ``backend/utils/entity_dicts.py``
(``scripts/entity_extraction/entity_dict.py`` persons and places, the
``EVENT_KEYWORDS`` set, and the book names of ``backend/utils/verse_parser.py``),
design D-12(a). The file is ``routing_lexicon.legacy.json``; the matchers below
reproduce the ``match_*_in_text`` functions of entity_dicts exactly, so the
backend can switch to this file without changing a single route (G-ROUTE).

Every word carries its provenance (design §9.1). ``render_lexicon`` is the one
canonical byte form, shared by the freezer and the build, so a layer can prove
it reproduces the frozen file bit for bit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragcommon import books

SCHEMA = "ragdata.routing_lexicon.v1"
CATEGORIES = ("persons", "places", "events", "books")
PROVENANCE_KEYS = ("provenance_class", "source", "note", "retire_by")
TERM_KEYS = {"persons": ("canonical", "aliases"), "places": ("canonical", "aliases"),
             "events": ("term",), "books": ("name", "book_id", "full_name")}
DOC_KEYS = frozenset({"schema", "variant", "header", *CATEGORIES})
MIN_BOOK_NAME = 2  # entity_dicts skips one-character book names (利, 伯, 拉, …)


class RoutingLexiconError(ValueError):
    """A routing lexicon does not follow the contract."""


@dataclass(frozen=True)
class NamedTerm:
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class BookName:
    name: str
    book_id: str
    full_name: str


@dataclass(frozen=True)
class RoutingLexicon:
    persons: tuple[NamedTerm, ...]
    places: tuple[NamedTerm, ...]
    events: tuple[str, ...]
    books: tuple[BookName, ...]

    def match_persons(self, text: str) -> list[str]:
        return _match_named(self.persons, text)

    def match_places(self, text: str) -> list[str]:
        return _match_named(self.places, text)

    def match_events(self, text: str) -> list[str]:
        """Keywords in ``text``, longest first, ties by code point (entity_dicts order)."""
        return [kw for kw in sorted(self.events, key=lambda k: (-len(k), k)) if kw in text]

    def match_books(self, text: str) -> list[str]:
        """Full names of the books named in ``text``, each book once, longest name first."""
        seen: set[str] = set()
        found: list[str] = []
        for book in sorted(self.books, key=lambda b: len(b.name), reverse=True):
            if len(book.name) >= MIN_BOOK_NAME and book.name in text \
                    and book.book_id not in seen:
                seen.add(book.book_id)
                found.append(book.full_name)
        return found

    def count_books(self, text: str) -> int:
        return len(self.match_books(text))


def _match_named(terms: Sequence[NamedTerm], text: str) -> list[str]:
    """Canonical names with an alias in ``text``; longest alias first, ties in file order
    (``sorted`` is stable, as in entity_dicts)."""
    ordered = sorted(terms, key=lambda t: max(len(a) for a in t.aliases), reverse=True)
    return [t.canonical for t in ordered if any(a in text for a in t.aliases)]


# ---------------------------------------------------------------- parsing


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise RoutingLexiconError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _entry(raw: Any, category: str, i: int) -> Mapping[str, Any]:
    where = f"{category}[{i}]"
    if not isinstance(raw, Mapping):
        raise RoutingLexiconError(f"{where}: expected an object")
    expected = {*TERM_KEYS[category], *PROVENANCE_KEYS}
    if set(raw) != expected:
        raise RoutingLexiconError(f"{where}: keys {sorted(raw)} are not {sorted(expected)}")
    for key in PROVENANCE_KEYS:
        _text(raw[key], f"{where}.{key}")
    return raw


def _named(raw: Mapping[str, Any], where: str) -> NamedTerm:
    aliases = raw["aliases"]
    if not isinstance(aliases, list) or not aliases:
        raise RoutingLexiconError(f"{where}.aliases: expected a non-empty list")
    return NamedTerm(_text(raw["canonical"], f"{where}.canonical"),
                     tuple(_text(a, f"{where}.aliases") for a in aliases))


def _book(raw: Mapping[str, Any], where: str) -> BookName:
    if not books.is_book_id(raw["book_id"]):
        raise RoutingLexiconError(f"{where}.book_id: unknown book {raw['book_id']!r}")
    return BookName(_text(raw["name"], f"{where}.name"), raw["book_id"],
                    _text(raw["full_name"], f"{where}.full_name"))


def _entries(doc: Mapping[str, Any], category: str) -> list[Mapping[str, Any]]:
    rows = doc[category]
    if not isinstance(rows, list):
        raise RoutingLexiconError(f"{category}: expected a list")
    return [_entry(raw, category, i) for i, raw in enumerate(rows)]


def parse_lexicon(doc: Any) -> RoutingLexicon:
    """Validate a lexicon document and build its matchers; raise RoutingLexiconError."""
    if not isinstance(doc, Mapping) or set(doc) != DOC_KEYS:
        keys = sorted(doc) if isinstance(doc, Mapping) else type(doc).__name__
        raise RoutingLexiconError(f"lexicon keys {keys} are not {sorted(DOC_KEYS)}")
    if doc["schema"] != SCHEMA:
        raise RoutingLexiconError(f"schema must be {SCHEMA}, got {doc['schema']!r}")
    rows = {category: _entries(doc, category) for category in CATEGORIES}
    return RoutingLexicon(
        persons=tuple(_named(r, f"persons[{i}]") for i, r in enumerate(rows["persons"])),
        places=tuple(_named(r, f"places[{i}]") for i, r in enumerate(rows["places"])),
        events=tuple(_text(r["term"], f"events[{i}].term") for i, r in enumerate(rows["events"])),
        books=tuple(_book(r, f"books[{i}]") for i, r in enumerate(rows["books"])),
    )


def load_lexicon(path: Path | str) -> RoutingLexicon:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingLexiconError(f"{path}: unreadable: {exc}") from None
    return parse_lexicon(doc)


def render_lexicon(doc: Mapping[str, Any]) -> bytes:
    """The canonical bytes of a lexicon document (sorted keys, one-space indent, UTF-8)."""
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")

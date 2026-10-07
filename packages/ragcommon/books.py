"""The 66-book table: ids, PDF names, abbreviations and metadata.

The single source is ``data/books.json``; nothing else in the repo should keep
its own copy of book names or abbreviations.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

DATA_PATH = Path(__file__).resolve().parent / "data" / "books.json"

BOOK_COUNT = 66
OT_COUNT = 39
CATEGORIES = frozenset({
    "pentateuch", "history", "wisdom", "major_prophets", "minor_prophets",
    "gospels", "acts", "pauline", "general", "apocalyptic",
})
NAME_FIELDS = (
    ("name", "name"),
    ("name_variants", "name_variant"),
    ("pdf_abbreviations", "pdf_abbreviation"),
    ("colloquial_abbreviations", "colloquial_abbreviation"),
)
_REQUIRED = ("book_id", "ord", "name", "file_name", "name_en", "testament", "category")
_BOOK_ID_RE = re.compile(r"[0-9a-z]{3}")
_HAN_RE = re.compile(r"[㐀-鿿]+")


class BookDataError(ValueError):
    """books.json violates the book-table contract."""


class UnknownBookError(KeyError):
    """A book id that is not one of the 66 codes."""


@dataclass(frozen=True)
class Book:
    book_id: str
    ord: int
    name: str
    file_name: str
    name_en: str
    testament: str
    category: str
    pdf_abbreviations: tuple[str, ...]
    colloquial_abbreviations: tuple[str, ...]
    name_variants: tuple[str, ...]

    @property
    def abbreviations(self) -> tuple[str, ...]:
        return self.pdf_abbreviations + self.colloquial_abbreviations


@dataclass(frozen=True)
class BookName:
    """One written form of a book name and what kind of form it is."""

    text: str
    book_id: str
    kind: str

    @property
    def is_abbreviation(self) -> bool:
        return self.kind.endswith("abbreviation")


@dataclass(frozen=True)
class BookTable:
    books: tuple[Book, ...]
    names: Mapping[str, BookName]
    ambiguous: Mapping[str, tuple[str, ...]]

    def ids(self) -> tuple[str, ...]:
        return tuple(b.book_id for b in self.books)

    def get(self, book_id: str) -> Book:
        for book in self.books:
            if book.book_id == book_id:
                return book
        raise UnknownBookError(book_id)

    def lookup(self, text: str) -> BookName | None:
        return self.names.get(text)

    def names_longest_first(self) -> tuple[BookName, ...]:
        return tuple(sorted(self.names.values(), key=lambda n: (-len(n.text), n.text)))


def _require_name(text: Any, where: str) -> str:
    if not isinstance(text, str) or not _HAN_RE.fullmatch(text):
        raise BookDataError(f"{where}: name must be Han characters only, got {text!r}")
    return text


def _book_from_record(rec: Mapping[str, Any], index: int) -> Book:
    for key in _REQUIRED:
        if key not in rec or rec[key] in (None, ""):
            raise BookDataError(f"books[{index}]: missing {key}")
    book_id = rec["book_id"]
    if not isinstance(book_id, str) or not _BOOK_ID_RE.fullmatch(book_id):
        raise BookDataError(f"books[{index}]: bad book_id {book_id!r}")
    if rec["ord"] != index + 1:
        raise BookDataError(f"{book_id}: ord {rec['ord']} != {index + 1}")
    expected = "OT" if index < OT_COUNT else "NT"
    if rec["testament"] != expected:
        raise BookDataError(f"{book_id}: testament {rec['testament']!r} != {expected}")
    if rec["category"] not in CATEGORIES:
        raise BookDataError(f"{book_id}: unknown category {rec['category']!r}")
    lists = {field: tuple(_require_name(t, book_id) for t in rec.get(field, []))
             for field, _ in NAME_FIELDS[1:]}
    return Book(
        book_id=book_id, ord=rec["ord"], name=_require_name(rec["name"], book_id),
        file_name=_require_name(rec["file_name"], book_id), name_en=rec["name_en"],
        testament=rec["testament"], category=rec["category"], **lists,
    )


def _name_index(book_list: tuple[Book, ...]) -> dict[str, BookName]:
    index: dict[str, BookName] = {}
    for book in book_list:
        for field, kind in NAME_FIELDS:
            value = getattr(book, field)
            for text in (value,) if isinstance(value, str) else value:
                if text in index:
                    raise BookDataError(f"duplicate name {text!r}: {index[text].book_id}, {book.book_id}")
                index[text] = BookName(text=text, book_id=book.book_id, kind=kind)
    return index


def _ambiguous(raw: Mapping[str, Any], names: Mapping[str, BookName],
               ids: frozenset[str]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for text, candidates in raw.items():
        _require_name(text, "ambiguous_names")
        if text in names:
            raise BookDataError(f"ambiguous name {text!r} is also a book name")
        if len(candidates) < 2 or not set(candidates) <= ids:
            raise BookDataError(f"ambiguous name {text!r}: bad candidates {candidates!r}")
        result[text] = tuple(candidates)
    return result


def load_books(path: Path | str = DATA_PATH) -> BookTable:
    """Load and validate a books.json file; raise BookDataError on any violation."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    records = doc.get("books", [])
    if len(records) != BOOK_COUNT:
        raise BookDataError(f"expected {BOOK_COUNT} books, got {len(records)}")
    book_list = tuple(_book_from_record(rec, i) for i, rec in enumerate(records))
    ids = [b.book_id for b in book_list]
    if len(set(ids)) != len(ids):
        raise BookDataError("duplicate book_id")
    names = _name_index(book_list)
    ambiguous = _ambiguous(doc.get("ambiguous_names", {}), names, frozenset(ids))
    return BookTable(
        books=book_list,
        names=MappingProxyType(names),
        ambiguous=MappingProxyType(ambiguous),
    )


@lru_cache(maxsize=1)
def default_books() -> BookTable:
    return load_books(DATA_PATH)


def all_books() -> tuple[Book, ...]:
    return default_books().books


def book_ids() -> tuple[str, ...]:
    return default_books().ids()


def get_book(book_id: str) -> Book:
    return default_books().get(book_id)


def is_book_id(text: str) -> bool:
    return text in book_ids()


def lookup_name(text: str) -> BookName | None:
    return default_books().lookup(text)

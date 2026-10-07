"""G-TEXT: the wording of every text-layer record is clean and its errata hold up (design §8).

- every text field is NFC and has no control, format, private-use, surrogate,
  unassigned or replacement character;
- ASCII appears only in the record types (and characters) the normalization
  registry allows, e.g. the 「......」 ellipsis in verses and footnote verse numbers;
- ``text`` equals ``text_pdf`` except at the errata of its container, and at
  each erratum it holds the corrected character (D-03(b));
- an applied correction occurs nowhere in the PDF text, and its misglyph
  occurs nowhere uncorrected (G11: fixed everywhere or nowhere);
- book names are the PDF title lines (books.json, checked against the PDFs by G-SRC).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Any, Iterator, Mapping

from ragcommon import books
from ragdata.contract import primary_key
from ragdata.contract.text import WORDING
from ragdata.gates.base import GateResult, Snapshot, capped

NAME = "G-TEXT"
FIELDS: Mapping[str, tuple[str, ...]] = {
    "books": ("name",), **{name: (pdf, *derived) for name, (pdf, derived) in WORDING.items()}}
DUAL = tuple(name for name, (pdf, derived) in WORDING.items() if "text" in derived)
FORBIDDEN = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})


def _fields(snapshot: Snapshot) -> Iterator[tuple[str, str, str, str]]:
    for type_name, fields in FIELDS.items():
        for record in snapshot.of(type_name):
            key = primary_key(record, type_name)
            for field in fields:
                yield type_name, key, field, getattr(record, field)


def _bad_char(c: str, allowed: frozenset[str]) -> bool:
    if c == "�" or unicodedata.category(c) in FORBIDDEN:
        return True
    return c.isascii() and c not in allowed


def _charset(snapshot: Snapshot, allowed: Mapping[str, frozenset[str]]) -> list[str]:
    out = []
    for type_name, key, field, value in _fields(snapshot):
        if unicodedata.normalize("NFC", value) != value:
            out.append(f"{type_name} {key}.{field}: not NFC")
        ok = allowed.get(type_name, frozenset())
        out += [f"{type_name} {key}.{field}: {c!r} (U+{ord(c):04X}) at {i}"
                for i, c in enumerate(value) if _bad_char(c, ok)]
    return out


def _errata_at(snapshot: Snapshot) -> dict[str, dict[int, Any]]:
    at: dict[str, dict[int, Any]] = defaultdict(dict)
    for e in snapshot.of("errata_applied"):
        at[e.container_id][e.offset] = e
    return at


def _dual(snapshot: Snapshot, at: Mapping[str, Mapping[int, Any]]) -> list[str]:
    out = []
    for type_name in DUAL:
        for record in snapshot.of(type_name):
            key = primary_key(record, type_name)
            fixes = at.get(key, {})
            differ = {i for i, (a, b) in enumerate(zip(record.text_pdf, record.text)) if a != b}
            out += [f"{type_name} {key}: text differs from text_pdf at {i} without errata"
                    for i in sorted(differ - set(fixes))]
            out += [f"{e.errata_id}: {key} text has {record.text[i:i + 1]!r} at {i}, "
                    f"not {e.corrected_char!r}" for i, e in sorted(fixes.items())
                    if record.text[i:i + 1] != e.corrected_char]
    return out


def _pdf_text(snapshot: Snapshot) -> Iterator[tuple[str, str]]:
    for type_name, key, field, value in _fields(snapshot):
        if type_name in WORDING and field == WORDING[type_name][0]:
            yield key, value


def _errata_evidence(snapshot: Snapshot, at: Mapping[str, Mapping[int, Any]]) -> list[str]:
    errata = snapshot.of("errata_applied")
    corrected = {e.corrected_char for e in errata}
    misglyphs = {e.pdf_char for e in errata}
    out = []
    for key, text in _pdf_text(snapshot):
        out += [f"{key}@{i}: correction {c} occurs in the PDF text"
                for i, c in enumerate(text) if c in corrected]
        out += [f"{key}@{i}: misglyph {c} is not corrected here"
                for i, c in enumerate(text) if c in misglyphs and i not in at.get(key, {})]
    return out


def _book_names(snapshot: Snapshot) -> list[str]:
    out = []
    for b in snapshot.of("books"):
        expected = books.get_book(b.book_id).name if books.is_book_id(b.book_id) else None
        if b.name != expected:
            out.append(f"books {b.book_id}: name {b.name!r}, PDF title line {expected!r}")
    return out


def check_text(snapshot: Snapshot, ascii_allowed: Mapping[str, frozenset[str]]) -> GateResult:
    at = _errata_at(snapshot)
    details = _charset(snapshot, ascii_allowed) + _dual(snapshot, at) \
        + _errata_evidence(snapshot, at) + _book_names(snapshot)
    if not snapshot.of("verse_units"):
        details.append("no verse units to check")
    observed = {"violations": len(details), "errata": len(snapshot.of("errata_applied"))}
    return GateResult(NAME, True, not details, observed, {"violations": 0}, capped(details))

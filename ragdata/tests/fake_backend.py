"""A stand-in backend tree with the entity_dicts interface, for the K4 freezer and live probe.

``write(root)`` lays out ``root/backend/utils/{entity_dicts,verse_parser}.py`` with the same
matching code as the real backend over a tiny vocabulary, and the source files the
freezer fingerprints. ``LEXICON`` is what freezing it must give (one byte form).
"""

from __future__ import annotations

from pathlib import Path

ENTITY_DICTS = '''
PERSON_DICT = {"保羅": {"保羅", "掃羅"}, "掃羅": {"掃羅"}, "哥尼流": {"哥尼流"}}
PLACE_DICT = {"大馬士革": {"大馬士革"}, "鹽海": {"鹽海", "死海"}}
GROUP_DICT = {"門徒": {"門徒"}}
EVENT_KEYWORDS = {"保羅歸主", "天國", "渴慕"}
from utils.verse_parser import _ALL_NAMES as _BOOK_NAMES


def _named(table, text):
    matched = []
    for canonical, aliases in sorted(table.items(), key=lambda x: max(len(a) for a in x[1]),
                                     reverse=True):
        for alias in sorted(aliases, key=len, reverse=True):
            if alias in text:
                matched.append(canonical)
                break
    return matched


def match_persons_in_text(text):
    return _named(PERSON_DICT, text)


def match_places_in_text(text):
    return _named(PLACE_DICT, text)


def match_events_in_text(text):
    return [kw for kw in sorted(EVENT_KEYWORDS, key=lambda k: (-len(k), k)) if kw in text]


def match_books_in_text(text):
    from utils.verse_parser import _resolve_book
    seen, names = set(), []
    for name in sorted(_BOOK_NAMES, key=len, reverse=True):
        if len(name) < 2 or name not in text:
            continue
        book_id, full = _resolve_book(name)
        if book_id not in seen:
            seen.add(book_id)
            names.append(full)
    return names
'''

VERSE_PARSER = '''
_FULL = {"使徒行傳": "act", "以弗所書": "eph", "詩篇": "psa"}
_ABBREV = {"徒": "act", "弗": "eph", "詩": "psa", "使徒": "act"}
_ALL_NAMES = sorted(list(_FULL) + list(_ABBREV), key=len, reverse=True)


def _resolve_book(name):
    if name in _FULL:
        return _FULL[name], name
    book_id = _ABBREV[name]
    return book_id, {v: k for k, v in _FULL.items()}[book_id]
'''

SOURCES = ("backend/utils/entity_dicts.py", "scripts/entity_extraction/entity_dict.py",
           "backend/utils/verse_parser.py", "bible_chunking/config.py")


def write(root: Path) -> Path:
    """Write the fake tree under ``root``; return its backend directory."""
    backend = root / "backend"
    (backend / "utils").mkdir(parents=True)
    (backend / "utils" / "__init__.py").write_text("", encoding="utf-8")
    (backend / "utils" / "entity_dicts.py").write_text(ENTITY_DICTS, encoding="utf-8")
    (backend / "utils" / "verse_parser.py").write_text(VERSE_PARSER, encoding="utf-8")
    for source in SOURCES:
        if not (root / source).exists():
            (root / source).parent.mkdir(parents=True, exist_ok=True)
            (root / source).write_text("# fake\n", encoding="utf-8")
    return backend

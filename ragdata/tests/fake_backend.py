"""A stand-in backend tree with the entity_dicts interface, for the K4 freezer and live probe.

``write(root)`` lays out ``root/backend/utils/{entity_dicts,verse_parser}.py`` with the same
matching code as the real backend over a tiny vocabulary, importing it, as the real one
does, from ``root/scripts/entity_extraction/entity_dict.py`` and
``root/bible_chunking/config.py`` (the four files the freezer fingerprints).
``freeze_live`` stores its matches on a text layer's probe texts as ``ragdata freeze
probe`` does, in process.
"""

from __future__ import annotations

from pathlib import Path

from ragdata.kg import k4_live, k4_route
from ragdata.kg.layers import load_inputs
from ragdata.legacy import route_live

ON_PATH = '''
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
'''

ENTITY_DICT = '''
PERSON_DICT = {"保羅": {"保羅", "掃羅"}, "掃羅": {"掃羅"}, "哥尼流": {"哥尼流"}}
PLACE_DICT = {"大馬士革": {"大馬士革"}, "鹽海": {"鹽海", "死海"}}
GROUP_DICT = {"門徒": {"門徒"}}
'''

ENTITY_DICTS = ON_PATH + '''
from scripts.entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
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

CONFIG = '''
BOOKS = {"使徒行傳": "act", "以弗所書": "eph", "詩篇": "psa"}
'''

VERSE_PARSER = ON_PATH + '''
from bible_chunking.config import BOOKS as _FULL
_ABBREV = {"徒": "act", "弗": "eph", "詩": "psa", "使徒": "act"}
_ALL_NAMES = sorted(list(_FULL) + list(_ABBREV), key=len, reverse=True)


def _resolve_book(name):
    if name in _FULL:
        return _FULL[name], name
    book_id = _ABBREV[name]
    return book_id, {v: k for k, v in _FULL.items()}[book_id]
'''

FILES = {"backend/utils/entity_dicts.py": ENTITY_DICTS,
         "scripts/entity_extraction/entity_dict.py": ENTITY_DICT,
         "backend/utils/verse_parser.py": VERSE_PARSER, "bible_chunking/config.py": CONFIG}
SOURCES = tuple(FILES)


def write(root: Path) -> Path:
    """Write the fake tree under ``root`` (regular packages, as in the repo); return its
    backend directory."""
    for source, text in FILES.items():
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        (root / source).write_text(text, encoding="utf-8")
    for package in ("backend/utils", "scripts", "scripts/entity_extraction", "bible_chunking"):
        (root / package / "__init__.py").write_text("", encoding="utf-8")
    return root / "backend"


def freeze_live(backend: Path, text_dir: Path, lexicon: Path, ground_truth: Path,
                root: Path) -> Path:
    """Store what ``ragdata freeze probe`` stores for this backend, in process (no venv);
    returns the ``live.json`` written."""
    _, snapshot = load_inputs(text_dir)
    probes = k4_route.probe_texts(snapshot, ground_truth)
    live = route_live.sourced_probe(backend, k4_route.flatten(probes))
    return Path(k4_live.store_live(probes, live, k4_live.frozen_from(lexicon), root)["written"])

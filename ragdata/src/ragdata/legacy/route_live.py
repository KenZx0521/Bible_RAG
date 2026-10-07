"""Freeze the backend's live routing vocabulary, or run its live matchers (K4, D-12(a)).

Runs in the backend venv, with the backend directory on ``sys.path`` (it imports
``utils.entity_dicts``, which pulls ``scripts.entity_extraction.entity_dict`` and
``utils.verse_parser``). Two commands, both file in, file out:

    python -m ragdata.legacy.route_live freeze --backend-dir backend --out LEXICON.json
    python -m ragdata.legacy.route_live probe --backend-dir backend --texts T.json --out O.json

``freeze`` writes the vocabulary the four ``match_*_in_text`` functions actually use —
``PERSON_DICT``, ``PLACE_DICT``, ``EVENT_KEYWORDS`` and the book names of length ≥ 2 with
their resolution — every word ``external_legacy``, retired by R2, in the canonical byte
form of ``ragcommon.routing``. ``GROUP_DICT`` is imported by entity_dicts but matched by
nothing, so it is not frozen. ``probe`` returns the live matches of each text, the
reference G-ROUTE compares the frozen matcher with.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator, Sequence

from ragcommon import routing

SOURCES = ("backend/utils/entity_dicts.py", "scripts/entity_extraction/entity_dict.py",
           "backend/utils/verse_parser.py", "bible_chunking/config.py")
NOTE = "R1 凍結的 legacy 路由詞（{fn}）；行為與現行 entity_dicts 逐一相同，R2 由 PDF 版詞表取代"
MATCHERS = {
    "persons": "match_persons_in_text：依別名最長長度遞減（同長依檔案順序）逐一比對，任一別名是子字串即回傳 canonical",
    "places": "match_places_in_text：同 persons",
    "events": "match_events_in_text：依（長度遞減、碼位）排序，回傳是子字串的關鍵詞",
    "books": "match_books_in_text：依名稱長度遞減，略過單字名，回傳尚未出現過的書卷全名",
}
FUNCTIONS = {"persons": "match_persons_in_text", "places": "match_places_in_text",
             "events": "match_events_in_text", "books": "match_books_in_text"}


class LiveError(RuntimeError):
    """The backend cannot be imported or does not have the expected interface."""


@contextmanager
def _backend(backend_dir: Path) -> Iterator[tuple[ModuleType, ModuleType]]:
    """entity_dicts and verse_parser imported fresh from ``backend_dir``."""
    def drop() -> None:
        for name in [n for n in sys.modules if n == "utils" or n.startswith("utils.")]:
            del sys.modules[name]
    drop()
    sys.path.insert(0, str(backend_dir))
    try:
        try:
            dicts = importlib.import_module("utils.entity_dicts")
            parser = importlib.import_module("utils.verse_parser")
        except ImportError as exc:
            raise LiveError(f"{backend_dir}: cannot import utils.entity_dicts: {exc}") from None
        yield dicts, parser
    finally:
        sys.path.remove(str(backend_dir))
        drop()


def _prov(source: str, fn: str) -> dict[str, str]:
    return {"provenance_class": "external_legacy", "source": source,
            "note": NOTE.format(fn=fn), "retire_by": "R2"}


def _named(table: dict[str, Any], source: str, fn: str) -> list[dict[str, Any]]:
    return [{"canonical": canonical, "aliases": sorted(aliases, key=lambda a: (-len(a), a)),
             **_prov(source, fn)} for canonical, aliases in table.items()]


def _books(dicts: ModuleType, parser: ModuleType) -> list[dict[str, Any]]:
    names = [n for n in sorted(dicts._BOOK_NAMES, key=len, reverse=True)
             if len(n) >= routing.MIN_BOOK_NAME]
    rows = []
    for name in names:
        book_id, full_name = parser._resolve_book(name)
        rows.append({"name": name, "book_id": book_id, "full_name": full_name,
                     **_prov("backend/utils/verse_parser.py:_ALL_NAMES", FUNCTIONS["books"])})
    return rows


def _fingerprints(backend_dir: Path) -> dict[str, str]:
    root = Path(backend_dir).resolve().parent
    return {source: hashlib.sha256((root / source).read_bytes()).hexdigest()
            for source in SOURCES if (root / source).is_file()}


def freeze(backend_dir: Path | str) -> dict[str, Any]:
    """The routing lexicon document of the backend at ``backend_dir``."""
    backend_dir = Path(backend_dir)
    with _backend(backend_dir) as (dicts, parser):
        persons = _named(dicts.PERSON_DICT, "scripts/entity_extraction/entity_dict.py:PERSON_DICT",
                         FUNCTIONS["persons"])
        places = _named(dicts.PLACE_DICT, "scripts/entity_extraction/entity_dict.py:PLACE_DICT",
                        FUNCTIONS["places"])
        events = [{"term": kw, **_prov("backend/utils/entity_dicts.py:EVENT_KEYWORDS",
                                       FUNCTIONS["events"])}
                  for kw in sorted(dicts.EVENT_KEYWORDS, key=lambda k: (-len(k), k))]
        books = _books(dicts, parser)
    header = {"provenance_class": "external_legacy", "retire_by": "R2",
              "frozen_from": _fingerprints(backend_dir), "matchers": MATCHERS,
              "not_frozen": "GROUP_DICT：entity_dicts 有 import，但沒有任何 match 函式使用"}
    return {"schema": routing.SCHEMA, "variant": "legacy", "header": header,
            "persons": persons, "places": places, "events": events, "books": books}


def match_all(lexicon: routing.RoutingLexicon, text: str) -> dict[str, list[str]]:
    return {"persons": lexicon.match_persons(text), "places": lexicon.match_places(text),
            "events": lexicon.match_events(text), "books": lexicon.match_books(text)}


def probe(backend_dir: Path | str, texts: Sequence[str]) -> list[dict[str, list[str]]]:
    """The live backend's matches of each text."""
    with _backend(Path(backend_dir)) as (dicts, _):
        fns = {key: getattr(dicts, name) for key, name in FUNCTIONS.items()}
        return [{key: list(fn(text)) for key, fn in fns.items()} for text in texts]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="route_live")
    parser.add_argument("command", choices=("freeze", "probe"))
    parser.add_argument("--backend-dir", type=Path, required=True)
    parser.add_argument("--texts", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            args.out.write_bytes(routing.render_lexicon(freeze(args.backend_dir)))
            return 0
        texts = json.loads(args.texts.read_text(encoding="utf-8"))
        args.out.write_text(json.dumps(probe(args.backend_dir, texts), ensure_ascii=False),
                            encoding="utf-8")
        return 0
    except (LiveError, OSError, ValueError, AttributeError) as exc:
        sys.stderr.write(f"route_live {args.command}: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

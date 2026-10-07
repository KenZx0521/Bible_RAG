"""Derive ragcommon's verse-grid data from a stored text layer (design §2.12).

The text layer is the source of truth: each chapter's max verse (chapters.jsonl),
the 11 omitted slots with the unit whose variant footnote holds them
(verse_slots.jsonl) and the external-reference aliases (ref_aliases.jsonl).
The layer is verified against its manifest before anything is read. G-REF
(``ragdata gate text``) fails until this has been run on the layer being gated.

  versification        write packages/ragcommon/data/versification.json and ref_aliases.jsonl
  check-abbreviations  verify every pdf_abbreviation in books.json occurs in the
                       PDF's parallel references or footnotes

  scripts/.venv/bin/python scripts/derive_ragcommon_data.py versification \\
      --text-layer /mnt/ollama-data/bible_rag_store/layers/text/text@<version>
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT / "packages", ROOT / "ragdata" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from ragcommon import books, ids  # noqa: E402
from ragdata.store import LayerData, StoreError, read_layer  # noqa: E402

DATA = ROOT / "packages" / "ragcommon" / "data"
OUT = DATA / "versification.json"
ALIASES_OUT = DATA / "ref_aliases.jsonl"
ALIAS_KEYS = ("external_ref", "relation", "target", "note", "provenance_class")


class DeriveError(ValueError):
    """The text layer does not hold a contiguous verse grid of the 66 books."""


def _rows(layer: LayerData, name: str) -> tuple[dict[str, Any], ...]:
    if f"{name}.jsonl" not in layer.rows:
        raise DeriveError(f"{layer.path}: no {name}.jsonl")
    return layer.rows[f"{name}.jsonl"]


def _grid(chapters: tuple[dict[str, Any], ...]) -> dict[str, list[int]]:
    by_book: dict[str, dict[int, int]] = collections.defaultdict(dict)
    for c in chapters:
        if not books.is_book_id(c["book_id"]):
            raise DeriveError(f"unknown book {c['book_id']!r} at {c['chapter_key']}")
        by_book[c["book_id"]][c["chapter"]] = c["max_verse"]
    grid = {}
    for book_id in books.book_ids():
        found = by_book.get(book_id)
        if not found:
            raise DeriveError(f"missing book {book_id}")
        if sorted(found) != list(range(1, len(found) + 1)):
            raise DeriveError(f"{book_id}: chapter numbers are not 1..n")
        grid[book_id] = [found[c] for c in range(1, len(found) + 1)]
    return grid


def derive_versification(layer_dir: Path | str) -> dict[str, Any]:
    layer = read_layer(layer_dir)
    order = {b: i for i, b in enumerate(books.book_ids())}
    omitted = [{"slot_key": s["slot_key"],
                "variant_in_footnote_of": ids.parse(s["variant_footnote_id"]).parent.raw}
               for s in _rows(layer, "verse_slots") if s["status"] == "omitted_variant"]
    omitted.sort(key=lambda o: (order[ids.parse(o["slot_key"]).book_id],
                                ids.parse(o["slot_key"]).chapter, ids.parse(o["slot_key"]).verse))
    return {
        "schema": "ragcommon.versification.v1",
        "source": {"kind": "text_layer", "layer_version": layer.version,
                   "derived_by": "scripts/derive_ragcommon_data.py versification"},
        "max_verse": _grid(_rows(layer, "chapters")),
        "omitted_slots": omitted,
    }


def derive_aliases(layer_dir: Path | str) -> list[dict[str, Any]]:
    rows = _rows(read_layer(layer_dir), "ref_aliases")
    return sorted(({k: r[k] for k in ALIAS_KEYS} for r in rows), key=lambda r: r["external_ref"])


def dump_versification(doc: dict[str, Any]) -> str:
    """JSON with one line per book so diffs stay readable."""
    books_lines = [f'    "{b}": {json.dumps(v)}' for b, v in doc["max_verse"].items()]
    omitted_lines = ["    " + json.dumps(o) for o in doc["omitted_slots"]]
    return "\n".join([
        "{",
        f'  "schema": {json.dumps(doc["schema"])},',
        f'  "source": {json.dumps(doc["source"], ensure_ascii=False)},',
        '  "max_verse": {', ",\n".join(books_lines), "  },",
        '  "omitted_slots": [', ",\n".join(omitted_lines), "  ]",
        "}",
    ]) + "\n"


def dump_aliases(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def count_abbreviations(layer_dir: Path | str) -> collections.Counter:
    """Count book-name forms followed by a numeral in parallel refs and footnotes."""
    layer = read_layer(layer_dir)
    table = books.default_books()
    names = [n.text for n in table.names_longest_first()] + sorted(table.ambiguous, key=len,
                                                                   reverse=True)
    pattern = re.compile("(" + "|".join(map(re.escape, names)) + ")(?=[0-9〇零一二三四五六七八九十百])")
    texts = [r["raw"] for r in _rows(layer, "parallel_refs")]
    texts += [r["text_pdf"] for r in _rows(layer, "footnotes")]
    counts: collections.Counter = collections.Counter()
    for text in texts:
        counts.update(m.group(1) for m in pattern.finditer(text))
    return counts


def missing_pdf_abbreviations(counts: collections.Counter) -> list[str]:
    return [a for b in books.all_books() for a in b.pdf_abbreviations if counts[a] == 0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["versification", "check-abbreviations"])
    parser.add_argument("--text-layer", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--aliases-out", type=Path, default=ALIASES_OUT)
    args = parser.parse_args(argv)
    try:
        if args.command == "versification":
            args.out.write_text(dump_versification(derive_versification(args.text_layer)),
                                encoding="utf-8")
            args.aliases_out.write_text(dump_aliases(derive_aliases(args.text_layer)),
                                        encoding="utf-8")
            return 0
        missing = missing_pdf_abbreviations(count_abbreviations(args.text_layer))
    except (DeriveError, StoreError) as exc:
        print(f"derive_ragcommon_data: {exc}", file=sys.stderr)
        return 2
    if missing:
        print(f"missing pdf_abbreviations: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

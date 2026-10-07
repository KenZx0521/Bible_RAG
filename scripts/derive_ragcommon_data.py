"""Derive ragcommon reference data from the audit prototype's canonical verse table.

Interim source until the P2 text layer exists (it will overwrite the output):
/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/gap_pdf_canonical/canonical_full.jsonl

  versification        write packages/ragcommon/data/versification.json
  check-abbreviations  verify every pdf_abbreviation in books.json occurs in the
                       PDF's parallel references or footnotes

  scripts/.venv/bin/python scripts/derive_ragcommon_data.py versification
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from ragcommon import books  # noqa: E402

CANONICAL = Path("/mnt/ollama-data/bible_rag_store/reference/audit_prototypes/"
                 "gap_pdf_canonical/canonical_full.jsonl")
OUT = ROOT / "packages" / "ragcommon" / "data" / "versification.json"
STATUSES = frozenset({"present", "omitted_variant"})
NOTE = "暫時資料：由稽核原型 canonical_full.jsonl 推導；P2 文字層產出 verse_slots 後覆寫"


class DeriveError(ValueError):
    """The canonical table is not a contiguous verse grid."""


def _records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _add(chapters: dict, rec: dict) -> None:
    if not books.is_book_id(rec["book"]):
        raise DeriveError(f"unknown book {rec['book']!r} at {rec['id']}")
    if rec["status"] not in STATUSES:
        raise DeriveError(f"unknown status {rec['status']!r} at {rec['id']}")
    verses = chapters.setdefault(rec["book"], {}).setdefault(rec["chapter"], set())
    span = set(range(rec["v_start"], rec["v_end"] + 1))
    if verses & span:
        raise DeriveError(f"overlap at {rec['id']}")
    verses |= span


def _max_list(book_id: str, chapters: dict[int, set[int]] | None) -> list[int]:
    if not chapters:
        raise DeriveError(f"missing book {book_id}")
    if sorted(chapters) != list(range(1, len(chapters) + 1)):
        raise DeriveError(f"{book_id}: chapter numbers are not 1..n")
    result = []
    for ch in range(1, len(chapters) + 1):
        top = max(chapters[ch])
        if chapters[ch] != set(range(1, top + 1)):
            raise DeriveError(f"{book_id}.{ch}: verse gap")
        result.append(top)
    return result


def derive_versification(path: Path | str) -> dict:
    path = Path(path)
    chapters: dict[str, dict[int, set[int]]] = {}
    omitted = []
    for rec in _records(path):
        _add(chapters, rec)
        if rec["status"] == "omitted_variant":
            omitted.append({"slot_key": rec["id"], "variant_in_footnote_of": rec["variant_in_footnote_of"]})
    order = {b: i for i, b in enumerate(books.book_ids())}
    omitted.sort(key=lambda o: (order[o["slot_key"].split(".")[0]],
                                *map(int, o["slot_key"].split(".")[1:])))
    return {
        "schema": "ragcommon.versification.v1",
        "source": {"kind": "audit_prototype", "path": str(path),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "derived_by": "scripts/derive_ragcommon_data.py versification", "note": NOTE},
        "max_verse": {b: _max_list(b, chapters.get(b)) for b in books.book_ids()},
        "omitted_slots": omitted,
    }


def dump_versification(doc: dict) -> str:
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


def count_abbreviations(path: Path | str) -> collections.Counter:
    """Count book-name forms followed by a numeral in parallel refs and footnotes."""
    table = books.default_books()
    names = [n.text for n in table.names_longest_first()] + sorted(table.ambiguous, key=len, reverse=True)
    pattern = re.compile("(" + "|".join(map(re.escape, names)) + ")(?=[0-9〇零一二三四五六七八九十百])")
    counts: collections.Counter = collections.Counter()
    for rec in _records(Path(path)):
        for ann in rec.get("annotations", []):
            if ann.get("type") in ("parallel_ref", "footnote"):
                counts.update(m.group(1) for m in pattern.finditer(ann["text"]))
    return counts


def missing_pdf_abbreviations(counts: collections.Counter) -> list[str]:
    return [a for b in books.all_books() for a in b.pdf_abbreviations if counts[a] == 0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["versification", "check-abbreviations"])
    parser.add_argument("--canonical", type=Path, default=CANONICAL)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.command == "versification":
        args.out.write_text(dump_versification(derive_versification(args.canonical)), encoding="utf-8")
        return 0
    missing = missing_pdf_abbreviations(count_abbreviations(args.canonical))
    if missing:
        print(f"missing pdf_abbreviations: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

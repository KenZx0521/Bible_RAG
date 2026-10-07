"""Difference reports of the text layer against the corpora it replaces (stored in the layer).

- ``diff_vs_bible_md.tsv``: every difference to bible_md, with its cause (``md``);
- ``diff_vs_canonical_full.tsv``: every field difference to the audit's
  canonical_full.jsonl (``canonical``);
- ``diff_summary.json``: counts by cause and group, and the reconciliation with
  the audit's numbers that G-DIFF judges.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragdata.contract.registry import (
    DIFF_CANONICAL_REPORT, DIFF_MD_REPORT, DIFF_SUMMARY_REPORT,
)
from ragdata.gates.base import GateResult
from ragdata.gates.diff import check_diff, metric
from ragdata.stages.diffs import canonical, md
from ragdata.stages.s01_extract import S1Book
from ragdata.stages.s02_parse.units import number_footnotes, unit_key

MD_FILE, CANONICAL_FILE, SUMMARY_FILE = DIFF_MD_REPORT, DIFF_CANONICAL_REPORT, DIFF_SUMMARY_REPORT
SUMMARY_SCHEMA = "ragdata.diff_summary.v1"


@dataclass(frozen=True)
class DiffReports:
    files: Mapping[str, bytes]
    gate: GateResult


def glyph_chars(parsed: Sequence[Any], s1_books: Mapping[str, S1Book]
                ) -> dict[str, tuple[md.CharInfo, ...]]:
    """Where each character of every unit and footnote was typeset (from S2 ParsedBooks)."""
    chars: dict[str, tuple[md.CharInfo, ...]] = {}
    for book in parsed:
        book_id = book.rows["books"][0]["book_id"]
        edges = {page: bounds[2] for page, bounds in s1_books[book_id].pages.items()}
        for verse in book.stream.verses:
            chars[unit_key(book_id, verse)] = md.char_info(verse.glyphs, edges)
        for fid, note in number_footnotes(book_id, book.stream):
            chars[fid] = md.char_info(note.glyphs, edges)
    return chars


def diff_reports(rows: Mapping[str, Sequence[Mapping[str, Any]]],
                 chars: Mapping[str, Sequence[md.CharInfo]], md_dir: Path,
                 canonical_path: Path, expect: Mapping[str, Mapping[str, int]]) -> DiffReports:
    """Both diffs of the final text rows, their summary and the G-DIFF verdict."""
    md_diff = md.diff_md(rows, chars, md_dir)
    can_diff = canonical.diff_canonical(rows, canonical_path)
    summaries = {"bible_md": md_diff.summary, "canonical_full": can_diff.summary}
    reconciliation = [{"reference": ref, "metric": path, "expected": value,
                       "observed": metric(summaries[ref], path, None),
                       "match": metric(summaries[ref], path, None) == value}
                      for ref, values in expect.items() for path, value in values.items()]
    summary = {"schema": SUMMARY_SCHEMA, **summaries, "groups": md.GROUPS,
               "reconciliation": reconciliation}
    files = {MD_FILE: md.encode_tsv(md_diff.rows),
             CANONICAL_FILE: canonical.encode_tsv(can_diff.rows),
             SUMMARY_FILE: (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1)
                            + "\n").encode()}
    return DiffReports(files, check_diff(summaries, expect))

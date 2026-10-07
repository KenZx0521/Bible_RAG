"""Gate-time G-CONSERVE and G-XCHECK: re-read the sources a stored text layer came from.

At build time both gates read the build's own S1/S2 state. A stored layer is
re-checked against its sources instead:

- G-CONSERVE classifies every glyph of the src layer's extracts by style again
  and requires each text category to equal what the *stored* records hold;
- G-XCHECK reads the PDFs with poppler again (each PDF must be the one the
  layer's books record names by sha256), checks the stored units, and requires
  the stored ``xcheck_report.json`` to equal the new report.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from ragcommon import ids
from ragdata.contract import primary_key, record_to_dict
from ragdata.gates.base import GateInputError, GateResult, Snapshot
from ragdata.gates.conserve import check_conserve
from ragdata.stages import s00_source, s01_extract, s03_xcheck
from ragdata.stages.s02_parse.conserve import stored_tally

BOOK_TYPES = ("verse_units", "chapter_texts", "headings", "parallel_refs",
              "footnotes", "speakers")


def _records_by_book(snapshot: Snapshot) -> dict[str, dict[str, list[dict[str, Any]]]]:
    by_book: dict[str, dict[str, list[dict[str, Any]]]] = {
        b.book_id: {t: [] for t in BOOK_TYPES} for b in snapshot.of("books")}
    for type_name in BOOK_TYPES:
        for record in snapshot.of(type_name):
            book = ids.parse(primary_key(record, type_name)).book_id
            if book in by_book:
                by_book[book][type_name].append(record_to_dict(record))
    return by_book


def conserve_from_src(snapshot: Snapshot, src_files: Mapping[str, bytes],
                      expect_path: Path) -> GateResult:
    """G-CONSERVE of a stored layer against the extracts of the src layer it was built on."""
    tallies = {}
    for book_id, records in _records_by_book(snapshot).items():
        name = f"extract_{book_id}.jsonl"
        if name not in src_files:
            raise GateInputError(f"the src layer has no {name}")
        tallies[book_id] = stored_tally(s01_extract.load_s1(src_files[name], name).lines, records)
    return check_conserve(tallies, s00_source.load_expect(expect_path)["conserve"])


def xcheck_from_pdfs(snapshot: Snapshot, pdf_dir: Path, stored: bytes | None) -> GateResult:
    """G-XCHECK of a stored layer: poppler again, and the stored report must be the same."""
    report = s03_xcheck.xcheck(Path(pdf_dir), [record_to_dict(b) for b in snapshot.of("books")],
                               [record_to_dict(u) for u in snapshot.of("verse_units")])
    result = s03_xcheck.check_xcheck(report)
    if stored != s03_xcheck.encode_report(report):
        note = f"stored {s03_xcheck.REPORT_FILE} differs from the poppler run now"
        result = dataclasses.replace(result, passed=False, details=(*result.details, note))
    return result

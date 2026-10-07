"""Build stages (design §4). ``build("text")`` runs S0–S4 and stores two layers:

- ``src`` — ``source_manifest.json`` (S0) and ``extract_{book_id}.jsonl`` per PDF (S1);
- ``text`` — every text record type: what the PDFs determine (S2: books, chapters,
  verse_units, verse_slots, chapter_texts, headings, parallel_refs, footnotes,
  speakers, name_spans) with the overlay applied (S4: errata in ``text``,
  ``errata_applied``, ``ref_aliases``), and the reports that go with it —
  ``xcheck_report.json`` (S3, poppler), ``overlay_report.json`` (S4) and the
  differences to bible_md and canonical_full (``diff_*``).

The build runs the gates over what it is about to write — G-TOOL, G-SRC,
G-CONSERVE, G-COUNT, G-REFINT, G-TEXT, G-XCHECK and G-DIFF — and reports them;
G-DET compares two builds (``ragdata det``) and ``ragdata gate text`` re-checks a
stored layer, G-REF included (it needs ragcommon's data derived from the stored
layer). Only a build whose hard gates all pass is stored: a red build writes
nothing, so no layer in the store was ever built from unpinned PDFs or tools or
with unexplained differences. To look at a red build, fix the pin or rerun with
``--store`` on a scratch directory.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from ragdata import paths
from ragdata.contract import parse_record
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.gates import diff as gate_diff
from ragdata.gates.base import GateResult, snapshot
from ragdata.gates.conserve import check_conserve
from ragdata.gates.counts import check_counts
from ragdata.gates.refint import check_refint
from ragdata.gates.text import check_text
from ragdata.stages import s00_source, s01_extract, s03_xcheck, s04_overlay
from ragdata.stages.diffs import diff_reports, glyph_chars
from ragdata.stages.s02_parse import S2_TYPES, ParsedBook, parse_book
from ragdata.stages.s02_parse.names import with_merge_groups
from ragdata.store import StoredLayer, encode_jsonl, write_layer

BUILDABLE = ("text",)
REPORT_SCHEMA = "ragdata.build_report.v1"
TEXT_TYPES = (*S2_TYPES, "errata_applied", "ref_aliases")


@dataclass(frozen=True)
class TextInputs:
    """What a text build reads besides the PDFs (registries and the reference corpora)."""

    registries: Path = paths.REGISTRIES
    md_dir: Path = paths.BIBLE_MD
    canonical: Path = paths.CANONICAL
    diff_expect: Path = gate_diff.EXPECT_PATH


def gates_pass(gates: Sequence[GateResult]) -> bool:
    """True when gates ran and every hard one passed."""
    return bool(gates) and all(g.passed for g in gates if g.hard)


@dataclass(frozen=True)
class BuildResult:
    layers: Mapping[str, StoredLayer]
    gates: tuple[GateResult, ...]
    timings: Mapping[str, float]

    @property
    def passed(self) -> bool:
        return gates_pass(self.gates)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "pass": self.passed,
                "layers": {k: {"version": v.version, "path": str(v.path)}
                           for k, v in self.layers.items()},
                "gates": [g.to_json() for g in self.gates],
                "timings_s": {k: round(v, 2) for k, v in self.timings.items()}}


@dataclass
class _Clock:
    laps: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def lap(self, name: str) -> Iterator[None]:
        start = time.monotonic()
        yield
        self.laps[name] = self.laps.get(name, 0.0) + time.monotonic() - start


@dataclass(frozen=True)
class _Source:
    pdfs: tuple[s00_source.SourcePdf, ...]
    tools: Mapping[str, str]
    s1: Mapping[str, tuple[bytes, s01_extract.S1Book]]
    manifest: Mapping[str, Any]

    @property
    def books(self) -> dict[str, s01_extract.S1Book]:
        return {book_id: book for book_id, (_, book) in self.s1.items()}


def _extract(pdf_dir: Path, workers: int) -> _Source:
    pdfs = s00_source.discover(Path(pdf_dir))
    tools = s00_source.toolchain()
    s1 = s01_extract.extract_all({p.book_id: p.path for p in pdfs}, workers)
    books = {book_id: book for book_id, (_, book) in s1.items()}
    return _Source(pdfs, tools, s1, s00_source.build_manifest(pdfs, books, tools))


def _parse_all(pdfs: Sequence[s00_source.SourcePdf],
               s1_books: Mapping[str, s01_extract.S1Book]) -> list[ParsedBook]:
    """Parse every book; unit and heading ``ord`` run in canonical order over all books."""
    parsed, unit_ord, heading_ord = [], 1, 1
    for pdf in pdfs:
        book = parse_book(s1_books[pdf.book_id], pdf.book_id, pdf.path.stem, pdf.sha256,
                          unit_ord, heading_ord)
        unit_ord += len(book.rows["verse_units"])
        heading_ord += len(book.rows["headings"])
        parsed.append(book)
    return parsed


def _s2_rows(parsed: Sequence[ParsedBook]) -> dict[str, list[dict[str, Any]]]:
    rows = {name: [row for p in parsed for row in p.rows[name]] for name in S2_TYPES}
    return {**rows, "name_spans": list(with_merge_groups(rows["name_spans"]))}


def _record_gates(parsed: Sequence[ParsedBook], overlay: s04_overlay.OverlayResult,
                  counts_path: Path, expect: Mapping[str, Any]) -> list[GateResult]:
    records = snapshot({name: [parse_record(name, row) for row in overlay.rows[name]]
                        for name in TEXT_TYPES})
    conserve = check_conserve({p.rows["books"][0]["book_id"]: p.tally for p in parsed},
                              expect["conserve"])
    count = check_counts(records, "text", load_counts(counts_path).get("text", {}))
    return [conserve, count, check_refint(records, "text"),
            check_text(records, overlay.ascii_allowed)]


def _store(root: Path, source: _Source, rows: Mapping[str, Sequence[Mapping[str, Any]]],
           reports: Mapping[str, bytes]) -> dict[str, StoredLayer]:
    src_files = {"source_manifest.json": s00_source.encode_manifest(source.manifest),
                 **{f"extract_{book_id}.jsonl": data for book_id, (data, _) in source.s1.items()}}
    src = write_layer(root, "src", src_files, exist_ok=True)
    text_files = {**{f"{name}.jsonl": encode_jsonl(rows[name]) for name in TEXT_TYPES},
                  **reports}
    text = write_layer(root, "text", text_files, depends_on={"src": src.version}, exist_ok=True)
    return {"src": src, "text": text}


def build(layer: str, pdf_dir: Path, store_root: Path, counts_path: Path = PDF_COUNTS_PATH,
          expect_path: Path = s00_source.EXPECT_PATH, workers: int = 8,
          inputs: TextInputs = TextInputs()) -> BuildResult:
    """Build ``layer`` from the PDFs, gate it, and store it only if every hard gate passed."""
    if layer not in BUILDABLE:
        raise ValueError(f"no stage builds layer {layer!r}")
    clock = _Clock()
    expect = s00_source.load_expect(expect_path)
    with clock.lap("s0_s1_extract"):
        source = _extract(pdf_dir, workers)
    with clock.lap("s2_parse"):
        parsed = _parse_all(source.pdfs, source.books)
    with clock.lap("s4_overlay"):
        overlay = s04_overlay.overlay(_s2_rows(parsed), inputs.registries)
    with clock.lap("s3_xcheck"):
        xcheck = s03_xcheck.xcheck(Path(pdf_dir), overlay.rows, workers=workers)
    with clock.lap("diffs"):
        diffs = diff_reports(overlay.rows, glyph_chars(parsed, source.books), inputs.md_dir,
                             inputs.canonical, inputs.diff_expect)
    with clock.lap("gates"):
        gates = [s00_source.check_tools(source.tools, expect),
                 s00_source.check_source(source.manifest, expect),
                 *_record_gates(parsed, overlay, Path(counts_path), expect),
                 s03_xcheck.check_xcheck(xcheck), diffs.gate]
    reports = {s03_xcheck.REPORT_FILE: s03_xcheck.encode_report(xcheck),
               s04_overlay.REPORT_FILE: s04_overlay.encode_report(overlay.report), **diffs.files}
    layers: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            layers = _store(Path(store_root), source, overlay.rows, reports)
    return BuildResult(MappingProxyType(layers), tuple(gates), MappingProxyType(clock.laps))

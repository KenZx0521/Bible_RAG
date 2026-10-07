"""Build stages (design §4). ``build("text")`` runs S0, S1 and S2 and stores two layers:

- ``src`` — ``source_manifest.json`` (S0) and ``extract_{book_id}.jsonl`` per PDF (S1);
- ``text`` — every record type the PDFs determine (S2): books, chapters, verse_units,
  verse_slots, chapter_texts, headings, parallel_refs, footnotes, speakers and
  name_spans, built on that src.

Errata and reference aliases come with S4, so ``ragdata gate text`` does not pass
the layer yet. The build runs the gates over what it is about to write — G-TOOL,
G-SRC, G-CONSERVE, G-COUNT (every text count) and G-REFINT — and reports them;
G-DET compares two builds (``ragdata det``). Only a build whose hard gates all
pass is stored: a red build writes nothing, so no layer in the store was ever
built from unpinned PDFs or tools (a stored layer carries no verdict of its own).
To look at a red build, fix the pin or rerun with ``--store`` on a scratch directory.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from ragdata.contract import parse_record
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.gates.base import GateResult, snapshot
from ragdata.gates.conserve import check_conserve
from ragdata.gates.counts import check_counts
from ragdata.gates.refint import check_refint
from ragdata.stages import s00_source, s01_extract
from ragdata.stages.s02_parse import S2_TYPES, ParsedBook, parse_book
from ragdata.stages.s02_parse.names import with_merge_groups
from ragdata.store import StoredLayer, encode_jsonl, write_layer

BUILDABLE = ("text",)
REPORT_SCHEMA = "ragdata.build_report.v1"
TEXT_TYPES = S2_TYPES


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


def _text_rows(parsed: Sequence[ParsedBook]) -> dict[str, list[dict[str, Any]]]:
    rows = {name: [row for p in parsed for row in p.rows[name]] for name in TEXT_TYPES}
    return {**rows, "name_spans": list(with_merge_groups(rows["name_spans"]))}


def _text_gates(parsed: Sequence[ParsedBook], rows: Mapping[str, list[dict[str, Any]]],
                counts_path: Path, expect: Mapping[str, Any]) -> list[GateResult]:
    records = snapshot({name: [parse_record(name, row) for row in rows[name]]
                        for name in TEXT_TYPES})
    conserve = check_conserve({p.rows["books"][0]["book_id"]: p.tally for p in parsed},
                              expect["conserve"])
    count = check_counts(records, "text", load_counts(counts_path).get("text", {}))
    return [conserve, count, check_refint(records, "text")]


def _store(root: Path, manifest: Mapping[str, Any], s1: Mapping[str, tuple[bytes, Any]],
           rows: Mapping[str, list[dict[str, Any]]]) -> dict[str, StoredLayer]:
    src_files = {"source_manifest.json": s00_source.encode_manifest(manifest),
                 **{f"extract_{book_id}.jsonl": data for book_id, (data, _) in s1.items()}}
    src = write_layer(root, "src", src_files, exist_ok=True)
    text_files = {f"{name}.jsonl": encode_jsonl(rows[name]) for name in TEXT_TYPES}
    text = write_layer(root, "text", text_files, depends_on={"src": src.version}, exist_ok=True)
    return {"src": src, "text": text}


def build(layer: str, pdf_dir: Path, store_root: Path, counts_path: Path = PDF_COUNTS_PATH,
          expect_path: Path = s00_source.EXPECT_PATH, workers: int = 8) -> BuildResult:
    """Build ``layer`` from the PDFs, gate it, and store it only if every hard gate passed."""
    if layer not in BUILDABLE:
        raise ValueError(f"no stage builds layer {layer!r}")
    clock = _Clock()
    expect = s00_source.load_expect(expect_path)
    with clock.lap("s0_s1_extract"):
        pdfs = s00_source.discover(Path(pdf_dir))
        tools = s00_source.toolchain()
        s1 = s01_extract.extract_all({p.book_id: p.path for p in pdfs}, workers)
        s1_books = {book_id: book for book_id, (_, book) in s1.items()}
        manifest = s00_source.build_manifest(pdfs, s1_books, tools)
    with clock.lap("s2_parse"):
        parsed = _parse_all(pdfs, s1_books)
        rows = _text_rows(parsed)
    with clock.lap("gates"):
        gates = [s00_source.check_tools(tools, expect), s00_source.check_source(manifest, expect),
                 *_text_gates(parsed, rows, Path(counts_path), expect)]
    layers: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            layers = _store(Path(store_root), manifest, s1, rows)
    return BuildResult(MappingProxyType(layers), tuple(gates), MappingProxyType(clock.laps))

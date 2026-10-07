"""Build stages (design §4). ``build("text")`` runs S0, S1 and S2a and stores two layers:

- ``src`` — ``source_manifest.json`` (S0) and ``extract_{book_id}.jsonl`` per PDF (S1);
- ``text`` — books, chapters, verse_units and verse_slots (S2a), built on that src.

The text layer is not complete yet: headings, parallel references, footnotes,
speakers, superscriptions, divisions and name spans come with S2b, errata with
S4, so ``ragdata gate text`` still fails it. The build runs the gates over
what it is about to write — G-TOOL, G-SRC, G-CONSERVE and G-COUNT on the S2a
counts — and reports them; G-DET compares two builds (``ragdata det``). Only a
build whose hard gates all pass is stored: a red build writes nothing, so no
layer in the store was ever built from unpinned PDFs or tools (a stored layer
carries no verdict of its own). To look at a red build, fix the pin or rerun
with ``--store`` on a scratch directory.
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
from ragdata.stages import s00_source, s01_extract
from ragdata.stages.s02_parse import ParsedBook, parse_book
from ragdata.store import StoredLayer, encode_jsonl, write_layer

BUILDABLE = ("text",)
REPORT_SCHEMA = "ragdata.build_report.v1"
TEXT_TYPES = ("books", "chapters", "verse_units", "verse_slots")
S2A_COUNT_KEYS = ("books", "chapters", "verse_units", "merged_units", "present_slots",
                  "omitted_slots", "omitted_slot_keys", "slot_rows", "selah_markers")


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
    parsed, ord_start = [], 1
    for pdf in pdfs:
        book = parse_book(s1_books[pdf.book_id], pdf.book_id, pdf.path.stem, pdf.sha256, ord_start)
        ord_start += len(book.records.units)
        parsed.append(book)
    return parsed


def _text_rows(parsed: Sequence[ParsedBook]) -> dict[str, list[dict[str, Any]]]:
    return {"books": [p.records.book for p in parsed],
            "chapters": [c for p in parsed for c in p.records.chapters],
            "verse_units": [u for p in parsed for u in p.records.units],
            "verse_slots": [s for p in parsed for s in p.records.slots]}


def _text_gates(parsed: Sequence[ParsedBook], rows: Mapping[str, list[dict[str, Any]]],
                counts_path: Path, expect: Mapping[str, Any]) -> list[GateResult]:
    records = {name: [parse_record(name, row) for row in rows[name]] for name in TEXT_TYPES}
    conserve = check_conserve({p.records.book["book_id"]: p.tally for p in parsed},
                              expect["conserve"])
    count = check_counts(snapshot(records), "text", load_counts(counts_path).get("text", {}),
                         keys=S2A_COUNT_KEYS)
    return [conserve, count]


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

"""Command line for the snapshot pipeline.

    python -m ragdata build text --pdf-dir bible_pdf [--store DIR] [--counts YAML]
                                 [--source-expect YAML] [--registries DIR] [--md-dir DIR]
                                 [--canonical JSONL] [--diff-expect YAML] [--workers N]
                                 [--report FILE]
    python -m ragdata build struct --text TEXT_LAYER_DIR [--store DIR] [--counts YAML]
                                 [--legacy-dir DIR] [--tokenizer FILE] [--report FILE]
    python -m ragdata build emb --struct STRUCT_LAYER_DIR --text TEXT_LAYER_DIR [--store DIR]
                                 [--counts YAML] [--legacy-dir DIR] [--tokenizer FILE]
                                 [--reranker-tokenizer FILE] [--device DEV] [--report FILE]
    python -m ragdata gate {text,struct,emb} LAYER_DIR [--dep DIR ...] [--pdf-dir DIR]
                                 [--counts YAML] [--source-expect YAML] [--registries DIR]
                                 [--tokenizer FILE] [--reranker-tokenizer FILE]
                                 [--legacy-dir DIR] [--device DEV] [--report FILE]
    python -m ragdata det FIRST_DIR SECOND_DIR [--report FILE]

A text layer is gated with its src layer as a dependency (G-CONSERVE re-reads
it) and the PDFs (G-XCHECK re-reads them); without them those gates fail closed.
A struct layer is built from, and gated with, its text layer; G-STRUCT counts
tokens with the pinned BGE-M3 tokenizer (the HF cache, or ``--tokenizer``) and
fails closed when it does not load. An emb layer is built from a struct layer and
the text layer it was built on, and gated with both (``--dep``); its build and
G-EMB/G-ENC load the pinned BGE-M3 offline (and the reranker tokenizer), and
G-ENC compares the vectors with the old ``output/`` (``--legacy-dir``). ``det`` on
two emb layers also compares their vectors within G-DET's tolerance.

Reports are JSON on stdout (and in ``--report`` when given). Exit status:
0 everything passed, 1 a hard gate failed, 2 bad input (including a stage that
met input it cannot turn into records), 3 an internal error (a bug: the
traceback goes to stderr, and no report is written, so a crash is never
mistaken for a gate result).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Sequence

import yaml

from ragdata import paths, stages
from ragdata.contract import LAYERS
from ragdata.contract.counts import PDF_COUNTS_PATH, CountsError
from ragdata.gates import check_det
from ragdata.gates.diff import EXPECT_PATH as DIFF_EXPECT_PATH
from ragdata.gates.runner import GateInputError, GateInputs, gate_layer
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import build as struct_stage
from ragdata.stages.s06_emb import build as emb_stage
from ragdata.stages.s00_source import EXPECT_PATH
from ragdata.store import DEFAULT_ROOT, StoreError

EXIT_OK, EXIT_GATE_FAILED, EXIT_ERROR, EXIT_INTERNAL = 0, 1, 2, 3


class CliError(ValueError):
    """Bad command-line input."""


def _encoder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reranker-tokenizer", type=Path, default=paths.RERANKER_TOKENIZER,
                        help="bge-reranker-v2-m3 tokenizer.json (emb)")
    parser.add_argument("--device", help="where BGE-M3 runs (emb; default cuda if available)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragdata", description="Bible_RAG snapshot pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build a layer from the PDFs into the store")
    build.add_argument("layer", choices=stages.BUILDABLE)
    build.add_argument("--pdf-dir", type=Path, help="the PDFs (text)")
    build.add_argument("--text", type=Path, help="the text layer to build on (struct, emb)")
    build.add_argument("--struct", type=Path, help="the struct layer to build on (emb)")
    build.add_argument("--legacy-dir", type=Path, default=paths.LEGACY_OUTPUT,
                       help="the old output/: legacy_ids (struct), vectors (emb)")
    build.add_argument("--tokenizer", type=Path, help="BGE-M3 tokenizer.json (struct, emb)")
    _encoder_arguments(build)
    build.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    build.add_argument("--counts", type=Path, default=PDF_COUNTS_PATH)
    build.add_argument("--source-expect", type=Path, default=EXPECT_PATH)
    build.add_argument("--registries", type=Path, default=paths.REGISTRIES)
    build.add_argument("--md-dir", type=Path, default=paths.BIBLE_MD)
    build.add_argument("--canonical", type=Path, default=paths.CANONICAL)
    build.add_argument("--diff-expect", type=Path, default=DIFF_EXPECT_PATH)
    build.add_argument("--workers", type=int, default=8)
    build.add_argument("--report", type=Path)
    gate = sub.add_parser("gate", help="run the data gates of a stored layer")
    gate.add_argument("layer", choices=LAYERS)
    gate.add_argument("layer_dir", type=Path)
    gate.add_argument("--dep", type=Path, action="append", default=[],
                      help="directory of a layer this one depends on (repeatable)")
    gate.add_argument("--pdf-dir", type=Path, help="the PDFs, for G-XCHECK")
    gate.add_argument("--counts", type=Path, default=PDF_COUNTS_PATH)
    gate.add_argument("--source-expect", type=Path, default=EXPECT_PATH)
    gate.add_argument("--registries", type=Path, default=paths.REGISTRIES)
    gate.add_argument("--tokenizer", type=Path, help="BGE-M3 tokenizer.json (struct, emb)")
    gate.add_argument("--legacy-dir", type=Path, default=paths.LEGACY_OUTPUT,
                      help="the old output/, for G-ENC")
    _encoder_arguments(gate)
    gate.add_argument("--report", type=Path)
    det = sub.add_parser("det", help="G-DET: compare two runs of the same layer")
    det.add_argument("first", type=Path)
    det.add_argument("second", type=Path)
    det.add_argument("--report", type=Path)
    return parser


def _emit(doc: dict[str, Any], report: Path | None) -> None:
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if report is not None:
        report.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def _build_text(args: argparse.Namespace) -> stages.BuildResult:
    if args.pdf_dir is None or not args.pdf_dir.is_dir():
        raise CliError(f"--pdf-dir {args.pdf_dir} is not a directory")
    inputs = stages.TextInputs(registries=args.registries, md_dir=args.md_dir,
                               canonical=args.canonical, diff_expect=args.diff_expect)
    return stages.build(args.layer, args.pdf_dir, args.store, counts_path=args.counts,
                        expect_path=args.source_expect, workers=args.workers, inputs=inputs)


def _build_struct(args: argparse.Namespace) -> stages.BuildResult:
    if args.text is None or not args.text.is_dir():
        raise CliError(f"--text {args.text} is not a layer directory")
    inputs = struct_stage.StructInputs(legacy_dir=args.legacy_dir, tokenizer=args.tokenizer)
    return struct_stage.build_struct(args.text, args.store, counts_path=args.counts, inputs=inputs)


def _build_emb(args: argparse.Namespace) -> stages.BuildResult:
    for flag, value in (("--struct", args.struct), ("--text", args.text)):
        if value is None:
            raise CliError(f"build emb needs {flag}")
    inputs = emb_stage.EmbInputs(tokenizer=args.tokenizer,
                                 reranker_tokenizer=args.reranker_tokenizer,
                                 legacy_dir=args.legacy_dir, device=args.device)
    return emb_stage.build_emb(args.struct, args.text, args.store, counts_path=args.counts,
                               inputs=inputs)


def _build(args: argparse.Namespace) -> int:
    builders = {"text": _build_text, "struct": _build_struct, "emb": _build_emb}
    result = builders[args.layer](args)
    _emit(result.to_json(), args.report)
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


def _gate(args: argparse.Namespace) -> int:
    inputs = GateInputs(pdf_dir=args.pdf_dir, registries=args.registries,
                        source_expect=args.source_expect, tokenizer=args.tokenizer,
                        reranker_tokenizer=args.reranker_tokenizer, legacy_dir=args.legacy_dir,
                        device=args.device)
    report = gate_layer(args.layer_dir, args.layer, args.dep, args.counts, inputs=inputs)
    _emit(report.to_json(), args.report)
    return EXIT_OK if report.passed else EXIT_GATE_FAILED


def _det(args: argparse.Namespace) -> int:
    result = check_det(args.first, args.second)
    _emit(result.to_json(), args.report)
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


HANDLED = (CliError, CountsError, GateInputError, StoreError, StageError, OSError,
           yaml.YAMLError)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handler = {"build": _build, "gate": _gate, "det": _det}[args.command]
    try:
        return handler(args)
    except HANDLED as exc:
        sys.stderr.write(f"ragdata {args.command}: {exc}\n")
        return EXIT_ERROR
    except Exception:  # noqa: BLE001 - any other exception is a bug, reported as such
        sys.stderr.write(f"ragdata {args.command}: internal error\n{traceback.format_exc()}")
        return EXIT_INTERNAL

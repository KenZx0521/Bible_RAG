"""Command line for the snapshot pipeline.

    python -m ragdata build text --pdf-dir bible_pdf [--store DIR]
    python -m ragdata gate {text,struct} LAYER_DIR [--dep DIR ...] [--counts YAML] [--report FILE]
    python -m ragdata det FIRST_DIR SECOND_DIR [--report FILE]

Reports are JSON on stdout (and in ``--report`` when given). Exit status:
0 everything passed, 1 a hard gate failed, 2 bad input or a stage that does
not exist yet, 3 an internal error (a bug: the traceback goes to stderr, and no
report is written, so a crash is never mistaken for a gate result).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Sequence

import yaml

from ragdata import stages
from ragdata.contract import LAYERS
from ragdata.contract.counts import PDF_COUNTS_PATH, CountsError
from ragdata.gates import check_det
from ragdata.gates.runner import GateInputError, gate_layer
from ragdata.store import DEFAULT_ROOT, StoreError

EXIT_OK, EXIT_GATE_FAILED, EXIT_ERROR, EXIT_INTERNAL = 0, 1, 2, 3


class CliError(ValueError):
    """Bad command-line input."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragdata", description="Bible_RAG snapshot pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build a layer from the PDFs into the store")
    build.add_argument("layer", choices=stages.BUILDABLE)
    build.add_argument("--pdf-dir", type=Path, required=True)
    build.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    gate = sub.add_parser("gate", help="run the data gates of a stored layer")
    gate.add_argument("layer", choices=LAYERS)
    gate.add_argument("layer_dir", type=Path)
    gate.add_argument("--dep", type=Path, action="append", default=[],
                      help="directory of a layer this one depends on (repeatable)")
    gate.add_argument("--counts", type=Path, default=PDF_COUNTS_PATH)
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


def _build(args: argparse.Namespace) -> int:
    if not args.pdf_dir.is_dir():
        raise CliError(f"--pdf-dir {args.pdf_dir} is not a directory")
    stored = stages.build(args.layer, pdf_dir=args.pdf_dir, store_root=args.store)
    _emit({"layer": stored.layer, "layer_version": stored.version, "path": str(stored.path)}, None)
    return EXIT_OK


def _gate(args: argparse.Namespace) -> int:
    report = gate_layer(args.layer_dir, args.layer, args.dep, args.counts)
    _emit(report.to_json(), args.report)
    return EXIT_OK if report.passed else EXIT_GATE_FAILED


def _det(args: argparse.Namespace) -> int:
    result = check_det(args.first, args.second)
    _emit(result.to_json(), args.report)
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


HANDLED = (CliError, CountsError, GateInputError, StoreError, stages.StageNotImplementedError,
           OSError, yaml.YAMLError)


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

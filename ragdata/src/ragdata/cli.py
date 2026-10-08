"""Command line for the snapshot pipeline.

    python -m ragdata pipeline run [--date YYYYMMDD] [--load] [--verify] [--device DEV]
                                 [--store DIR] [--releases DIR] [--report FILE]
        every layer from the PDFs, gated, then the release (and load, verify) in one
        run; it stops at the first red gate (see ragdata.pipeline and
        docs/rebuild_pipeline.md). The commands below run one stage each.

    python -m ragdata build text --pdf-dir bible_pdf [--store DIR] [--counts YAML]
                                 [--source-expect YAML] [--registries DIR] [--md-dir DIR]
                                 [--canonical JSONL] [--diff-expect YAML] [--workers N]
                                 [--report FILE]
    python -m ragdata build struct --text TEXT_LAYER_DIR [--store DIR] [--counts YAML]
                                 [--legacy-dir DIR] [--tokenizer FILE] [--report FILE]
    python -m ragdata build emb --struct STRUCT_LAYER_DIR --text TEXT_LAYER_DIR [--store DIR]
                                 [--counts YAML] [--legacy-dir DIR] [--tokenizer FILE]
                                 [--reranker-tokenizer FILE] [--device DEV] [--report FILE]
    python -m ragdata build kg0 --text DIR --struct DIR [--registries DIR] [--kg0-counts YAML]
    python -m ragdata build events --text DIR --struct DIR [--events-yaml YAML]
                                 [--legacy-registry JSON] [--counts YAML]
    python -m ragdata build route --text DIR [--lexicon JSON] [--ground-truth JSON]
                                 [--backend-python PY] [--backend-dir DIR] [--counts YAML]
    python -m ragdata gate LAYER LAYER_DIR [--dep DIR ...] [--pdf-dir DIR] [--counts YAML]
                                 [--source-expect YAML] [--registries DIR] [--tokenizer FILE]
                                 [--reranker-tokenizer FILE] [--legacy-dir DIR] [--device DEV]
                                 [--kg0-counts YAML] [--legacy-registry JSON] [--lexicon JSON]
                                 [--ground-truth JSON] [--backend-python PY] [--backend-dir DIR]
                                 [--report FILE]
    python -m ragdata det FIRST_DIR SECOND_DIR [--report FILE]
    python -m ragdata gt {build,gate} ...   (GT v2; see ragdata.gt.cli)
    python -m ragdata release VERSION... [--store DIR] [--releases DIR] [--date YYYYMMDD]
                                 [--tokenizer F]
    python -m ragdata load RELEASE_JSON --slot inactive [--store DIR] [--contracts DIR]
                                 [--env-file F] [--tokenizer F]
    python -m ragdata verify RELEASE_JSON [--store DIR] [--contracts DIR] [--env-file F]
                                 [--tokenizer F] [--gt F] [--freeze F] [--device DEV]
                                 [--sample N] [--report F]
    python -m ragdata unload BUILD_ID [--contracts DIR] [--env-file F]
    python -m ragdata promote --env staging|prod --build BUILD_ID --image IMAGE_REF
                                 [--yes-prod] [--env-file F]
    python -m ragdata promote --env staging|prod --rollback [--yes-prod] [--env-file F]

DAG-external tools that write a registry or an expectation file (never run by a build):

    python -m ragdata expect kg0 --text DIR --struct DIR [--registries DIR] [--out YAML]
    python -m ragdata convert events --text DIR --struct DIR [--legacy-registry JSON] [--out YAML]
    python -m ragdata freeze route [--backend-python PY] [--backend-dir DIR] [--out JSON]

A text layer is gated with its src layer as a dependency (G-CONSERVE re-reads
it) and the PDFs (G-XCHECK re-reads them); without them those gates fail closed.
A struct layer is built from, and gated with, its text layer; G-STRUCT counts
tokens with the pinned BGE-M3 tokenizer (the HF cache, or ``--tokenizer``) and
fails closed when it does not load. An emb layer is built from a struct layer and
the text layer it was built on, and gated with both (``--dep``); its build and
G-EMB/G-ENC load the pinned BGE-M3 offline (and the reranker tokenizer), and
G-ENC compares the vectors with the old ``output/`` (``--legacy-dir``). ``gate emb``
on cuda encodes every record again (about a minute in all); with ``--device cpu``
it encodes a sample and reports ``sampled: true``. ``det`` on two emb layers also
compares their vectors and probe vectors within G-DET's tolerance. kg0 and events
are built from, and gated with, text and struct; route with text. G-ROUTE runs the backend's live matcher
with ``--backend-python`` (the backend venv) and fails closed without it.
``release``, ``load`` and ``verify`` gate every layer of the release again (all but
G-ENC, G-ROUTE, G-CONSERVE and G-XCHECK) and refuse it (status 2) when one is red.

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
from typing import Any, Callable, Sequence

import yaml

from ragdata import paths, stages
from ragdata.contract import LAYERS
from ragdata.contract.counts import KG0_COUNTS_PATH, PDF_COUNTS_PATH, CountsError
from ragdata.gates import check_det
from ragdata.gates.diff import EXPECT_PATH as DIFF_EXPECT_PATH
from ragdata.gates.runner import GateInputError, GateInputs, gate_layer
from ragdata.kg import k0_build, k1_build, k4_build, k4_route
from ragdata.loader import cli as loader_cli
from ragdata.loader.config import ConfigError
from ragdata.loader.plan import LoaderError
from ragdata.pipeline import cli as pipeline_cli
from ragdata.pipeline.run import GATE
from ragdata.gt import cli as gt_cli
from ragdata.gt.errors import GT_ERRORS
from ragdata.release import cli as release_cli
from ragdata.release.assemble import ReleaseError
from ragdata.stages.errors import StageError
from ragdata.stages.s05_struct import build as struct_stage
from ragdata.stages.s06_emb import build as emb_stage
from ragdata.stages.s00_source import EXPECT_PATH
from ragdata.store import DEFAULT_ROOT, StoreError

EXIT_OK, EXIT_GATE_FAILED, EXIT_ERROR, EXIT_INTERNAL = 0, 1, 2, 3
KG0_COUNTS_HEADER = ("# 由 `python -m ragdata expect kg0` 從定版 text／struct 層與 K0 註冊表算出，"
                     "G-KG0 逐項比對；不要手改。\n")


class CliError(ValueError):
    """Bad command-line input."""


def _encoder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reranker-tokenizer", type=Path, default=paths.RERANKER_TOKENIZER,
                        help="bge-reranker-v2-m3 tokenizer.json (emb)")
    parser.add_argument("--device", help="where BGE-M3 runs (emb; default cuda if available)")


def _kg_inputs(parser: argparse.ArgumentParser) -> None:
    """Options the KG builds and gates share."""
    parser.add_argument("--kg0-counts", type=Path, default=KG0_COUNTS_PATH)
    parser.add_argument("--events-yaml", type=Path, default=paths.EVENTS_REGISTRY)
    parser.add_argument("--legacy-registry", type=Path, default=paths.LEGACY_EVENT_REGISTRY)
    parser.add_argument("--lexicon", type=Path, default=paths.FROZEN_LEXICON)
    parser.add_argument("--ground-truth", type=Path, default=paths.GROUND_TRUTH)
    parser.add_argument("--backend-python", type=Path, default=paths.BACKEND_PYTHON)
    parser.add_argument("--backend-dir", type=Path, default=paths.BACKEND)


def _build_parser(sub: Any) -> None:
    build = sub.add_parser("build", help="build a layer into the store")
    build.add_argument("layer", choices=stages.BUILDABLE)
    build.add_argument("--pdf-dir", type=Path, help="the PDFs (text)")
    build.add_argument("--text", type=Path, help="the text layer to build on")
    build.add_argument("--struct", type=Path,
                       help="the struct layer to build on (emb, kg0, events)")
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
    _kg_inputs(build)


def _gate_parser(sub: Any) -> None:
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
    _kg_inputs(gate)


def _tool_parsers(sub: Any) -> None:
    expect = sub.add_parser("expect", help="write the kg0 expectation file (outside the DAG)")
    expect.add_argument("layer", choices=("kg0",))
    expect.add_argument("--text", type=Path, required=True)
    expect.add_argument("--struct", type=Path, required=True)
    expect.add_argument("--registries", type=Path, default=paths.REGISTRIES)
    expect.add_argument("--out", type=Path, default=KG0_COUNTS_PATH)
    convert = sub.add_parser("convert", help="convert the legacy event registry (outside the DAG)")
    convert.add_argument("what", choices=("events",))
    convert.add_argument("--text", type=Path, required=True)
    convert.add_argument("--struct", type=Path, required=True)
    convert.add_argument("--legacy-registry", type=Path, default=paths.LEGACY_EVENT_REGISTRY)
    convert.add_argument("--out", type=Path, default=paths.EVENTS_REGISTRY)
    freeze = sub.add_parser("freeze", help="freeze the backend routing lexicon (outside the DAG)")
    freeze.add_argument("what", choices=("route",))
    freeze.add_argument("--backend-python", type=Path, default=paths.BACKEND_PYTHON)
    freeze.add_argument("--backend-dir", type=Path, default=paths.BACKEND)
    freeze.add_argument("--out", type=Path, default=paths.FROZEN_LEXICON)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragdata", description="Bible_RAG snapshot pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    _build_parser(sub)
    _gate_parser(sub)
    det = sub.add_parser("det", help="G-DET: compare two runs of the same layer")
    det.add_argument("first", type=Path)
    det.add_argument("second", type=Path)
    det.add_argument("--report", type=Path)
    _tool_parsers(sub)
    gt_cli.add_parser(sub)
    release_cli.add_parser(sub)
    pipeline_cli.add_parser(sub)
    loader_cli.add_parsers(sub)
    return parser


def _emit(doc: dict[str, Any], report: Path | None) -> None:
    text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if report is not None:
        report.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def _need_dir(value: Path | None, option: str) -> Path:
    if value is None or not value.is_dir():
        raise CliError(f"{option} {value} is not a directory")
    return value


def _build_text(args: argparse.Namespace) -> stages.BuildResult:
    _need_dir(args.pdf_dir, "--pdf-dir")
    inputs = stages.TextInputs(registries=args.registries, md_dir=args.md_dir,
                               canonical=args.canonical, diff_expect=args.diff_expect)
    return stages.build(args.layer, args.pdf_dir, args.store, counts_path=args.counts,
                        expect_path=args.source_expect, workers=args.workers, inputs=inputs)


def _build_struct(args: argparse.Namespace) -> stages.BuildResult:
    inputs = struct_stage.StructInputs(legacy_dir=args.legacy_dir, tokenizer=args.tokenizer)
    return struct_stage.build_struct(_need_dir(args.text, "--text"), args.store,
                                     counts_path=args.counts, inputs=inputs)


def _build_emb(args: argparse.Namespace) -> stages.BuildResult:
    for flag, value in (("--struct", args.struct), ("--text", args.text)):
        if value is None:
            raise CliError(f"build emb needs {flag}")
    inputs = emb_stage.EmbInputs(tokenizer=args.tokenizer,
                                 reranker_tokenizer=args.reranker_tokenizer,
                                 legacy_dir=args.legacy_dir, device=args.device)
    return emb_stage.build_emb(args.struct, args.text, args.store, counts_path=args.counts,
                               inputs=inputs)


def _build_kg0(args: argparse.Namespace) -> stages.BuildResult:
    return k0_build.build_kg0(_need_dir(args.text, "--text"), _need_dir(args.struct, "--struct"),
                              args.store, args.registries, args.kg0_counts)


def _build_events(args: argparse.Namespace) -> stages.BuildResult:
    return k1_build.build_events(_need_dir(args.text, "--text"), _need_dir(args.struct, "--struct"),
                                 args.store, args.events_yaml, args.legacy_registry, args.counts)


def _build_route(args: argparse.Namespace) -> stages.BuildResult:
    live = k4_route.subprocess_probe(args.backend_python, args.backend_dir)
    return k4_build.build_route(_need_dir(args.text, "--text"), args.store, live, args.lexicon,
                                args.ground_truth, args.counts)


BUILDERS: dict[str, Callable[[argparse.Namespace], stages.BuildResult]] = {
    "text": _build_text, "struct": _build_struct, "emb": _build_emb, "kg0": _build_kg0,
    "events": _build_events, "route": _build_route,
}


def _build(args: argparse.Namespace) -> int:
    if args.layer not in BUILDERS:
        raise CliError(f"no build for layer {args.layer!r} yet")
    result = BUILDERS[args.layer](args)
    _emit(result.to_json(), args.report)
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


def gate_inputs(args: argparse.Namespace) -> GateInputs:
    return GateInputs(pdf_dir=args.pdf_dir, registries=args.registries,
                      source_expect=args.source_expect, tokenizer=args.tokenizer,
                      reranker_tokenizer=args.reranker_tokenizer, legacy_dir=args.legacy_dir,
                      device=args.device, kg0_counts=args.kg0_counts, legacy_registry=args.legacy_registry,
                      frozen_lexicon=args.lexicon, ground_truth=args.ground_truth,
                      backend_python=args.backend_python, backend_dir=args.backend_dir)


def _gate(args: argparse.Namespace) -> int:
    report = gate_layer(args.layer_dir, args.layer, args.dep, args.counts,
                        inputs=gate_inputs(args))
    _emit(report.to_json(), args.report)
    return EXIT_OK if report.passed else EXIT_GATE_FAILED


def _det(args: argparse.Namespace) -> int:
    result = check_det(args.first, args.second)
    _emit(result.to_json(), args.report)
    return EXIT_OK if result.passed else EXIT_GATE_FAILED


def _expect(args: argparse.Namespace) -> int:
    doc = k0_build.expected_counts(_need_dir(args.text, "--text"),
                                   _need_dir(args.struct, "--struct"), args.registries)
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    args.out.write_text(KG0_COUNTS_HEADER + body, encoding="utf-8")
    _emit({"written": str(args.out), "names": doc["names"],
           "parallel_links": doc["parallel_links"],
           "extra_spans": {k: v["total"] for k, v in doc["extra_spans"].items()}}, None)
    return EXIT_OK


def _convert(args: argparse.Namespace) -> int:
    text = k1_build.convert(_need_dir(args.text, "--text"), _need_dir(args.struct, "--struct"),
                            args.legacy_registry)
    args.out.write_text(text, encoding="utf-8")
    _emit({"written": str(args.out), "from": str(args.legacy_registry)}, None)
    return EXIT_OK


def _freeze(args: argparse.Namespace) -> int:
    """Run ragdata.legacy.route_live freeze in the backend venv (it imports entity_dicts)."""
    if not args.backend_python.is_file():
        raise CliError(f"--backend-python {args.backend_python} is not a file")
    k4_route.run_live(args.backend_python, ["freeze", "--backend-dir", str(args.backend_dir),
                                            "--out", str(args.out)])
    _emit({"written": str(args.out), "backend": str(args.backend_dir)}, None)
    return EXIT_OK


def _gt(args: argparse.Namespace) -> int:
    report = gt_cli.run(args)
    _emit(report.to_json(), getattr(args, "report", None))
    return EXIT_OK if report.passed else EXIT_GATE_FAILED


def _release(args: argparse.Namespace) -> int:
    _emit(release_cli.run(args), None)
    return EXIT_OK


def _load(args: argparse.Namespace) -> int:
    _emit(loader_cli.run_load(args), None)
    return EXIT_OK


def _pipeline(args: argparse.Namespace) -> int:
    report = pipeline_cli.run_pipeline(args)
    _emit(report.to_json(), args.report)
    if report.stop is None:
        return EXIT_OK
    sys.stderr.write(pipeline_cli.describe(report.stop))
    return EXIT_GATE_FAILED if report.stop.kind == GATE else EXIT_ERROR


def _unload(args: argparse.Namespace) -> int:
    _emit(loader_cli.run_unload(args), None)
    return EXIT_OK


def _promote(args: argparse.Namespace) -> int:
    _emit(loader_cli.run_promote(args), None)
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    report = loader_cli.run_verify(args)
    _emit(report.to_json(), args.report)
    return EXIT_OK if report.passed else EXIT_GATE_FAILED


HANDLED = (CliError, CountsError, GateInputError, StoreError, StageError, OSError,
           yaml.YAMLError, json.JSONDecodeError, ReleaseError, LoaderError, ConfigError,
           *GT_ERRORS)
COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "build": _build, "gate": _gate, "det": _det, "expect": _expect, "convert": _convert,
    "freeze": _freeze, "gt": _gt, "release": _release, "load": _load, "verify": _verify,
    "unload": _unload, "promote": _promote, "pipeline": _pipeline,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except HANDLED as exc:
        sys.stderr.write(f"ragdata {args.command}: {exc}\n")
        return EXIT_ERROR
    except Exception:  # noqa: BLE001 - any other exception is a bug, reported as such
        sys.stderr.write(f"ragdata {args.command}: internal error\n{traceback.format_exc()}")
        return EXIT_INTERNAL

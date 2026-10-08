"""``python -m ragdata gt build|gate``.

    gt build --text-layer DIR [--v1 F] [--curated F] [--out F] [--changes F] [--freeze F]
    gt gate  [GT_V2] [--store DIR | --text-layer DIR] [--v1 F] [--changes F] [--freeze F]
             [--report F]

``build`` writes ground_truth.v2.json, the change log and the freeze record,
then gates them. It refuses to run unless the generator (ragdata/src/ragdata/gt,
packages/ragcommon) and the curated file are committed, so the git sha in the
header names the code that made the file. ``gate`` re-reads everything from
disk; the text layer defaults to the header's slot_universe in the store.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from ragcommon.versification import Versification, default_versification
from ragdata import paths
from ragdata.gt.build import BuildResult, Provenance, build_v2, encode_doc, sha256
from ragdata.gt.changes import change_from_json
from ragdata.gt.corpus import ServiceText
from ragdata.gt.curated import load_curated
from ragdata.gt.gate import GtInputs, GtReport, check_gt, freeze_record
from ragdata.store import DEFAULT_ROOT, decode_jsonl, read_layer

GOLD = paths.REPO / "config" / "gold"
DEFAULTS = {"v1": paths.REPO / "ground_truth.json", "out": paths.REPO / "ground_truth.v2.json",
            "curated": GOLD / "gt_v2_curated.yaml", "changes": GOLD / "gt_v2_changes.jsonl",
            "freeze": GOLD / "gt_v2_freeze.json"}
GENERATOR = ("ragdata/src/ragdata/gt", "packages/ragcommon")
COMMAND = "python -m ragdata gt build"
SCRIPT = "ragdata/src/ragdata/gt/build.py"


class GtCliError(ValueError):
    """Bad input to ``ragdata gt``."""


def add_parser(sub: argparse._SubParsersAction) -> None:
    gt = sub.add_parser("gt", help="build or gate GT v2 (ground_truth.v2.json)")
    actions = gt.add_subparsers(dest="gt_command", required=True)
    build = actions.add_parser("build", help="derive GT v2 from v1 and a text layer")
    build.add_argument("--text-layer", type=Path, required=True)
    gate = actions.add_parser("gate", help="run G-GT")
    gate.add_argument("gt", type=Path, nargs="?", default=DEFAULTS["out"])
    gate.add_argument("--text-layer", type=Path)
    gate.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    gate.add_argument("--report", type=Path)
    for parser in (build, gate):
        parser.add_argument("--v1", type=Path, default=DEFAULTS["v1"])
        parser.add_argument("--changes", type=Path, default=DEFAULTS["changes"])
        parser.add_argument("--freeze", type=Path, default=DEFAULTS["freeze"])
    build.add_argument("--curated", type=Path, default=DEFAULTS["curated"])
    build.add_argument("--out", type=Path, default=DEFAULTS["out"])


def _rel(path: Path, repo: Path = paths.REPO) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise GtCliError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def git_provenance(repo: Path, tracked: tuple[str, ...]) -> dict[str, Any]:
    """HEAD and the tree/blob sha of each tracked path; refuse uncommitted changes there."""
    dirty = _git(repo, "status", "--porcelain", "--", *tracked)
    if dirty:
        raise GtCliError(f"commit these before building GT v2:\n{dirty}")
    return {"script": SCRIPT, "command": COMMAND, "git_sha": _git(repo, "rev-parse", "HEAD"),
            "files": {p: _git(repo, "rev-parse", f"HEAD:{p}") for p in tracked}}


def versification_for(layer_version: str) -> Versification:
    vers = default_versification()
    if vers.source.get("layer_version") != layer_version:
        raise GtCliError(f"ragcommon versification is from {vers.source.get('layer_version')}, "
                         f"not {layer_version}")
    return vers


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build(args: argparse.Namespace) -> tuple[BuildResult, bytes, bytes]:
    layer = read_layer(args.text_layer)
    corpus = ServiceText.from_layer(layer)
    v1_bytes = args.v1.read_bytes()
    curated_rel = _rel(args.curated)
    generator = git_provenance(paths.REPO, (*GENERATOR, curated_rel))
    prov = Provenance(v1={"path": _rel(args.v1), "sha256": sha256(v1_bytes)},
                      generator=generator,
                      curated={"path": curated_rel, "sha256": sha256(args.curated.read_bytes())},
                      changes_path=_rel(args.changes))
    result = build_v2(json.loads(v1_bytes), corpus, versification_for(layer.version),
                      load_curated(args.curated), prov)
    return result, encode_doc(result.doc), v1_bytes


def run_build(args: argparse.Namespace) -> GtReport:
    result, v2_bytes, _ = _build(args)
    freeze = freeze_record(result.doc, v2_bytes)
    _write(args.out, v2_bytes)
    _write(args.changes, result.changes_bytes)
    _write(args.freeze, (json.dumps(freeze, ensure_ascii=False, indent=2) + "\n").encode())
    return gate_files(args.out, args.text_layer, args.v1, args.changes, args.freeze)


def gate_files(gt: Path, text_layer: Path, v1: Path, changes: Path, freeze: Path) -> GtReport:
    v2_bytes, v1_bytes, log = gt.read_bytes(), v1.read_bytes(), changes.read_bytes()
    layer = read_layer(text_layer)
    return check_gt(GtInputs(
        doc=json.loads(v2_bytes), corpus=ServiceText.from_layer(layer),
        vers=versification_for(layer.version), v1_doc=json.loads(v1_bytes),
        v1_sha256=sha256(v1_bytes),
        changes=tuple(change_from_json(r) for r in decode_jsonl(log, changes.name)),
        changes_sha256=sha256(log), freeze=json.loads(freeze.read_text(encoding="utf-8")),
        v2_sha256=sha256(v2_bytes)))


def run_gate(args: argparse.Namespace) -> GtReport:
    text_layer = args.text_layer
    if text_layer is None:
        universe = json.loads(args.gt.read_bytes())["metadata"].get("slot_universe")
        if not universe:
            raise GtCliError(f"{args.gt} declares no slot_universe; pass --text-layer")
        text_layer = args.store / "text" / universe
    return gate_files(args.gt, text_layer, args.v1, args.changes, args.freeze)


def run(args: argparse.Namespace) -> GtReport:
    return {"build": run_build, "gate": run_gate}[args.gt_command](args)

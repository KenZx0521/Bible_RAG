"""``python -m ragdata pipeline run [--date YYYYMMDD] [--load] [--verify] [--device DEV]
[--store DIR] [--releases DIR] [--report F]``.

Runs ``pipeline.run`` over the repository's inputs: the PDFs in bible_pdf/, the
registries and expectations, the old output/, the pinned models (offline), the backend
venv for G-ROUTE. ``--load`` writes the release to PG, Qdrant and ``contracts/`` (a new
namespace; a build already registered with this release is not loaded again) and
``--verify`` runs G-PROJ over it; both connect with the repository's ``.env``. Without
``--date`` the build date is the commit date of HEAD, so a rerun on the same commit names
the same build.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable, Mapping

from ragdata import paths
from ragdata.gates.runner import GateInputs
from ragdata.loader import cli as loader_cli
from ragdata.loader.load import load
from ragdata.loader.verify import VerifyInputs, verify
from ragdata.pipeline import derived
from ragdata.pipeline.run import Databases, Pipeline, PipelineReport, Stop, run
from ragdata.pipeline.steps import Built, Sources, layer_steps
from ragdata.release import assemble as rel
from ragdata.release.gating import ReleaseChecks
from ragdata.store import DEFAULT_ROOT
from ragdata.store.cas import sha256_bytes


def add_parser(sub: argparse._SubParsersAction) -> None:
    pipeline = sub.add_parser("pipeline", help="PDF to release (to load and verify) in one run")
    actions = pipeline.add_subparsers(dest="pipeline_command", required=True)
    go = actions.add_parser("run", help="build, gate, release; --load, --verify")
    go.add_argument("--date", help="YYYYMMDD build date (default: the commit date of HEAD)")
    go.add_argument("--load", action="store_true", help="load the release (new namespace)")
    go.add_argument("--verify", action="store_true", help="G-PROJ over the loaded release")
    go.add_argument("--device", help="where BGE-M3 runs (default cuda if available)")
    go.add_argument("--store", type=Path, default=DEFAULT_ROOT)
    go.add_argument("--releases", type=Path, default=paths.RELEASES)
    go.add_argument("--report", type=Path)


def release_step(store: Path, releases: Path, date: str,
                 checks: ReleaseChecks) -> Callable[[Built], tuple[rel.Release, bool]]:
    """S12 over the built layers; the release and whether its file was there already."""
    def assemble(built: Built) -> tuple[rel.Release, bool]:
        release = rel.assemble(store, [built[k].version for k in rel.CORE], date, checks)
        existed = (Path(releases) / f"{release.build_id}.json").exists()
        rel.write_release(release, releases)
        return release, existed
    return assemble


def load_once(contracts: Path) -> Callable[[rel.Release, Any, Any], Mapping[str, Any]]:
    """S13, unless ``rag_meta.builds`` already holds this very release (then it is reused)."""
    def load_release(release: rel.Release, pg: Any, qdrant: Any) -> Mapping[str, Any]:
        row = pg.build_row(release.build_id)
        if row is not None and row.get("manifest_sha") == sha256_bytes(release.data):
            return {"build_id": release.build_id, "reused": True}
        return {**load(release, pg, qdrant, contracts), "reused": False}
    return load_release


def _databases(args: argparse.Namespace) -> Databases | None:
    if not (args.load or args.verify):
        return None
    inputs = VerifyInputs(device=args.device)
    return Databases(
        connect=lambda: loader_cli.connect(loader_cli.environment(paths.REPO / ".env")),
        load=load_once(paths.CONTRACTS) if args.load else None,
        verify=(lambda release, pg, qdrant: verify(release, pg, qdrant, paths.CONTRACTS, inputs))
        if args.verify else None)


def default_pipeline(args: argparse.Namespace) -> Pipeline:
    sources = Sources(gate=GateInputs(pdf_dir=paths.PDF_DIR, device=args.device))
    files = derived.DerivedFiles()
    date = args.date or rel.git_date(paths.REPO)
    checks = ReleaseChecks(sources.counts, sources.gate)
    return Pipeline(args.store, layer_steps(args.store, sources), files,
                    lambda built: derived.gt_report(built, files),
                    release_step(args.store, args.releases, date, checks), _databases(args))


def describe(stop: Stop) -> str:
    """What stderr says when a run stops: where, which gates, and what to run."""
    where = stop.where + (f" ({stop.version})" if stop.version else "")
    lines = [f"ragdata pipeline: stopped at {where}:", *(f"  {r}" for r in stop.red)]
    if stop.commands:
        lines += ["run, in order:", *(f"  {n}. {c}" for n, c in enumerate(stop.commands, 1))]
    return "\n".join(lines) + "\n"


def run_pipeline(args: argparse.Namespace) -> PipelineReport:
    return run(default_pipeline(args))

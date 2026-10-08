"""``ragdata pipeline run``: from the PDFs to a release, and optionally loaded and verified.

Order: text (with src), struct, the derived-file check and G-GT, emb, kg0, events, route,
then the release (S12), ``load`` into a new namespace (S13) and ``verify`` (S14, G-PROJ).
Each layer is built and stored only when its build gates pass, then gated again with
every gate it requires (``steps``). The first red gate, stale derived file or bad input
stops the run: nothing after it runs, and the report names the step and the gates.

A layer whose build gives a version the store already holds is that version (the store
is content addressed and never rewrites one); the report marks it ``reused``. So a second
run over the same inputs gives the same layers, the same release and the same build id,
and a build already registered in ``rag_meta.builds`` with this release is not loaded
again. For G-DET the report keeps every layer's file sha256s (and the emb vectors'), so two
runs compare file by file; a rebuilt emb version keeps its stored vectors only if this
run's are within G-DET's tolerance of them (``s06_emb.build``).
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Sequence

import yaml

from ragdata.contract.counts import CountsError
from ragdata.gates.base import GateInputError, GateResult
from ragdata.gt.errors import GT_ERRORS
from ragdata.loader.config import ConfigError
from ragdata.loader.plan import LoaderError
from ragdata.pipeline import derived
from ragdata.pipeline.steps import Built, Step
from ragdata.release.assemble import Release, ReleaseError
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult
from ragdata.store import MANIFEST, StoreError, StoredLayer, attach, vectors

REPORT_SCHEMA = "ragdata.pipeline_report.v1"
GATE, INPUT = "gate", "input"           # a red gate; bad input (or stale derived files)
CHECK_AFTER = "struct"                  # the derived files name text and struct
INPUT_ERRORS = (StageError, StoreError, GateInputError, CountsError, ReleaseError, LoaderError,
                ConfigError, derived.DerivedError, OSError, yaml.YAMLError,
                json.JSONDecodeError, *GT_ERRORS)


class Stop(Exception):
    """The run stops at ``where`` (a layer, or a later step) for the ``red`` reasons."""

    def __init__(self, where: str, red: Sequence[str], kind: str = GATE,
                 commands: Sequence[str] = (), version: str | None = None) -> None:
        super().__init__(f"{where}: {'; '.join(red)}")
        self.where, self.red, self.kind = where, tuple(red), kind
        self.commands, self.version = tuple(commands), version

    def with_commands(self, commands: Sequence[str]) -> "Stop":
        return Stop(self.where, self.red, self.kind, commands, self.version)

    def to_json(self) -> dict[str, Any]:
        return {"at": self.where, "version": self.version, "kind": self.kind,
                "red": list(self.red), "commands": list(self.commands)}


@dataclass(frozen=True)
class Databases:
    """Where ``load`` and ``verify`` go: ``connect()`` gives (pg, qdrant)."""

    connect: Callable[[], tuple[Any, Any]]
    load: Callable[[Release, Any, Any], Mapping[str, Any]] | None
    verify: Callable[[Release, Any, Any], Any] | None


@dataclass(frozen=True)
class Pipeline:
    store: Path
    steps: tuple[Step, ...]
    files: derived.DerivedFiles
    gt: Callable[[Built], Any]                              # G-GT report (``passed``, gates)
    release: Callable[[Built], tuple[Release, bool]]        # the release, and was it written
    databases: Databases | None = None


@dataclass(frozen=True)
class PipelineReport:
    doc: Mapping[str, Any]
    stop: Stop | None

    @property
    def passed(self) -> bool:
        return self.stop is None

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "pass": self.passed,
                "stopped": None if self.stop is None else self.stop.to_json(), **self.doc}


def red_of(gates: Sequence[GateResult], missing: Sequence[str] = ()) -> list[str]:
    """``{gate}: {first details}`` for every red hard gate, and every required gate not run."""
    red = [f"{g.name}: {list(g.details[:3])}" for g in gates if g.hard and not g.passed]
    return red + [f"{name}: not run" for name in missing]


@contextmanager
def phase(where: str) -> Iterator[None]:
    """Turn bad input met in ``where`` into a stop there."""
    try:
        yield
    except Stop:
        raise
    except INPUT_ERRORS as exc:
        raise Stop(where, [f"{type(exc).__name__}: {exc}"], INPUT) from exc


def _versions(store: Path) -> frozenset[str]:
    store = Path(store)
    return frozenset(p.name for layer in store.iterdir() if layer.is_dir()
                     for p in layer.iterdir()) if store.is_dir() else frozenset()


def _files(layer: StoredLayer) -> dict[str, Any]:
    entry: dict[str, Any] = {"files": json.loads((layer.path / MANIFEST).read_text())["files"]}
    if layer.layer == "emb":
        entry["vectors"] = dict(attach.read_attachment(layer.path, vectors.NAME)[0].file_shas)
    return entry


def _summary(gates: Sequence[GateResult]) -> dict[str, bool]:
    return {g.name: g.passed for g in gates}


def _build(step: Step, built: Built, store: Path, doc: dict[str, Any]) -> Built:
    """Build one layer; record it (and src, for text) in ``doc``; the layers built so far."""
    with phase(step.layer):
        before = _versions(store)
        result: BuildResult = step.build(built)
        if not result.passed:
            raise Stop(step.layer, red_of(result.gates))
        for name, layer in result.layers.items():
            doc["layers"][name] = {"version": layer.version, "reused": layer.version in before,
                                   **_files(layer)}
    doc["layers"][step.layer]["build_gates"] = _summary(result.gates)
    return {**built, **result.layers}


def _gate(step: Step, built: Built, doc: dict[str, Any]) -> None:
    """Every gate the stored layer requires."""
    with phase(step.layer):
        report = step.gate(built)
    doc["layers"][step.layer]["gates"] = _summary(report.gates)
    if not report.passed:
        raise Stop(step.layer, red_of(report.gates, report.missing),
                   version=report.layer_version)


def _check_derived(p: Pipeline, built: Built, doc: dict[str, Any]) -> None:
    """The derived files name this run's text and struct layers, and GT v2 passes G-GT."""
    with phase("derived"):
        found = derived.stale(built, p.files)
    if found:
        raise Stop("derived", [s.line() for s in found], INPUT, derived.commands(built, found))
    with phase("gt"):
        report = p.gt(built)
    doc["gt"] = {"slot_universe": report.slot_universe, "gates": _summary(report.gates)}
    if not report.passed:
        raise Stop("gt", red_of(report.gates))


def _databases(dbs: Databases, release: Release, doc: dict[str, Any]) -> None:
    with phase("load"):
        pg, qdrant = dbs.connect()
    try:
        if dbs.load is not None:
            with phase("load"):
                doc["load"] = dict(dbs.load(release, pg, qdrant))
        if dbs.verify is not None:
            with phase("verify"):
                report = dbs.verify(release, pg, qdrant)
            doc["verify"] = {"pass": report.passed, "gates": _summary(report.gates)}
            if not report.passed:
                raise Stop("verify", red_of(report.gates))
    finally:
        pg.close()
        qdrant.close()


def _hints(p: Pipeline, built: Built) -> list[str]:
    """The commands for stale derived files, to print with any stop (they often explain it)."""
    try:
        return derived.commands(built, derived.stale(built, p.files))
    except INPUT_ERRORS as exc:
        return [f"(the derived files could not be checked: {exc})"]


def _release(p: Pipeline, built: Built, doc: dict[str, Any]) -> Release:
    with phase("release"):
        release, existed = p.release(built)
    doc["release"] = {"build_id": release.build_id, "release_sha": release.release_sha,
                      "existed": existed,
                      "layers": {k: v for k, v in release.doc["layers"].items() if v}}
    return release


def run(p: Pipeline) -> PipelineReport:
    doc: dict[str, Any] = {"layers": {}}
    built: Built = {}
    start = time.monotonic()
    try:
        for step in p.steps:
            built = _build(step, built, p.store, doc)
            _gate(step, built, doc)
            if step.layer == CHECK_AFTER:
                _check_derived(p, built, doc)
        release = _release(p, built, doc)
        if p.databases is not None:
            _databases(p.databases, release, doc)
        stop = None
    except Stop as exc:
        stop = exc if exc.commands else exc.with_commands(_hints(p, built))
    doc["elapsed_s"] = round(time.monotonic() - start, 1)
    return PipelineReport(MappingProxyType(doc), stop)

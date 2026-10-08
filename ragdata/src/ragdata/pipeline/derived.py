"""Committed files derived from the text and struct layers: are they this run's?

Three files in the repository name the layer they were made from, and a release over
another text or struct layer would contradict them:

- ``packages/ragcommon/data/versification.json`` (``source.layer_version``): the services'
  verse grid; G-REF compares its content, and ``gt build`` refuses a grid of another layer;
- ``expectations/kg0_counts.yaml`` (``inputs``): G-KG0 compares the kg0 layer with it;
- ``ground_truth.v2.json`` and ``config/gold/gt_v2_freeze.json`` (``slot_universe``): G-GT
  and G-PROJ C6 hold GT v2 to the release's text layer.

They are written by commands outside the DAG and reviewed and committed by a person (a
build writes neither config/ nor the expectations, and ``gt build`` records the commit of
its generator), so the pipeline never rewrites them: it stops and prints, in order, the
commands that do. ``gt_report`` runs G-GT once GT v2 names the text layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragcommon import versification
from ragdata import paths
from ragdata.contract.counts import KG0_COUNTS_PATH, load_kg0_counts
from ragdata.gt import cli as gt_cli
from ragdata.gt.gate import GtReport
from ragdata.store import StoredLayer

RAGDATA = "PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python -m ragdata"
DERIVE = ("scripts/.venv/bin/python scripts/derive_ragcommon_data.py versification "
          "--text-layer {text}")
Built = Mapping[str, StoredLayer]


class DerivedError(ValueError):
    """A derived file cannot be read as the document it should be."""


@dataclass(frozen=True)
class DerivedFiles:
    versification: Path = versification.DATA_PATH
    kg0_counts: Path = KG0_COUNTS_PATH
    gt: Path = paths.GT_V2
    freeze: Path = paths.GT_V2_FREEZE
    gt_v1: Path = paths.GROUND_TRUTH
    gt_changes: Path = field(default_factory=lambda: gt_cli.DEFAULTS["changes"])


@dataclass(frozen=True)
class Stale:
    what: str           # "versification", "kg0_counts" or "gt"
    path: Path
    names: Any          # the layer version(s) the file names
    wants: Any          # the version(s) of this run

    def line(self) -> str:
        return f"{self.path} names {self.names}, this run built {self.wants}"


def _field(path: Path, *keys: str) -> Any:
    """The value at ``keys`` of the JSON object in ``path`` (None where it has none)."""
    try:
        node: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DerivedError(f"{path}: unreadable: {exc}") from None
    if not isinstance(node, dict):
        raise DerivedError(f"{path}: not a JSON object")
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _versification(files: DerivedFiles, text: str) -> list[Stale]:
    found = _field(files.versification, "source", "layer_version")
    return [] if found == text else [Stale("versification", files.versification, found, text)]


def _gt(files: DerivedFiles, text: str) -> list[Stale]:
    found = (_field(files.gt, "metadata", "slot_universe"),
             _field(files.freeze, "slot_universe"))
    return [] if found == (text, text) else [Stale("gt", files.gt, list(found), text)]


def _kg0(files: DerivedFiles, text: str, struct: str) -> list[Stale]:
    found = dict(load_kg0_counts(files.kg0_counts)["inputs"])
    want = {"struct": struct, "text": text}
    return [] if found == want else [Stale("kg0_counts", files.kg0_counts, found, want)]


def stale(built: Built, files: DerivedFiles) -> list[Stale]:
    """The derived files that do not name the text (and struct) layer of ``built``."""
    if "text" not in built:
        return []
    text = built["text"].version
    found = _versification(files, text)
    if "struct" in built:
        found += _kg0(files, text, built["struct"].version)
    return found + _gt(files, text)


def commands(built: Built, found: Sequence[Stale]) -> list[str]:
    """What rewrites the stale files, in the order it must run, with the commits between."""
    if not found:
        return []
    what = {s.what for s in found}
    text = built["text"].path
    steps: list[str] = []
    if "versification" in what:
        steps += [DERIVE.format(text=text),
                  "git add packages/ragcommon/data && git commit  "
                  "(gt build refuses an uncommitted ragcommon)"]
    if "kg0_counts" in what:
        steps.append(f"{RAGDATA} expect kg0 --text {text} --struct {built['struct'].path}  "
                     "(review the diff: only what this run changed may move)")
    if "gt" in what:
        steps.append(f"{RAGDATA} gt build --text-layer {text}")
    return steps + ["git add the rewritten files && git commit",
                    f"{RAGDATA} pipeline run ...  (again; finished layers are reused)"]


def gt_report(built: Built, files: DerivedFiles) -> GtReport:
    """G-GT over the committed GT v2, its change log and freeze, against this text layer."""
    return gt_cli.gate_files(files.gt, built["text"].path, files.gt_v1, files.gt_changes,
                             files.freeze)

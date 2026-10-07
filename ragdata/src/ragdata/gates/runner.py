"""Run the data gates of one stored layer and collect them into a JSON report.

A layer is gated together with the layers it depends on (struct needs text);
each dependency must be the exact version the layer's manifest declares.
The report passes only when every hard gate passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragdata.contract import LAYERS, record_type_for_file
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.gates.base import GateInputError, GateResult
from ragdata.gates.counts import check_counts
from ragdata.gates.refint import check_refint
from ragdata.gates.schema import check_schema
from ragdata.store import LayerData, read_layer

REPORT_SCHEMA = "ragdata.gate_report.v1"
REQUIRED_DEPS: Mapping[str, tuple[str, ...]] = {"text": (), "struct": ("text",)}


@dataclass(frozen=True)
class GateReport:
    layer: str
    layer_version: str
    depends_on: Mapping[str, str]
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates if g.hard)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "layer": self.layer, "layer_version": self.layer_version,
                "depends_on": dict(self.depends_on), "pass": self.passed,
                "gates": [g.to_json() for g in self.gates]}


def _load_deps(target: LayerData, deps: Sequence[Path | str]) -> list[LayerData]:
    loaded = [read_layer(d) for d in deps]
    given = {d.layer: d.version for d in loaded}
    if len(given) != len(loaded):
        raise GateInputError("each dependency layer may be given once")
    required = set(REQUIRED_DEPS[target.layer])
    declared = dict(target.depends_on)
    if set(given) != required or set(declared) != required:
        raise GateInputError(f"{target.layer} needs dependencies {sorted(required)}; manifest "
                             f"declares {sorted(declared)}, given {sorted(given)}")
    for layer, version in given.items():
        if declared[layer] != version:
            raise GateInputError(f"{target.layer} was built on {declared[layer]}, given {version}")
    return loaded


def _check_layer_files(data: LayerData) -> None:
    for name in data.file_shas:
        rtype = record_type_for_file(name)
        if rtype is None or rtype.layer != data.layer:
            owner = "no known layer" if rtype is None else f"the {rtype.layer} layer"
            raise GateInputError(f"{data.path}: {name} does not belong in a {data.layer} layer "
                                 f"(it belongs to {owner})")


def merge_files(layers: Sequence[LayerData]) -> dict[str, tuple[dict[str, Any], ...]]:
    """The ``.jsonl`` rows of ``layers`` by file name; each file must come from its own layer,
    so a layer can never stand in for the data of the layer it depends on."""
    files: dict[str, tuple[dict[str, Any], ...]] = {}
    for data in layers:
        _check_layer_files(data)
        for name, rows in data.rows.items():
            if name in files:
                raise GateInputError(f"{name} is given twice (again by {data.path})")
            files[name] = rows
    return files


def gate_layer(layer_dir: Path | str, layer: str, deps: Sequence[Path | str] = (),
               counts_path: Path | str = PDF_COUNTS_PATH) -> GateReport:
    """Verify, load and gate ``layer_dir``; raise GateInputError on a bad setup."""
    if layer not in LAYERS:
        raise GateInputError(f"no gates for layer {layer!r}")
    target = read_layer(layer_dir)
    if target.layer != layer:
        raise GateInputError(f"{layer_dir} holds a {target.layer} layer, not {layer}")
    loaded = [*_load_deps(target, deps), target]
    files = merge_files(loaded)
    schema, snapshot = check_schema(files, [d.layer for d in loaded])
    counts = check_counts(snapshot, layer, load_counts(counts_path).get(layer, {}))
    refint = check_refint(snapshot, layer)
    return GateReport(layer, target.version, target.depends_on, (schema, counts, refint))

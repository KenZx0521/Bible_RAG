"""Run the data gates of one stored layer and collect them into a JSON report.

A layer is gated together with the record layers it depends on (struct needs
text); each must be the exact version the layer's manifest declares. A ``src``
dependency (the PDFs as extracted) holds no records and is not loaded.

``REQUIRED_GATES`` lists, per layer, every gate of design §8 whose subject is
that layer (G-DET compares two runs and has its own command). A gate that is
not built yet still appears in the report as a failing hard gate, so the
report fails closed: it passes only when every required gate ran and every
hard gate passed. Tests may run a subset (``gates=``) to see what the built
gates catch; such a report never passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ragdata.contract import LAYERS, record_type_for_file
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.gates.base import GateInputError, GateResult, Snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.refint import check_refint
from ragdata.gates.schema import check_schema
from ragdata.store import DEPENDS_ON, LayerData, read_layer

REPORT_SCHEMA = "ragdata.gate_report.v1"
REQUIRED_DEPS: Mapping[str, tuple[str, ...]] = {"text": (), "struct": ("text",)}
REQUIRED_GATES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "text": ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-TEXT", "G-CONSERVE", "G-XCHECK", "G-REF"),
    "struct": ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-STRUCT"),
})
NOT_IMPLEMENTED = "not implemented"


@dataclass(frozen=True)
class GateContext:
    """What the gates of one run read."""

    layer: str
    schema: GateResult
    snapshot: Snapshot
    counts_path: Path | str


def _count_gate(ctx: GateContext) -> GateResult:
    return check_counts(ctx.snapshot, ctx.layer, load_counts(ctx.counts_path).get(ctx.layer, {}))


GATES: Mapping[str, Callable[[GateContext], GateResult]] = MappingProxyType({
    "G-SCHEMA": lambda ctx: ctx.schema,
    "G-COUNT": _count_gate,
    "G-REFINT": lambda ctx: check_refint(ctx.snapshot, ctx.layer),
})


def implemented_gates(layer: str) -> tuple[str, ...]:
    """The required gates of ``layer`` that are built, in report order."""
    return tuple(name for name in REQUIRED_GATES[layer] if name in GATES)


def not_implemented(name: str) -> GateResult:
    return GateResult(name, hard=True, passed=False, observed=NOT_IMPLEMENTED,
                      expected="implemented",
                      details=(f"{name} is required by design §8 but not built yet; "
                               "this layer cannot pass until it is",))


@dataclass(frozen=True)
class GateReport:
    layer: str
    layer_version: str
    depends_on: Mapping[str, str]
    gates: tuple[GateResult, ...]
    required: tuple[str, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        ran = {g.name for g in self.gates}
        return tuple(name for name in self.required if name not in ran)

    @property
    def passed(self) -> bool:
        return bool(self.gates) and bool(self.required) and not self.missing \
            and all(g.passed for g in self.gates if g.hard)

    def to_json(self) -> dict[str, Any]:
        return {"schema": REPORT_SCHEMA, "layer": self.layer, "layer_version": self.layer_version,
                "depends_on": dict(self.depends_on), "pass": self.passed,
                "required_gates": list(self.required), "missing_gates": list(self.missing),
                "gates": [g.to_json() for g in self.gates]}


def _load_deps(target: LayerData, deps: Sequence[Path | str]) -> list[LayerData]:
    loaded = [read_layer(d) for d in deps]
    given = {d.layer: d.version for d in loaded}
    if len(given) != len(loaded):
        raise GateInputError("each dependency layer may be given once")
    required = set(REQUIRED_DEPS[target.layer])
    declared = {layer: v for layer, v in target.depends_on.items() if layer in LAYERS}
    if set(given) != required or set(declared) != required:
        raise GateInputError(f"{target.layer} needs dependencies {sorted(required)}; manifest "
                             f"declares {sorted(declared)}, given {sorted(given)}")
    for layer, version in given.items():
        if declared[layer] != version:
            raise GateInputError(f"{target.layer} was built on {declared[layer]}, given {version}")
    return loaded


def _check_layer_files(data: LayerData) -> None:
    for name in sorted(set(data.file_shas) - {DEPENDS_ON}):
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


def _gate_names(layer: str, gates: Sequence[str] | None) -> tuple[str, ...]:
    required = REQUIRED_GATES[layer]
    names = required if gates is None else tuple(gates)
    if not names or len(set(names)) != len(names) or not set(names) <= set(required):
        raise GateInputError(f"gates {list(names)} must be distinct gates of the {layer} layer "
                             f"{list(required)}")
    return names


def gate_layer(layer_dir: Path | str, layer: str, deps: Sequence[Path | str] = (),
               counts_path: Path | str = PDF_COUNTS_PATH,
               gates: Sequence[str] | None = None) -> GateReport:
    """Verify, load and gate ``layer_dir`` with every required gate (or only ``gates``);
    raise GateInputError on a bad setup."""
    if layer not in LAYERS:
        raise GateInputError(f"no gates for layer {layer!r}")
    names = _gate_names(layer, gates)
    target = read_layer(layer_dir)
    if target.layer != layer:
        raise GateInputError(f"{layer_dir} holds a {target.layer} layer, not {layer}")
    loaded = [*_load_deps(target, deps), target]
    schema, snapshot = check_schema(merge_files(loaded), [d.layer for d in loaded])
    ctx = GateContext(layer, schema, snapshot, counts_path)
    results = tuple(GATES[n](ctx) if n in GATES else not_implemented(n) for n in names)
    return GateReport(layer, target.version, target.depends_on, results, REQUIRED_GATES[layer])

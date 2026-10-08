"""Build the kg0 layer (K0) from stored text and struct layers and store it if its gates pass.

Inputs: the text layer, the struct layer built on it, the K0 registries
(``config/registries``) and ``expectations/kg0_counts.yaml``. Gates: G-SCHEMA,
G-REFINT, G-KG0 and G-PROV over the new rows; a red build writes nothing. The layer
holds ``names``, ``extra_spans``, ``parallel_links`` and ``kg0_report.json`` (the
registry versions and what every rule did) and depends on text and struct.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragdata import paths
from ragdata.contract.counts import KG0_COUNTS_PATH, load_kg0_counts
from ragdata.contract.registry import KG0_REPORT
from ragdata.gates.base import GateResult, Snapshot
from ragdata.gates.kg0 import check_kg0
from ragdata.gates.prov import check_prov
from ragdata.gates.refint import check_refint
from ragdata.gates.schema import check_schema
from ragdata.kg import k0, registries
from ragdata.kg.layers import encode_json, load_inputs, with_records
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import StoredLayer, encode_jsonl, write_layer

KG0_FILES = ("names", "extra_spans", "parallel_links")


def kg0_gates(base: Snapshot, rows: Mapping[str, Any], report: Mapping[str, Any],
              expected: Mapping[str, Any], depends_on: Mapping[str, str]) -> list[GateResult]:
    files = {f"{name}.jsonl": rows[name] for name in KG0_FILES}
    schema, own = check_schema(files, ["kg0"])
    snap = with_records(base, own)
    return [schema, check_refint(snap, "kg0"), check_kg0(snap, report, expected, depends_on),
            check_prov(files)]


def compute(text_dir: Path, struct_dir: Path, registries_dir: Path
            ) -> tuple[dict[str, str], Snapshot, k0.K0Result]:
    layers, snap = load_inputs(text_dir, struct_dir)
    result = k0.kg0_rows(snap, registries.load_k0(registries_dir))
    return {name: data.version for name, data in layers.items()}, snap, result


def build_kg0(text_dir: Path, struct_dir: Path, store_root: Path,
              registries_dir: Path = paths.REGISTRIES,
              counts_path: Path = KG0_COUNTS_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("k0"):
        depends, snap, result = compute(Path(text_dir), Path(struct_dir), Path(registries_dir))
    report = dict(result.report)
    with clock.lap("gates"):
        gates = kg0_gates(snap, result.rows, report, load_kg0_counts(counts_path), depends)
    layers: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            files = {**{f"{n}.jsonl": encode_jsonl(result.rows[n]) for n in KG0_FILES},
                     KG0_REPORT: encode_json(report)}
            layers["kg0"] = write_layer(store_root, "kg0", files, depends_on=depends,
                                        exist_ok=True)
    return BuildResult(MappingProxyType(layers), tuple(gates), MappingProxyType(clock.laps))


def expected_counts(text_dir: Path, struct_dir: Path,
                    registries_dir: Path = paths.REGISTRIES) -> dict[str, Any]:
    """What ``ragdata expect kg0`` writes into expectations/kg0_counts.yaml."""
    depends, _, result = compute(Path(text_dir), Path(struct_dir), Path(registries_dir))
    return k0.kg0_counts(result, depends["text"], depends["struct"])

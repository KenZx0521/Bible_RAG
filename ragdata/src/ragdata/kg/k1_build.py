"""Build the events layer (K1, R2) and store it if its gates pass.

Inputs: the text and struct layers and ``config/registries/events.yaml`` (the
hand-maintained registry); no R1 data. Gates: G-SCHEMA, G-COUNT, G-REFINT, G-EVENT and
G-PROV; a red build writes nothing. The layer holds ``events``, the contract file
``event_registry_v2.json`` and ``events_report.json``.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragdata import paths
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.contract.registry import EVENT_REGISTRY_V2, EVENTS_REPORT
from ragdata.gates.base import GateResult, Snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.events import check_event
from ragdata.gates.prov import check_prov
from ragdata.gates.refint import check_refint
from ragdata.gates.schema import check_schema
from ragdata.kg import k1_events
from ragdata.kg.layers import encode_json, load_inputs, with_records
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import StoredLayer, encode_jsonl, write_layer

EVENT_FILES = ("events",)


def event_gates(base: Snapshot, result: k1_events.EventsResult, struct_version: str,
                counts_path: Path) -> list[GateResult]:
    files = {f"{name}.jsonl": result.rows[name] for name in EVENT_FILES}
    schema, own = check_schema(files, ["events"])
    snap = with_records(base, own)
    return [schema, check_counts(snap, "events", load_counts(counts_path).get("events", {})),
            check_refint(snap, "events"), check_event(snap, result.v2, struct_version),
            check_prov(files)]


def _files(result: k1_events.EventsResult) -> Mapping[str, bytes]:
    return {**{f"{n}.jsonl": encode_jsonl(result.rows[n]) for n in EVENT_FILES},
            EVENT_REGISTRY_V2: encode_json(result.v2), EVENTS_REPORT: encode_json(result.report)}


def build_events(text_dir: Path, struct_dir: Path, store_root: Path,
                 events_yaml: Path = paths.EVENTS_REGISTRY,
                 counts_path: Path = PDF_COUNTS_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("k1"):
        layers, snap = load_inputs(Path(text_dir), Path(struct_dir))
        struct_version = layers["struct"].version
        doc, version = k1_events.load_events_yaml(events_yaml)
        result = k1_events.compile_events(doc, snap, struct_version, version)
    with clock.lap("gates"):
        gates = event_gates(snap, result, struct_version, Path(counts_path))
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            depends: dict[str, Any] = {name: data.version for name, data in layers.items()}
            stored["events"] = write_layer(store_root, "events", _files(result),
                                           depends_on=depends, exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

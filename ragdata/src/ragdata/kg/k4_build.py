"""Build the route layer (K4, R2) from the text, kg0 and events layers (``kg.k4_route``).

Inputs: the three layers (kg0 and events built on that text), the registries kg0 was built
with (``divine_refs``, ``name_normalization``) and ``query_aliases.yaml``. Gates: G-SCHEMA,
G-COUNT, G-ROUTE and G-PROV; a red build writes nothing. The layer holds
``routing_terms``, ``routing_lexicon.json`` and ``query_aliases.json`` (the contract files)
and ``route_report.json`` (counts, unroutable terms, the ‧ spellings that were already a
term).
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ragcommon import routing
from ragdata import paths
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.contract.registry import QUERY_ALIASES, ROUTE_REPORT, ROUTING_LEXICON
from ragdata.gates.base import GateResult
from ragdata.gates.counts import check_counts
from ragdata.gates.prov import check_prov
from ragdata.gates.route import check_route
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.kg import k4_route
from ragdata.kg.k4_route import Compiled, RouteInputs
from ragdata.kg.layers import encode_json, with_records
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import LayerData, StoredLayer, encode_jsonl, read_layer, write_layer

INPUTS = ("text", "kg0", "events")


def load_layers(dirs: Mapping[str, Path]) -> dict[str, LayerData]:
    """The text, kg0 and events layers (``dirs`` by layer), checked to be what they claim and
    built on the same text and struct."""
    layers: dict[str, LayerData] = {}
    for layer in INPUTS:
        layers[layer] = read_layer(Path(dirs[layer]))
        if layers[layer].layer != layer:
            raise StageError(f"{dirs[layer]} holds a {layers[layer].layer} layer, not {layer}")
    built_on = {name: dict(data.depends_on) for name, data in layers.items()}
    if built_on["kg0"].get("text") != layers["text"].version or \
            built_on["events"].get("text") != layers["text"].version:
        raise StageError(f"kg0 and events must be built on {layers['text'].version}: {built_on}")
    if built_on["kg0"].get("struct") != built_on["events"].get("struct"):
        raise StageError(f"kg0 and events are built on different struct layers: {built_on}")
    return layers


def route_files(compiled: Compiled) -> dict[str, bytes]:
    return {"routing_terms.jsonl": encode_jsonl(compiled.records),
            ROUTING_LEXICON: routing.render_lexicon(compiled.lexicon),
            QUERY_ALIASES: encode_json(compiled.query_aliases),
            ROUTE_REPORT: encode_json(compiled.report)}


def route_gates(inputs: RouteInputs, files: Mapping[str, bytes], compiled: Compiled,
                counts_path: Path) -> list[GateResult]:
    rows = {"routing_terms.jsonl": compiled.records}
    schema, own = check_schema(rows, ["route"])
    snap = with_records(inputs.snapshot, own)
    return [schema, check_counts(snap, "route", load_counts(counts_path).get("route", {})),
            check_route(inputs, snap.of("routing_terms"), files[ROUTING_LEXICON],
                        files[QUERY_ALIASES]),
            check_prov(rows)]


def build_route(text_dir: Path, kg0_dir: Path, events_dir: Path, store_root: Path,
                registries: Path = paths.REGISTRIES,
                counts_path: Path = PDF_COUNTS_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("k4"):
        layers = load_layers({"text": text_dir, "kg0": kg0_dir, "events": events_dir})
        schema, snap = check_schema(merge_files(list(layers.values())), list(layers))
        if not schema.passed:
            raise StageError(f"input layers fail G-SCHEMA: {list(schema.details[:3])}")
        versions = {name: data.version for name, data in layers.items()}
        inputs = k4_route.route_inputs(snap, versions, registries)
        compiled = k4_route.compile_route(inputs)
        files = route_files(compiled)
    with clock.lap("gates"):
        gates = route_gates(inputs, files, compiled, Path(counts_path))
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            stored["route"] = write_layer(store_root, "route", files, depends_on=versions,
                                          exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

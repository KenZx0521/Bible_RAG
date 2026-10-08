"""Build the route layer (K4, R1) from the text layer and the frozen lexicon.

Inputs: the text layer (for the probe verses and headings), the frozen
``routing_lexicon.legacy.json``, the GT questions and the old backend's matches on
those probe texts, frozen in the store (``k4_live``; no backend runs). Gates:
G-SCHEMA, G-COUNT, G-ROUTE and G-PROV; a red build writes nothing. The layer holds
``routing_terms``, ``routing_lexicon.json`` (the contract file, the frozen bytes) and
``route_report.json`` (the lexicon header, the probe set and the words the PDF verses
never print).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragcommon import routing
from ragdata import paths
from ragdata.contract.counts import PDF_COUNTS_PATH, load_counts
from ragdata.contract.registry import ROUTE_REPORT, ROUTING_LEXICON
from ragdata.gates.base import GateResult, Snapshot
from ragdata.gates.counts import check_counts
from ragdata.gates.prov import check_prov
from ragdata.gates.route import check_route
from ragdata.gates.schema import check_schema
from ragdata.kg import k4_route
from ragdata.kg.k4_route import LiveProbe
from ragdata.kg.layers import encode_json, load_inputs, with_records
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import StoredLayer, encode_jsonl, write_layer

REPORT_SCHEMA = "ragdata.route_report.v1"


def read_frozen(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        data = Path(path).read_bytes()
        return data, json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise StageError(f"{path}: cannot read the frozen lexicon: {exc}") from None


def route_report(rest: Mapping[str, Any], probes: Mapping[str, Sequence[str]],
                 rows: Sequence[Mapping[str, Any]], snapshot: Snapshot) -> dict[str, Any]:
    return {"schema": REPORT_SCHEMA, "lexicon_rest": dict(rest),
            "probes": k4_route.probe_summary(probes),
            "zero_in_verses": k4_route.zero_in_verses(rows, snapshot)}


def route_gates(base: Snapshot, rows: Sequence[Mapping[str, Any]], rest: Mapping[str, Any],
                lexicon: bytes, frozen: bytes | None, texts: Sequence[str] | None,
                live: Sequence[Mapping[str, Any]] | None, counts_path: Path) -> list[GateResult]:
    files = {"routing_terms.jsonl": list(rows)}
    schema, own = check_schema(files, ["route"])
    snap = with_records(base, own)
    return [schema, check_counts(snap, "route", load_counts(counts_path).get("route", {})),
            check_route(snap.of("routing_terms"), rest, lexicon, frozen, texts, live),
            check_prov(files)]


def build_route(text_dir: Path, store_root: Path, live: LiveProbe,
                lexicon_path: Path = paths.FROZEN_LEXICON,
                ground_truth: Path = paths.GROUND_TRUTH,
                counts_path: Path = PDF_COUNTS_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("k4"):
        layers, snap = load_inputs(Path(text_dir))
        frozen, doc = read_frozen(lexicon_path)
        rest, rows = k4_route.split_lexicon(doc)
        lexicon = routing.render_lexicon(k4_route.join_lexicon(rest, rows))
        probes = k4_route.probe_texts(snap, ground_truth)
    texts = k4_route.flatten(probes)
    with clock.lap("live_probe"):
        live_results = live(texts)
    with clock.lap("gates"):
        gates = route_gates(snap, rows, rest, lexicon, frozen, texts, live_results,
                            Path(counts_path))
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            files = {"routing_terms.jsonl": encode_jsonl(rows), ROUTING_LEXICON: lexicon,
                     ROUTE_REPORT: encode_json(route_report(rest, probes, rows, snap))}
            stored["route"] = write_layer(store_root, "route", files,
                                          depends_on={"text": layers["text"].version},
                                          exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

"""Build the relations layer and store it if G-REGNAL and G-GEN pass.

The relations layer (L3, design §13.1: rule-based relations; ``ids.LAYERS`` reserves the
name) holds only the data of two backend cards, each a narrow exception Kay let in: the regnal
formulas (P5, 2026-10-19, the chronology card) and the Genesis 5 and 11 chains (the GEN card,
2026-10-21); every other relation stays unbuilt.

Regnal input: the text layer only (its verse units and footnotes; ``regnal_core.inputs``). The
layer holds the contract file ``regnal_layer.json`` and ``regnal_report.json``. The
contract file is serialized as experiment A wrote ``layer_auto.json``
(``json.dumps(ensure_ascii=False, indent=1)``, no final newline), so its sha256 is the
audited file's and G-REGNAL can pin it (``gates.regnal``). Since the rule fixes of
2026-10-19 (R1a-R12, ``regnal_formulas``) the build is no longer experiment A's file but the
fixed layer (store reports/regnal_fix_20261019/candidate/, made by
``evaluation/experiments/2026-10-19_regnal_fix/candidate.py``); the store's
relations@a04b67a301dc still holds experiment A's.

GEN input: the text layer's verse units (``gen_layer``) and names, and the route layer's routing
lexicon (``gen_names``). A text that holds Genesis 5 or 11 gets both contract files,
``gen_layer.json`` and ``gen_names.json``, and the layer depends on {text, route}; that build
needs the route layer. A text without them (the mini text) gets neither, and the layer depends
on text alone. G-GEN pins the two files' sha256s (``gates.gen``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragdata.contract.registry import GEN_LAYER, GEN_NAMES, REGNAL_LAYER, REGNAL_REPORT, ROUTING_LEXICON
from ragdata.gates.gen import GEN_EXPECT_PATH, check_gen, load_gen_expect
from ragdata.gates.regnal import REGNAL_EXPECT_PATH, check_regnal, load_regnal_expect, report_doc
from ragdata.kg import gen_layer, gen_names
from ragdata.kg.layers import encode_json, load_inputs
from ragdata.kg.regnal_core import inputs
from ragdata.kg.regnal_formulas import compile_layer
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import LayerData, StoredLayer, layer_digest, read_layer, write_layer


def encode_layer(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def regnal_files(text: LayerData) -> dict[str, bytes]:
    """The layer's two regnal files, built from ``text``."""
    verses, fns = inputs(text.rows["verse_units.jsonl"], text.rows["footnotes.jsonl"])
    data = encode_layer(compile_layer(verses, fns))
    report = report_doc(json.loads(data), text.version, hashlib.sha256(data).hexdigest())
    return {REGNAL_LAYER: data, REGNAL_REPORT: encode_json(report)}


def gen_files(text: LayerData, route: LayerData | None) -> dict[str, bytes]:
    """The layer's two GEN files, built from ``text`` and ``route``; none for a text without
    Genesis 5 and 11."""
    units = text.rows["verse_units.jsonl"]
    if not gen_layer.has_chains(units):
        return {}
    if route is None:
        raise StageError(f"{text.version} holds Genesis 5 and 11: {GEN_NAMES} reads the route "
                         "layer's routing lexicon (--route)")
    layer = gen_layer.encode(gen_layer.build(units, layer_digest(text.file_shas)))
    return {GEN_LAYER: layer, GEN_NAMES: gen_layer.encode(gen_names.build(layer, text, route))}


def _route(route_dir: Path | None, text: LayerData) -> LayerData | None:
    if route_dir is None:
        return None
    route = read_layer(route_dir)
    if route.layer != "route":
        raise StageError(f"{route_dir} holds a {route.layer} layer, not a route layer")
    if route.depends_on.get("text") != text.version:
        raise StageError(f"{route_dir} was built on {route.depends_on.get('text')}, not on {text.version}")
    return route


def build_regnal(text_dir: Path, store_root: Path, expect_path: Path = REGNAL_EXPECT_PATH, *,
                 route_dir: Path | None = None, gen_expect: Path = GEN_EXPECT_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("regnal"):
        layers, _snap = load_inputs(Path(text_dir))
        text = layers["text"]
        files = regnal_files(text)
    with clock.lap("gen"):
        route = _route(route_dir, text)
        gen = gen_files(text, route)
        files = {**files, **gen}
    with clock.lap("gates"):
        depends = {"text": text.version, **({"route": route.version} if gen else {})}
        lexicon = route.file_shas.get(ROUTING_LEXICON) if gen else None
        gates = [check_regnal(files[REGNAL_LAYER], json.loads(files[REGNAL_REPORT]), depends,
                              load_regnal_expect(expect_path)),
                 check_gen(gen.get(GEN_LAYER), gen.get(GEN_NAMES),
                           hashlib.sha256(files[REGNAL_LAYER]).hexdigest(), depends, lexicon,
                           load_gen_expect(gen_expect))]
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            stored["relations"] = write_layer(store_root, "relations", files, depends_on=depends,
                                              exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

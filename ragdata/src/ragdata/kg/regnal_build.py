"""Build the relations layer and store it if G-REGNAL passes.

The relations layer (L3, design §13.1: rule-based relations; ``ids.LAYERS`` reserves the
name) holds only the regnal formulas: Kay's P5 exception of 2026-10-19 lets this one
narrow use in, the chronology card, and every other relation stays unbuilt.

Input: the text layer only (its verse units and footnotes; ``regnal_core.inputs``). The
layer holds the contract file ``regnal_layer.json`` and ``regnal_report.json``. The
contract file is serialized as experiment A wrote ``layer_auto.json``
(``json.dumps(ensure_ascii=False, indent=1)``, no final newline), so its sha256 is the
audited file's and G-REGNAL can pin it (``gates.regnal``). Since the rule fixes of
2026-10-19 (R1a-R12, ``regnal_formulas``) the build is no longer experiment A's file but the
fixed layer (store reports/regnal_fix_20261019/candidate/, made by
``evaluation/experiments/2026-10-19_regnal_fix/candidate.py``); the store's
relations@a04b67a301dc still holds experiment A's.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragdata.contract.registry import REGNAL_LAYER, REGNAL_REPORT
from ragdata.gates.regnal import REGNAL_EXPECT_PATH, check_regnal, load_regnal_expect, report_doc
from ragdata.kg.layers import encode_json, load_inputs
from ragdata.kg.regnal_core import inputs
from ragdata.kg.regnal_formulas import compile_layer
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import LayerData, StoredLayer, write_layer


def encode_layer(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def regnal_files(text: LayerData) -> dict[str, bytes]:
    """The layer's two files, built from ``text``."""
    verses, fns = inputs(text.rows["verse_units.jsonl"], text.rows["footnotes.jsonl"])
    data = encode_layer(compile_layer(verses, fns))
    report = report_doc(json.loads(data), text.version, hashlib.sha256(data).hexdigest())
    return {REGNAL_LAYER: data, REGNAL_REPORT: encode_json(report)}


def build_regnal(text_dir: Path, store_root: Path,
                 expect_path: Path = REGNAL_EXPECT_PATH) -> BuildResult:
    clock = Clock()
    with clock.lap("regnal"):
        layers, _snap = load_inputs(Path(text_dir))
        text = layers["text"]
        files = regnal_files(text)
    with clock.lap("gates"):
        depends = {"text": text.version}
        gates = [check_regnal(files[REGNAL_LAYER], json.loads(files[REGNAL_REPORT]), depends,
                              load_regnal_expect(expect_path))]
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            stored["relations"] = write_layer(store_root, "relations", files, depends_on=depends,
                                              exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

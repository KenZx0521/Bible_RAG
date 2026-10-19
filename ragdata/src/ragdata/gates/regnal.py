"""G-REGNAL: the regnal layer is the audited one (Kay's P5 exception, 2026-10-19).

The regnal layer exists for one use, the backend's chronology card, and it is
accepted as a specific file. It was first experiment A's ``layer_auto.json`` (K0
field precision 40/40, Kay's check 0/20 rows wrong, the blind confirmation set; see
``evaluation/experiments/2026-10-18_kg_cards/confirm_A.md``); since the rule fixes of
2026-10-19 (R1a-R12, ``kg.regnal_formulas``) it is the fixed layer, audited by K0-R
against the reference layer without Solomon, K0-1' and Kay's check
(``evaluation/experiments/2026-10-19_regnal_fix/``). So the gate pins it:

- the layer was built on the text layer ``expectations/regnal_expect.yaml`` names,
  and ``regnal_layer.json`` hashes to its ``layer_sha256`` (a new text layer or a
  changed rule means a new audit before the expectation may move);
- the document is the occ/slot policy with no name union, every id is unique,
  every edge and synchronism names a node, and a king's kingdom is Israel ('I'),
  Judah ('J') or the united monarchy ('U', on neither chain);
- the succession chains read by ``ragcommon.regnal`` and the conflict count equal
  the expectation, and ``regnal_report.json`` restates the layer it sits beside.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from ragcommon import regnal
from ragdata.gates.base import GateInputError, GateResult, capped

NAME = "G-REGNAL"
EXPECT_SCHEMA = "ragdata.regnal_expect.v1"
REPORT_SCHEMA = "ragdata.regnal_report.v1"
REGNAL_EXPECT_PATH = Path(__file__).resolve().parents[1] / "contract" / "expectations" / "regnal_expect.yaml"
EXPECT_KEYS = ("schema", "inputs", "layer_sha256", "chains", "conflicts")
LAYER_KINGDOMS = (*regnal.KINGDOMS, "U")   # 'U': all Israel (R8); a mention-only node may also have None


def load_regnal_expect(path: Path | str = REGNAL_EXPECT_PATH) -> Mapping[str, Any]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GateInputError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != EXPECT_SCHEMA \
            or any(k not in doc for k in EXPECT_KEYS):
        raise GateInputError(f"{path}: not a {EXPECT_SCHEMA} document with {list(EXPECT_KEYS)}")
    return doc


def report_doc(doc: Mapping[str, Any], text_version: str, layer_sha256: str) -> dict[str, Any]:
    """``regnal_report.json``: what the layer holds, in counts and chains."""
    view = regnal.load(doc)
    log_kinds: dict[str, int] = {}
    for entry in doc["log"]:
        log_kinds[entry[0]] = log_kinds.get(entry[0], 0) + 1
    return {"schema": REPORT_SCHEMA, "text": text_version, "layer_sha256": layer_sha256,
            "counts": {"nodes": len(doc["nodes"]), "kings": len(view.nodes),
                       "edges": len(doc["edges"]), "fallback_edges": len(doc["fallback_edges"]),
                       "syncs": len(doc["syncs"]), "conflicts": len(doc["conflicts"]),
                       "occ_alias": len(doc["occ_alias"]), "log": dict(sorted(log_kinds.items()))},
            "chains": view.chain_names()}


def expectation_doc(doc: Mapping[str, Any], text_version: str, layer_sha256: str) -> dict[str, Any]:
    """The expectation a layer would meet (written by hand for the store; tests use it)."""
    return {"schema": EXPECT_SCHEMA, "inputs": {"text": text_version}, "layer_sha256": layer_sha256,
            "chains": regnal.load(doc).chain_names(), "conflicts": len(doc["conflicts"])}


def _structure(doc: Mapping[str, Any]) -> list[str]:
    out = []
    if doc.get("policy") != "occ" or doc.get("fn_rule") != "slot" or doc.get("union_classes") is not None:
        out.append(f"policy {doc.get('policy')!r}, fn_rule {doc.get('fn_rule')!r}, "
                   f"union_classes {doc.get('union_classes')!r}: want occ, slot, none")
    ids = [n["id"] for n in doc["nodes"]]
    out += [f"node id {i} is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    known = set(ids)
    for key in ("edges", "fallback_edges"):
        out += [f"{key} {e[0]}->{e[1]} names no node" for e in doc[key] if not {e[0], e[1]} <= known]
    out += [f"sync {s[0]}~{s[1]} names no node" for s in doc["syncs"] if not {s[0], s[1]} <= known]
    out += [f"node {n['id']} ({n['name']}) has accession evidence but no kingdom"
            for n in doc["nodes"] if (n["has_acc"] or "reign" in n["fields"]) and n["kingdom"] is None]
    out += [f"node {n['id']} ({n['name']}) has kingdom {n['kingdom']!r}: want one of {list(LAYER_KINGDOMS)}"
            for n in doc["nodes"] if n["kingdom"] is not None and n["kingdom"] not in LAYER_KINGDOMS]
    return out


def check_regnal(layer_bytes: bytes | None, report: Mapping[str, Any] | None,
                 depends_on: Mapping[str, str], expect: Mapping[str, Any]) -> GateResult:
    want = {"text": expect["inputs"].get("text"), "layer_sha256": str(expect["layer_sha256"])[:12],
            "chains": {k: len(v) for k, v in expect["chains"].items()}, "conflicts": expect["conflicts"]}
    if layer_bytes is None:
        return GateResult(NAME, hard=True, passed=False, observed="missing input", expected=want,
                          details=(f"the layer holds no {regnal.LAYER_FILE}",))
    sha = hashlib.sha256(layer_bytes).hexdigest()
    out = []
    text = depends_on.get("text")
    if text != expect["inputs"].get("text"):
        out.append(f"built on {text}, the expectation names {expect['inputs'].get('text')}: "
                   "audit the layer of this text again before the expectation moves")
    if sha != expect["layer_sha256"]:
        out.append(f"{regnal.LAYER_FILE} sha256 {sha[:12]} is not the audited {str(expect['layer_sha256'])[:12]}")
    try:
        doc = json.loads(layer_bytes.decode("utf-8"))
        if not isinstance(doc, dict):
            raise TypeError(f"a {type(doc).__name__}, not an object")
        out += _structure(doc)
        chains = regnal.load(doc).chain_names()
        restated = report_doc(doc, text or "", sha)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        return GateResult(NAME, hard=True, passed=False, observed={"sha256": sha[:12]}, expected=want,
                          details=(f"{regnal.LAYER_FILE} is not a regnal layer: {exc!r}",))
    for kd in regnal.KINGDOMS:
        if chains[kd] != list(expect["chains"].get(kd, [])):
            out.append(f"chain {kd} is {chains[kd]}, the expectation {expect['chains'].get(kd)}")
    if len(doc["conflicts"]) != expect["conflicts"]:
        out.append(f"{len(doc['conflicts'])} field conflicts, the expectation {expect['conflicts']}")
    if report is None or report != restated:
        out.append("regnal_report.json is missing or does not restate this layer")
    observed = {"text": text, "layer_sha256": sha[:12], "chains": {k: len(v) for k, v in chains.items()},
                "conflicts": len(doc["conflicts"])}
    return GateResult(NAME, hard=True, passed=not out, observed=observed, expected=want,
                      details=capped(out))

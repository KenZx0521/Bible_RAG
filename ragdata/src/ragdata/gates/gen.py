"""G-GEN: the GEN card's two files are the audited ones (plan 2026-10-21 §2.1, D1, D2).

A relations layer may carry ``gen_layer.json`` and ``gen_names.json``, the data of the backend's
Genesis lifespan card. Like the regnal layer they are accepted as specific files, so the gate
pins them (``expectations/gen_expect.yaml``):

- both files or neither: only one of them is red;
- with them: each hashes to its pinned sha256, the layer declares the route layer it read the
  lexicon from, that route layer's ``routing_lexicon.json`` is the one ``gen_names.json`` names
  in its ``sources``, and ``gen_layer.json``'s ``text_digest`` is the text layer it depends on;
- without them: only a layer that depends on exactly {text} and whose ``regnal_layer.json`` is
  one of ``absent_ok_regnal`` (the relations layers that existed before GEN). The store is
  content addressed, so this lets through those layers only; a layer built on route must carry
  the files.

The parse of the files by the backend's ``gencard``, K0-2 and ``gen_layer_sha256`` are fixed
properties of the pinned bytes; the builder's tests check them once against the store's files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from ragcommon import ids
from ragdata.contract.registry import GEN_LAYER, GEN_NAMES, ROUTING_LEXICON
from ragdata.gates.base import GateInputError, GateResult, capped
from ragdata.kg.gen_names import SOURCE_LEXICON

NAME = "G-GEN"
EXPECT_SCHEMA = "ragdata.gen_expect.v1"
GEN_EXPECT_PATH = Path(__file__).resolve().parents[1] / "contract" / "expectations" / "gen_expect.yaml"
EXPECT_KEYS = ("schema", "gen_layer_sha256", "gen_names_sha256", "absent_ok_regnal")


def load_gen_expect(path: Path | str = GEN_EXPECT_PATH) -> Mapping[str, Any]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GateInputError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != EXPECT_SCHEMA \
            or any(k not in doc for k in EXPECT_KEYS) or not isinstance(doc["absent_ok_regnal"], list):
        raise GateInputError(f"{path}: not a {EXPECT_SCHEMA} document with {list(EXPECT_KEYS)}")
    return doc


def _sha(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _short(data: bytes | None) -> str | None:
    return None if data is None else _sha(data)[:12]


def _absent(regnal_sha: str | None, depends_on: Mapping[str, str], expect: Mapping[str, Any]) -> list[str]:
    out = []
    if set(depends_on) != {"text"}:
        out.append(f"no {GEN_LAYER} or {GEN_NAMES}, but the layer depends on {sorted(depends_on)}: "
                   "a layer built on route carries both")
    if regnal_sha not in {str(s) for s in expect["absent_ok_regnal"]}:
        out.append(f"no {GEN_LAYER} or {GEN_NAMES}, and regnal_layer.json "
                   f"{(regnal_sha or 'missing')[:12]} is not a layer from before GEN")
    return out


def _present(layer: bytes, names: bytes, depends_on: Mapping[str, str], lexicon_sha: str | None,
             expect: Mapping[str, Any]) -> list[str]:
    out = []
    for name, data, key in ((GEN_LAYER, layer, "gen_layer_sha256"), (GEN_NAMES, names, "gen_names_sha256")):
        if _sha(data) != str(expect[key]):
            out.append(f"{name} sha256 {_short(data)} is not the audited {str(expect[key])[:12]}")
    if "route" not in depends_on:
        out.append(f"the layer holds {GEN_NAMES} but does not depend on the route layer it read")
    try:
        named = json.loads(names.decode("utf-8"))["sources"].get(SOURCE_LEXICON)
        text = ids.layer_version("text", json.loads(layer.decode("utf-8"))["text_digest"])
    except (ValueError, KeyError, TypeError, AttributeError, ids.IdError) as exc:
        return [*out, f"{GEN_LAYER} or {GEN_NAMES} is not a GEN file: {exc!r}"]
    if lexicon_sha is None or named != lexicon_sha:
        out.append(f"{GEN_NAMES} names lexicon {str(named)[:12]}, the route layer's "
                   f"{ROUTING_LEXICON} is {(lexicon_sha or 'not given')[:12]}")
    if text != depends_on.get("text"):
        out.append(f"{GEN_LAYER} was read from {text}, the layer depends on {depends_on.get('text')}")
    return out


def check_gen(layer: bytes | None, names: bytes | None, regnal_sha: str | None,
              depends_on: Mapping[str, str], lexicon_sha: str | None,
              expect: Mapping[str, Any]) -> GateResult:
    """``layer``/``names``: the two files' bytes (None if absent); ``regnal_sha``: the layer's
    regnal_layer.json sha256; ``lexicon_sha``: the depended-on route layer's routing_lexicon.json
    sha256 (None if route was not given)."""
    want = {"gen_layer_sha256": str(expect["gen_layer_sha256"])[:12],
            "gen_names_sha256": str(expect["gen_names_sha256"])[:12],
            "absent_ok_regnal": [str(s)[:12] for s in expect["absent_ok_regnal"]]}
    observed = {"gen_layer_sha256": _short(layer), "gen_names_sha256": _short(names),
                "depends_on": sorted(depends_on)}
    if (layer is None) != (names is None):
        missing = GEN_NAMES if names is None else GEN_LAYER
        return GateResult(NAME, hard=True, passed=False, observed=observed, expected=want,
                          details=(f"the layer holds one GEN file but not {missing}: both or neither",))
    out = _absent(regnal_sha, depends_on, expect) if layer is None \
        else _present(layer, names, depends_on, lexicon_sha, expect)
    return GateResult(NAME, hard=True, passed=not out, observed=observed, expected=want,
                      details=capped(out))

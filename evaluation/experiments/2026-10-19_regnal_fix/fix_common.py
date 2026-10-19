"""Paths, pins and small readers of the regnal-layer fix (2026-10-19; layer rules R1a-R12).

Shared by ref_v2.py, candidate.py, k0r.py and k0_diff.py. Host python, CPU only: nothing here
calls Ollama, docker or a model. Outputs go to store reports/regnal_fix_20261019/ only; the repo
holds code. Experiment A's store files (reports/kg_cards_20261018/) are read, never written, and
its code (evaluation/experiments/2026-10-18_kg_cards/) is not imported: its regnal.View.idx
raises KeyError on the united-monarchy kingdom 'U' the fixed layer gives Solomon.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _p in (REPO / "ragdata" / "src", REPO / "packages"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

STORE = Path("/mnt/ollama-data/bible_rag_store")
TEXT = STORE / "layers/text/text@247eafe44b02"
A_DIR = STORE / "reports/kg_cards_20261018/A"
REF = A_DIR / "ref_layer.json"
REF_SHA = "79d57efe451f675b6d2c1163d801b2a173a24a1a8b1ed0ba6a207f698ca16660"
OLD_LAYER = STORE / "layers/relations/relations@a04b67a301dc/regnal_layer.json"
OLD_SHA = "932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab"
OUT = STORE / "reports/regnal_fix_20261019"
REF_V2 = OUT / "ref_layer_v2.json"
CANDIDATE = OUT / "candidate"
K0_DIR = OUT / "k0"
KS = (-3, -2, -1, 1, 2, 3)
KINGDOMS = ("I", "J")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_pinned(path: Path, sha: str) -> bytes:
    """The bytes of ``path``; raises if they do not hash to ``sha``."""
    data = Path(path).read_bytes()
    if sha256_bytes(data) != sha:
        raise SystemExit(f"{path}: sha256 {sha256_bytes(data)[:12]} is not the pinned {sha[:12]}")
    return data


def dump(doc: Any) -> bytes:
    """The serialization of experiment A's layer files: indent=1, ensure_ascii=False, no final newline."""
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def write_new(path: Path, data: bytes) -> str:
    """Write ``data`` under OUT (never elsewhere) and return its sha256."""
    path = Path(path)
    if OUT not in path.parents:
        raise SystemExit(f"{path}: outputs go under {OUT} only")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def text_rows() -> dict[str, str]:
    """unit_key -> verse text of the text layer (store only; never written to the repo)."""
    from ragdata.store import read_layer
    return {r["unit_key"]: r["text"] for r in read_layer(TEXT).rows["verse_units.jsonl"]}


# ---------------------------------------------------------------- reference layer rows
def ref_view(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Chains (ids in file order per kingdom), rows by id and typed predecessor edges of a
    reference layer (a JSON list in succession order; only kingdoms I and J)."""
    rows = list(rows)
    by_id = {r["id"]: r for r in rows}
    chain = {kd: [r["id"] for r in rows if r["kingdom"] == kd] for kd in KINGDOMS}
    edge = {(r["pred"][0], r["id"]): (r["pred"][1], r["pred"][2]) for r in rows if r["pred"] and r["pred"][0]}
    return {"rows": by_id, "chain": chain, "edge": edge}


def keyed(names: Iterable[str]) -> list[tuple[str, int]]:
    """(name, k-th occurrence) per position, so the two Jeroboams of Israel stay apart."""
    seen: collections.Counter = collections.Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append((n, seen[n]))
    return out


def succ_rows(names: list[str]) -> dict[tuple[tuple[str, int], int], tuple[str, int]]:
    """The +-1..+-3 succession rows of one chain: {(king, k): king k places away}."""
    ks = keyed(names)
    return {(x, k): ks[i + k] for i, x in enumerate(ks) for k in KS if 0 <= i + k < len(ks)}


def compare_rows(auto: list[str], ref: list[str]) -> dict[str, Any]:
    a, r = succ_rows(auto), succ_rows(ref)
    differ = sorted(key for key in a if r.get(key) != a[key])
    only_ref = sorted(key for key in r if key not in a)
    return {"rows": len(a), "ref_rows": len(r), "differ": len(differ), "only_ref": len(only_ref),
            "examples": [[list(key[0]), key[1], list(a[key]), list(r[key]) if key in r else None]
                         for key in differ[:20]]}


def chain_map(V, ref: Mapping[str, Any]) -> dict[str, str]:
    """Layer id -> reference id, by (name, occurrence) along each kingdom's chain."""
    m = {}
    for kd in KINGDOMS:
        rk = dict(zip(keyed(ref["rows"][i]["name"] for i in ref["chain"][kd]), ref["chain"][kd]))
        for key, x in zip(keyed(V.nodes[x]["name"] for x in V.chain[kd]), V.chain[kd]):
            if key in rk:
                m[x] = rk[key]
    return m

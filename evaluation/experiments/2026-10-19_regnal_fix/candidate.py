"""The candidate regnal layer: ragdata's build (rules R1a-R12) on the served text layer.

Writes store reports/regnal_fix_20261019/candidate/regnal_layer.json and regnal_report.json, the
bytes ``ragdata.kg.regnal_build.regnal_files`` returns (what ``ragdata build relations`` would
store), and prints their sha256 and counts, also kept in store candidate_check.json. With
--scout it compares the layer with the scout's prototype (the fix modules run with every rule
on, R13 off) part by part: nodes, edges, fallback edges, synchronisms, conflicts and occurrence
aliases must be equal; the log may differ, and every difference is listed.

    python3 -B candidate.py [--scout PATH/fix_all.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fix_common import CANDIDATE, OUT, TEXT, dump, sha256_file, write_new

CHECK = OUT / "candidate_check.json"   # beside candidate/, which holds only the layer's two files
SCOUT_SHA = "1789c0de976cbd98241cb8ae521d5c54f84ede61290c771255eb851069750a78"
PARTS = ("nodes", "edges", "fallback_edges", "syncs", "conflicts", "occ_alias")


def build() -> dict[str, bytes]:
    from ragdata.kg.regnal_build import regnal_files
    from ragdata.store import read_layer
    return regnal_files(read_layer(TEXT))


def compare(doc: dict, scout: dict) -> dict:
    """Part-by-part equality with the scout layer; list every element that differs."""
    out = {}
    for part in (*PARTS, "log"):
        a, b = doc[part], scout[part]
        n = max(len(a), len(b))
        diffs = [{"index": i, "candidate": a[i] if i < len(a) else None, "scout": b[i] if i < len(b) else None}
                 for i in range(n) if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)]
        out[part] = {"candidate": len(a), "scout": len(b), "equal": a == b, "diffs": diffs}
    rest = sorted((set(doc) | set(scout)) - set(PARTS) - {"log"})
    out["other_keys"] = {k: doc.get(k) == scout.get(k) for k in rest}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scout", type=Path, help="the scout's fix_all.json (sha 1789c0de...)")
    args = ap.parse_args()
    files = build()
    shas = {name: write_new(CANDIDATE / name, data) for name, data in files.items()}
    res = {"candidate": str(CANDIDATE), "sha256": shas, "text": TEXT.name}
    doc = json.loads(files["regnal_layer.json"])
    res["counts"] = {k: len(doc[k]) for k in (*PARTS, "log")}
    if args.scout is not None:
        scout_sha = sha256_file(args.scout)
        cmp = compare(doc, json.loads(args.scout.read_bytes()))
        res["scout"] = {"file": str(args.scout), "sha256": scout_sha, "pinned": scout_sha == SCOUT_SHA,
                        "byte_identical": files["regnal_layer.json"] == args.scout.read_bytes(),
                        "structure_equal": all(cmp[p]["equal"] for p in PARTS)
                        and all(cmp["other_keys"].values()), "parts": cmp}
    write_new(CHECK, dump(res))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

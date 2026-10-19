"""K0-R: the candidate regnal layer against ref_layer_v2, part by part. CPU only, no model.

Reads the candidate (store candidate/regnal_layer.json, which must be the file
regnal_expect.yaml pins) through ``ragcommon.regnal.load`` (it takes the united-monarchy kingdom
'U'; experiment A's regnal.py does not) and ref_layer_v2.json through ``fix_common.ref_view``,
and writes store k0/k0r.json:

- succession rows +-1..+-3 per kingdom (target: J 0/108, I 0/102 differ);
- the chain's edge types against the reference predecessor types (target 0 differ);
- ghost nodes of Israel or Judah, no accession and no reign (target 0), fallback edges (0);
- the field conflicts (target 3) beside the reference's alt fields;
- synchronisms mapped to reference ids (target 31 the same, none missing);
- field differences reign, age, father, mother per chain king (value, or only the verse);
- S4 rows: each Judah king with an accession age, ``born_under`` and its margin, and every
  conflict alternative of his age and of the reigns on the walked path, put in one at a time
  and walked again. Data only: the S4 guard itself is another branch's.

Prints the summary; names and verse keys only, no verse text.

    python3 -B k0r.py
"""
from __future__ import annotations

import copy
import json
from typing import Any

from fix_common import (CANDIDATE, K0_DIR, KINGDOMS, REF_V2, TEXT, chain_map, compare_rows, dump, ref_view,
                        sha256_bytes, write_new)
from ragcommon import regnal  # noqa: E402  (on sys.path through fix_common)

TARGET = {"rows_differ": 0, "edge_type_differ": 0, "ghosts": 0, "fallback_edges": 0, "conflicts": 3,
          "syncs_same": 31}
FIELDS = ("reign", "age", "father", "mother")


def ref_field(row: dict, f: str) -> tuple[Any, str | None]:
    """(value, verse) of a reference row's field: reign [text, value, verse], others [value, verse]."""
    v = row.get(f)
    if not v:
        return None, None
    return (v[1], v[2]) if f == "reign" else (v[0], v[-1])


def same(f: str, a: Any, b: Any) -> bool:
    if f == "reign" and a is not None and b is not None:
        return abs(a - b) < 1e-3
    return a == b


def edge_types(V, ref: dict) -> list[dict]:
    out = []
    for kd in KINGDOMS:
        ch, rc = V.chain[kd], ref["chain"][kd]
        for i in range(1, max(len(ch), len(rc))):
            a = (ch[i - 1], ch[i]) if i < len(ch) else None
            r = (rc[i - 1], rc[i]) if i < len(rc) else None
            at = V.edge_type.get(a) if a else None
            rt = ref["edge"].get(r, (None, None))[0] if r else None
            if at != rt:
                out.append({"kingdom": kd, "pos": i, "layer": [V.nodes[x]["name"] for x in a] if a else None,
                            "layer_type": at, "ref": [ref["rows"][x]["name"] for x in r] if r else None,
                            "ref_type": rt})
    return out


def conflicts(doc: dict, m: dict, ref: dict) -> list[dict]:
    out = []
    for nid, name, f, kept, other in doc["conflicts"]:
        row = ref["rows"].get(m.get(nid), {})
        out.append({"id": nid, "ref_id": m.get(nid), "name": name, "field": f, "kept": kept, "other": other,
                    "ref_value": list(ref_field(row, f)) if row else None,
                    "ref_alt": [a for a in row.get("alt", []) if a[0] == f]})
    return out


def ref_alts_not_conflicts(doc: dict, m: dict, ref: dict) -> list[dict]:
    back = {r: a for a, r in m.items()}
    have = {(c[0], c[2]) for c in doc["conflicts"]}
    return [{"ref_id": rid, "name": row["name"], "alt": a} for rid, row in ref["rows"].items()
            for a in row.get("alt", []) if (back.get(rid), a[0]) not in have]


def syncs(V, m: dict, ref: dict) -> dict:
    auto = sorted((m.get(n, "?" + n), m.get(o, "?" + o), y, v, p) for (n, o, y, v, p) in V.syncs)
    want = sorted((rid, o, y, v, kind == "primary") for rid, row in ref["rows"].items()
                  for (o, y, v, kind) in row["sync"])
    return {"layer": len(auto), "ref": len(want), "same": sum(1 for s in auto if s in want),
            "layer_not_in_ref": [list(s) for s in auto if s not in want],
            "ref_not_in_layer": [list(s) for s in want if s not in auto]}


def field_diffs(V, m: dict, ref: dict) -> list[dict]:
    out = []
    for x, rid in m.items():
        n, row = V.nodes[x], ref["rows"][rid]
        for f in FIELDS:
            av, ap = n[f], n["prov"].get(f)
            rv, rp = ref_field(row, f)
            if not same(f, av, rv):
                kind = "value"
            elif av is not None and ap != rp:
                kind = "verse"
            else:
                continue
            out.append({"kingdom": n["kingdom"], "name": n["name"], "id": x, "ref_id": rid, "field": f,
                        "kind": kind, "layer": [av, ap], "ref": [rv, rp]})
    return out


def born(V, x: str) -> tuple[dict, list[str]]:
    """``born_under`` of x as names: the king x was born under and the margin in years, or the
    reason there is none (UNKNOWN_REIGN at a king, BEFORE_CHAIN), with the walked path."""
    res, read = regnal.born_under(V, x)
    out: dict[str, Any] = {"path": [[V.nodes[y]["name"], V.nodes[y]["reign"]] for y in read]}
    if res is None:
        out.update(result=None, margin=None)
    elif res[0] in V.nodes:
        out.update(result=V.nodes[res[0]]["name"], result_id=res[0], margin=res[1])
    else:
        out.update(result=res[0], margin=None, at=V.nodes[res[1]]["name"] if res[1] in V.nodes else None)
    return out, read


def put(V, x: str, f: str, val: Any):
    """A view with node x's field f set to val (a shallow copy; V is not changed)."""
    W = copy.copy(V)
    W.nodes = {**V.nodes, x: {**V.nodes[x], f: val}}
    return W


def s4_rows(V, doc: dict) -> list[dict]:
    alts: dict[tuple[str, str], list] = {}
    for nid, _name, f, _kept, other in doc["conflicts"]:
        alts.setdefault((nid, f), []).append(other)
    out = []
    for x in V.chain["J"]:
        n = V.nodes[x]
        if n["age"] is None:
            continue
        b, walked = born(V, x)
        row = {"name": n["name"], "id": x, "age": [n["age"], n["prov"].get("age")], **b, "alternatives": []}
        for nid, f in [(x, "age")] + [(y, "reign") for y in walked]:
            for val, verse, src in alts.get((nid, f), []):
                row["alternatives"].append({"node": V.nodes[nid]["name"], "id": nid, "field": f, "value": val,
                                            "verse": verse, "src": src, **born(put(V, nid, f, val), x)[0]})
        out.append(row)
    return out


def main() -> None:
    from ragdata.gates.regnal import load_regnal_expect
    data = (CANDIDATE / "regnal_layer.json").read_bytes()
    sha = sha256_bytes(data)
    if sha != load_regnal_expect()["layer_sha256"]:
        raise SystemExit(f"candidate {sha[:12]} is not the layer regnal_expect.yaml pins")
    ref_bytes = REF_V2.read_bytes()
    doc, ref = json.loads(data), ref_view(json.loads(ref_bytes))
    V = regnal.load(doc)
    m = chain_map(V, ref)
    rows = {kd: compare_rows([V.nodes[x]["name"] for x in V.chain[kd]],
                             [ref["rows"][r]["name"] for r in ref["chain"][kd]]) for kd in KINGDOMS}
    ghosts = [{"id": n["id"], "kingdom": n["kingdom"], "name": n["name"], "created_by": n["created_by"],
               "evidence": n["evidence"]} for n in doc["nodes"]
              if n["kingdom"] in KINGDOMS and not (n["has_acc"] or "reign" in n["fields"])]
    res = {
        "inputs": {"candidate": {"file": str(CANDIDATE / "regnal_layer.json"), "sha256": sha},
                   "ref_layer_v2": {"file": str(REF_V2), "sha256": sha256_bytes(ref_bytes)}, "text": TEXT.name},
        "chains": {"layer": V.chain_names(),
                   "ref": {kd: [ref["rows"][r]["name"] for r in ref["chain"][kd]] for kd in KINGDOMS}},
        "succ_rows": rows,
        "edge_types": edge_types(V, ref),
        "ghosts": ghosts,
        "fallback_edges": doc["fallback_edges"],
        "off_chain_kings": [{"id": x, "kingdom": n["kingdom"], "name": n["name"]} for x, n in V.nodes.items()
                            if x not in V.chain.get(n["kingdom"], [])],
        "unmapped": {"layer": [x for kd in KINGDOMS for x in V.chain[kd] if x not in m],
                     "ref": [r for kd in KINGDOMS for r in ref["chain"][kd] if r not in m.values()]},
        "conflicts": conflicts(doc, m, ref),
        "ref_alts_not_conflicts": ref_alts_not_conflicts(doc, m, ref),
        "syncs": syncs(V, m, ref),
        "field_diffs": field_diffs(V, m, ref),
        "s4_rows": s4_rows(V, doc),
    }
    got = {"rows_differ": sum(r["differ"] + r["only_ref"] for r in rows.values()),
           "edge_type_differ": len(res["edge_types"]), "ghosts": len(ghosts),
           "fallback_edges": len(doc["fallback_edges"]), "conflicts": len(doc["conflicts"]),
           "syncs_same": res["syncs"]["same"] if not res["syncs"]["ref_not_in_layer"] else -1}
    res["summary"] = {"target": TARGET, "observed": got, "met": {k: got[k] == v for k, v in TARGET.items()},
                      "rows": {kd: f"{r['differ']}/{r['rows']}" for kd, r in rows.items()},
                      "field_diffs": {k: sum(d["kind"] == k for d in res["field_diffs"]) for k in ("value", "verse")},
                      "s4_rows": len(res["s4_rows"])}
    out = write_new(K0_DIR / "k0r.json", dump(res))
    print(json.dumps({"k0r": str(K0_DIR / "k0r.json"), "sha256": out, **res["summary"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

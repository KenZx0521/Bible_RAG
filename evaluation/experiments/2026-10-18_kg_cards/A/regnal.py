"""Unified layer view of probe_C5 regnal_lib.py (load_ref, load_auto, map_auto_to_ref, born_under),
reading the store A/ copies instead of the probe directory. Read-only, CPU."""
from __future__ import annotations

import collections
from pathlib import Path

from a_common import read_json


class View:
    """nodes[id] = dict(kingdom, name, aliases, reign, age, mother, father, death, prov{field: verse})."""

    def __init__(self, label):
        self.label = label
        self.nodes, self.chain = {}, {"I": [], "J": []}
        self.syncs = []      # (node, other, year, verse, primary)
        self.edge_type = {}  # (pred, succ) -> type

    def idx(self, x):
        k = self.nodes[x]["kingdom"]
        return self.chain[k].index(x) if x in self.chain[k] else None

    def succ(self, x, k=1):
        kd, i = self.nodes[x]["kingdom"], self.idx(x)
        if i is None:
            return None
        j = i + k
        return self.chain[kd][j] if 0 <= j < len(self.chain[kd]) else None

    def names(self, x):
        n = self.nodes[x]
        return [n["name"]] + [a for a in dict.fromkeys(n["aliases"]) if a != n["name"]]


def _first(v):
    return v[0] if v else None


def load_ref(path: Path) -> View:
    K, V = read_json(path), View("ref")
    for k in K:
        prov = {f: k[f][-1] for f in ("reign", "mother", "mother_desc", "father") if k[f]}
        if k["age"]:
            prov["age"] = k["age"][1]
        if k["death"]:
            prov["death"] = k["death"][2]
        if k["pred"] and k["pred"][0]:
            prov["pred"] = k["pred"][2]
        elif k["pred"]:
            prov["founder"] = k["pred"][2]
        V.nodes[k["id"]] = dict(kingdom=k["kingdom"], name=k["name"], aliases=[a[0] for a in k["aliases"]],
                                reign=k["reign"][1] if k["reign"] else None, age=_first(k["age"]),
                                mother=_first(k["mother"]), mother_desc=_first(k["mother_desc"]),
                                father=_first(k["father"]), death=_first(k["death"]), has_acc=True, prov=prov)
        V.syncs += [(k["id"], o, y, v, kind == "primary") for (o, y, v, kind) in k["sync"]]
        if k["pred"] and k["pred"][0]:
            V.edge_type[(k["pred"][0], k["id"])] = k["pred"][1]
    for kd in ("I", "J"):
        V.chain[kd] = [k["id"] for k in K if k["kingdom"] == kd]  # file is in succession order
    return V


def _auto_chain(V, real, edges, kd):
    ch = collections.defaultdict(list)
    for e in edges:
        ch[e[0]].append(e[1])
    has_pred = {e[1] for e in edges}
    ids = sorted([i for i in real if V.nodes[i]["kingdom"] == kd], key=lambda i: V.nodes[i]["order"])
    seq, seen = [], set()

    def dfs(x):
        if x in seen:
            return
        seen.add(x)
        seq.append(x)
        for c in sorted(ch.get(x, []), key=lambda i: V.nodes[i]["order"]):
            if V.nodes[c]["kingdom"] == kd:
                dfs(c)
    for r in [i for i in ids if i not in has_pred]:
        dfs(r)
    for i in ids:
        dfs(i)
    return seq


def load_auto(path: Path, use_fallback: bool = True) -> View:
    A, V = read_json(path), View("auto")
    real = set()
    for n in A["nodes"]:
        f = n["fields"]
        if not (n["has_acc"] or "reign" in f):
            continue  # ghost node: mentioned only, no accession or reign evidence
        real.add(n["id"])
        V.nodes[n["id"]] = dict(kingdom=n["kingdom"], name=n["name"], aliases=n["aliases"],
                                reign=f.get("reign", [None])[0], age=f.get("age", [None])[0],
                                mother=f.get("mother", [None])[0], mother_desc=f.get("mother_desc", [None])[0],
                                father=f.get("father", [None])[0], death=f.get("death", [None])[0],
                                has_acc=n["has_acc"], order=n["order"], prov={k: v[1] for k, v in f.items()},
                                evidence=n["evidence"])
    edges = [e for e in A["edges"] if e[0] in real and e[1] in real]
    if use_fallback:
        edges += [e for e in A["fallback_edges"] if e[0] in real and e[1] in real]
    for e in edges:
        V.edge_type[(e[0], e[1])] = e[2]
    for kd in ("I", "J"):
        V.chain[kd] = _auto_chain(V, real, edges, kd)
    prim = {}
    for (nid, oth, y, v, kind) in A["syncs"]:
        if nid in real and oth in real:
            p = kind == "acc" and nid not in prim
            if p:
                prim[nid] = True
            V.syncs.append((nid, oth, y, v, p))
    return V


def map_auto_to_ref(VA: View, VR: View) -> dict:
    """auto id -> ref id: by reign/age/sync provenance verse votes, then (kingdom, name or alias, order)."""
    refkey = collections.defaultdict(set)
    for rid, n in VR.nodes.items():
        for f in ("reign", "age"):
            if f in n["prov"]:
                refkey[(f, n["prov"][f])].add(rid)
    for (rid, o, y, v, p) in VR.syncs:
        refkey[("sync", v)].add(rid)
    m = {}
    for aid, n in VA.nodes.items():
        votes = collections.Counter()
        for f in ("reign", "age"):
            if f in n["prov"]:
                for rid in refkey.get((f, n["prov"][f]), []):
                    votes[rid] += 1
        for (nid, o, y, v, p) in VA.syncs:
            if nid == aid:
                for rid in refkey.get(("sync", v), []):
                    votes[rid] += 1
        if votes:
            m[aid] = votes.most_common(1)[0][0]
    used = set(m.values())
    for aid, n in VA.nodes.items():
        if aid in m:
            continue
        c = [rid for rid, r in VR.nodes.items() if rid not in used and r["kingdom"] == n["kingdom"] and
             (n["name"] == r["name"] or n["name"] in r["aliases"])]
        if c:
            m[aid] = c[0]
            used.add(c[0])
    return m


def born_under(V: View, x, variant="cum"):
    """Walk back the predecessor chain from x's accession age. (king, margin years) | ('UNKNOWN_REIGN', y)
    | ('BEFORE_CHAIN', None) | None; also returns the nodes read."""
    n, read = V.nodes[x], []
    if n["age"] is None or V.idx(x) is None:
        return None, read
    rem, kd = float(n["age"]), n["kingdom"]
    for j in range(V.idx(x) - 1, -1, -1):
        y = V.chain[kd][j]
        read.append(y)
        r = V.nodes[y]["reign"]
        if r is None:
            return ("UNKNOWN_REIGN", y), read
        if variant == "nonacc" and r >= 1:
            r = r - 1
        if rem < r:
            return (y, min(rem, r - rem)), read
        rem -= r
    return ("BEFORE_CHAIN", None), read


def acc_sync(V: View, x):
    return [(o, y, v) for (n, o, y, v, p) in V.syncs if n == x and p]


def fmt_reign(r):
    if r is None:
        return "?"
    if r >= 1:
        return "%d年" % round(r)
    if r >= 0.07:
        return "%d個月" % round(r * 12)
    return "%d日" % round(r * 365)

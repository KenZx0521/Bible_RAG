"""K0 diff: every content difference of the served regnal layer (relations@a04b67a301dc, experiment
A's 932d2242) against the candidate, for the independent check and Kay's spot check.

Ids are renumbered by the fixes, so nodes are paired by content, in three passes:
(kingdom, name, first evidence verse); then (kingdom, name) with a shared evidence verse; then
the name with a shared evidence verse (the kingdom changed). A node left over is removed or
added. Each difference carries the verse keys it rests on and, in the store JSON only, those
verses' text from the text layer (the repo and stdout get keys and names, never verse text).

Writes store k0/k0_diff.json and prints the counts per kind.

    python3 -B k0_diff.py
"""
from __future__ import annotations

import collections
import json
from typing import Any

from fix_common import CANDIDATE, K0_DIR, OLD_LAYER, OLD_SHA, dump, read_pinned, sha256_bytes, text_rows, write_new

NODE_ATTRS = ("kingdom", "aliases", "pending", "created_by", "has_acc")


def pair_nodes(old: list[dict], new: list[dict]) -> list[tuple[dict | None, dict | None, str]]:
    """(old node, new node, pairing rule) for every node of either layer."""
    rules = (("kingdom_name_first_verse", lambda a, b: a["kingdom"] == b["kingdom"] and a["name"] == b["name"]
              and a["evidence"][0] == b["evidence"][0]),
             ("kingdom_name_shared_verse", lambda a, b: a["kingdom"] == b["kingdom"] and a["name"] == b["name"]
              and set(a["evidence"]) & set(b["evidence"])),
             ("name_shared_verse", lambda a, b: a["name"] == b["name"] and set(a["evidence"]) & set(b["evidence"])))
    left, right, pairs = list(old), list(new), []
    for rule, fits in rules:
        for a in list(left):
            b = next((b for b in right if fits(a, b)), None)
            if b is not None:
                pairs.append((a, b, rule))
                left.remove(a)
                right.remove(b)
    pairs += [(a, None, "removed") for a in left] + [(None, b, "added") for b in right]
    return sorted(pairs, key=lambda p: (p[1] or p[0])["order"] + (0.5 if p[1] is None else 0))


def labels(pairs) -> tuple[dict, dict, list[str]]:
    """old id -> label, new id -> label: 'name(kingdom)', '#k' for the k-th of one name."""
    seen: collections.Counter = collections.Counter()
    lo, ln, order = {}, {}, []
    for a, b, _ in pairs:
        n = b or a
        base = f"{n['name']}({n['kingdom'] or '-'})"
        seen[base] += 1
        lab = base if seen[base] == 1 else f"{base}#{seen[base]}"
        order.append(lab)
        if a:
            lo[a["id"]] = lab
        if b:
            ln[b["id"]] = lab
    return lo, ln, order


def verse_of(log_entry: list) -> str | None:
    key = log_entry[1] if len(log_entry) > 1 else None
    if isinstance(key, str) and key.startswith("fn:"):
        return key[3:].split("#")[0]
    return key if isinstance(key, str) else None


class Diff:
    def __init__(self, texts: dict[str, str]):
        self.texts, self.items = texts, []

    def add(self, kind: str, node: str | None, what: dict[str, Any], verses) -> None:
        keys = sorted({v for v in verses if v})
        self.items.append({"kind": kind, "node": node, **what,
                           "basis": [{"key": k, "text": self.texts.get(k)} for k in keys]})


def node_diffs(D: Diff, pairs, lo, ln) -> None:
    for a, b, rule in pairs:
        if a is None or b is None:
            n = a or b
            D.add("node_" + rule, (ln if b else lo)[n["id"]],
                  {"id": n["id"], "created_by": n["created_by"], "fields": n["fields"], "evidence": n["evidence"]},
                  n["evidence"])
            continue
        lab = ln[b["id"]]
        if a["id"] != b["id"]:
            D.add("id_renumbered", lab, {"old": a["id"], "new": b["id"], "pair_rule": rule}, [])
        for f in NODE_ATTRS:
            if a[f] != b[f]:
                D.add("node_attr", lab, {"field": f, "old": a[f], "new": b[f], "pair_rule": rule},
                      [a["evidence"][0], b["evidence"][0]] + [v[1] for v in b["fields"].values()
                                                              if f == "kingdom" and v is not None])
        for f in sorted(set(a["fields"]) | set(b["fields"])):
            fa, fb = a["fields"].get(f), b["fields"].get(f)
            if fa != fb:
                D.add("field", lab, {"field": f, "old": fa, "new": fb, "pair_rule": rule},
                      [fa[1] if fa else None, fb[1] if fb else None])
        if a["evidence"] != b["evidence"]:
            D.add("evidence", lab, {"old": a["evidence"], "new": b["evidence"], "pair_rule": rule},
                  set(a["evidence"]) ^ set(b["evidence"]))


def edge_diffs(D: Diff, old: dict, new: dict, lo, ln) -> None:
    eo = {(lo[e[0]], lo[e[1]]): e[2:] for e in old["edges"]}
    en = {(ln[e[0]], ln[e[1]]): e[2:] for e in new["edges"]}
    for p in sorted(set(eo) | set(en)):
        if eo.get(p) != en.get(p):
            D.add("edge", f"{p[0]}->{p[1]}", {"old": eo.get(p), "new": en.get(p)},
                  [(eo.get(p) or [None, None])[1], (en.get(p) or [None, None])[1]])
    fo = {(lo[e[0]], lo[e[1]]) for e in old["fallback_edges"]}
    fn = {(ln[e[0]], ln[e[1]]) for e in new["fallback_edges"]}
    for kind, pairs, doc, lab in (("fallback_removed", fo - fn, new, ln), ("fallback_added", fn - fo, new, ln)):
        for p in sorted(pairs):
            into = [e for e in doc["edges"] if lab[e[1]] == p[1]]
            D.add(kind, f"{p[0]}->{p[1]}", {"typed_edges_into_successor": [[lab[e[0]], *e[2:]] for e in into]},
                  [e[3] for e in into])


def rest_diffs(D: Diff, old: dict, new: dict, lo, ln) -> None:
    so = [(lo[s[0]], lo[s[1]], *s[2:]) for s in old["syncs"]]
    sn = [(ln[s[0]], ln[s[1]], *s[2:]) for s in new["syncs"]]
    for kind, a, b in (("sync_removed", so, sn), ("sync_added", sn, so)):
        for s in a:
            if s not in b:
                D.add(kind, s[0], {"sync": list(s)}, [s[3]])
    co = [(lo[c[0]], c[2], c[3][:2], c[4][:2]) for c in old["conflicts"]]
    cn = [(ln[c[0]], c[2], c[3][:2], c[4][:2]) for c in new["conflicts"]]
    for kind, a, b in (("conflict_removed", co, cn), ("conflict_added", cn, co)):
        for c in a:
            if c not in b:
                D.add(kind, c[0], {"field": c[1], "first": c[2], "second": c[3]}, [c[2][1], c[3][1]])
    lgo = [json.dumps(x, ensure_ascii=False) for x in old["log"]]
    lgn = [json.dumps(x, ensure_ascii=False) for x in new["log"]]
    for kind, a, b, doc in (("log_removed", lgo, lgn, old), ("log_added", lgn, lgo, new)):
        for s, entry in zip(a, doc["log"]):
            if s not in b:
                D.add(kind, None, {"entry": entry}, [verse_of(entry)])
    oo = {(k, w, lo[v]) for k, w, v in old["occ_alias"]}
    on = {(k, w, ln[v]) for k, w, v in new["occ_alias"]}
    for kind, a, b in (("occ_alias_removed", oo, on), ("occ_alias_added", on, oo)):
        for k, w, lab in sorted(a - b):
            D.add(kind, lab, {"word": w}, [k])


def main() -> None:
    from ragdata.gates.regnal import load_regnal_expect
    old_bytes = read_pinned(OLD_LAYER, OLD_SHA)
    new_bytes = read_pinned(CANDIDATE / "regnal_layer.json", load_regnal_expect()["layer_sha256"])
    old, new = json.loads(old_bytes), json.loads(new_bytes)
    pairs = pair_nodes(old["nodes"], new["nodes"])
    lo, ln, order = labels(pairs)
    D = Diff(text_rows())
    node_diffs(D, pairs, lo, ln)
    edge_diffs(D, old, new, lo, ln)
    rest_diffs(D, old, new, lo, ln)
    counts = dict(collections.Counter(d["kind"] for d in D.items))
    by_node: dict[str, list[int]] = collections.defaultdict(list)
    for i, d in enumerate(D.items):
        for lab in (d["node"] or "").split("->"):
            if lab:
                by_node[lab].append(i)
    content = [k for k in counts if k not in ("id_renumbered", "log_removed", "log_added")]
    res = {"inputs": {"old": {"file": str(OLD_LAYER), "sha256": sha256_bytes(old_bytes)},
                      "new": {"file": str(CANDIDATE / "regnal_layer.json"), "sha256": sha256_bytes(new_bytes)}},
           "pairing": {"rules": dict(collections.Counter(r for _, _, r in pairs)),
                       "pairs": [{"label": lab, "old": a["id"] if a else None, "new": b["id"] if b else None,
                                  "rule": r} for lab, (a, b, r) in zip(order, pairs)]},
           "counts": {"old": {k: len(old[k]) for k in ("nodes", "edges", "fallback_edges", "syncs", "conflicts",
                                                       "log", "occ_alias")},
                      "new": {k: len(new[k]) for k in ("nodes", "edges", "fallback_edges", "syncs", "conflicts",
                                                       "log", "occ_alias")},
                      "diffs": counts},
           "nodes_with_content_changes": sorted({lab for i, d in enumerate(D.items) if d["kind"] in content
                                                 for lab in (d["node"] or "").split("->") if lab},
                                                key=order.index),
           "by_node": {lab: by_node[lab] for lab in order if lab in by_node},
           "diffs": D.items}
    out = write_new(K0_DIR / "k0_diff.json", dump(res))
    print(json.dumps({"k0_diff": str(K0_DIR / "k0_diff.json"), "sha256": out, "pairing": res["pairing"]["rules"],
                      "counts": res["counts"], "nodes_with_content_changes": res["nodes_with_content_changes"]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

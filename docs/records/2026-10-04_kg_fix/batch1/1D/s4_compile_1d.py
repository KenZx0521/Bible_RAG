"""S4: quantify the 1D compile against the batch-0 chain projection (== staging).

Outputs s4_compile_1d.json. Pure JSONL; no DB.
"""
import hashlib, json, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ro import OUT, ROOT, jsonl, dump
from compile_sim import (chain, compile_1d, replay, load_titles, protected, curated_alias_pairs)
import export_event_registry as exr
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
from kg_validate.checks_r import _is_junk_name


def r10(nodes, exempt=frozenset()):
    owners, canon = defaultdict(set), defaultdict(set)
    for e, n in nodes.items():
        canon[(n["canonical_name"] or "").strip()].add(e)
        for a in n["aliases"]:
            if (e, a) not in exempt:
                owners[a.strip()].add(e)
    return sorted(a for a, w in owners.items() if len(w) > 1 or canon.get(a, set()) - w)


def registry(nodes, edges):
    anchors = defaultdict(set)
    chunk_parent = {r["id"]: r["parent_id"] for r in jsonl(OUT / "chunks.jsonl")}
    for lab, sid, eid in edges:
        anchors[eid].add(chunk_parent.get(sid, sid) if lab == "Chunk" else sid)
    rows = [{"id": e, "name": n["canonical_name"], "aliases": n["aliases"], "anchors": sorted(anchors.get(e, ()))}
            for e, n in nodes.items() if n["type"] == "Event"]
    return exr.registry_from_rows(rows, exr.curated_event_ids(), exr.event_keywords(), exr.load_book_order())


def h10(nodes, edges):
    keys = sorted(f"{l}|{s}|{e}" for l, s, e in edges if nodes.get(e, {}).get("type") == "Event")
    return len(keys), hashlib.sha256("\n".join(keys).encode()).hexdigest()


def find_by_name(nodes, name, k=5):
    hits = [(n.get("mention_count") or 0, e, n["canonical_name"]) for e, n in nodes.items()
            if name in n["canonical_name"] or any(name in a for a in n["aliases"])]
    return sorted(hits, reverse=True)[:k]


def analyse(policy, scope):
    b_nodes, b_edges, b_rep, _ = chain()
    nodes, edges, rows, mig, drop, stats = compile_1d(id_policy=policy, dictname_scope=scope)
    per, ch = load_titles()
    rep, titles = replay(nodes, edges, per, ch)
    prot = protected()
    res = {"policy": policy, "dictname_scope": list(scope), "stats": dict(stats)}
    res["entities"] = {"before": len(b_nodes), "after": len(nodes)}
    res["by_type_before"] = dict(Counter(n["type"] for n in b_nodes.values()))
    res["by_type_after"] = dict(Counter(n["type"] for n in nodes.values()))
    res["id_migration"] = {"rows": len(mig), "by_op_rule_type": dict(Counter(f"{m['op']}|{m['rule']}|{m['type']}" for m in mig)),
                           "by_op": dict(Counter(m["op"] for m in mig))}
    res["protected_in_migration"] = sorted(m["old_id"] for m in mig if m["old_id"] in prot)
    res["mentions"] = {"edges_before": len(b_edges), "edges_after": len(edges),
                       "lost_keys": len(set(b_edges) - set(edges)), "new_keys": len(set(edges) - set(b_edges))}
    # relations.jsonl impact
    remap = {m["old_id"]: m["new_id"] for m in mig}
    rel = list(jsonl(OUT / "relations.jsonl"))
    dropped_rel = [r for r in rel if remap.get(r["head_id"], 0) is None or remap.get(r["tail_id"], 0) is None]
    rew = [r for r in rel if r not in dropped_rel and (r["head_id"] in remap or r["tail_id"] in remap)]
    keys_after = Counter()
    selfloops = 0
    for r in rel:
        if r in dropped_rel:
            continue
        h, t = remap.get(r["head_id"], r["head_id"]), remap.get(r["tail_id"], r["tail_id"])
        if h == t:
            selfloops += 1
        keys_after[(h, r["relation"], t)] += 1
    keys_before = Counter((r["head_id"], r["relation"], r["tail_id"]) for r in rel)
    res["relations_jsonl"] = {"rows": len(rel), "dropped_rows": len(dropped_rel),
                              "dropped_by_rule": dict(Counter(next(m["rule"] for m in mig if m["old_id"] in (r["head_id"], r["tail_id"]) and m["op"] == "drop") for r in dropped_rel)),
                              "rewritten_rows": len(rew), "self_loops_after": selfloops,
                              "distinct_triples_before": len(keys_before), "distinct_triples_after": len(keys_after)}
    # descriptions
    res["replay"] = {k: len(v) for k, v in rep.items()}
    res["replay_stale"] = rep["stale"]
    mig_ids = {m["old_id"] for m in mig}
    res["replay_missing_explained"] = sum(1 for e in rep["missing"] if e in mig_ids)
    res["replay_missing_unexplained"] = [e for e in rep["missing"] if e not in mig_ids]
    res["descriptions_lost_by_type"] = dict(Counter(
        (b_nodes[e]["type"] if e in b_nodes else "?") for e in rep["stale"] + rep["missing"]
        if (b_nodes.get(e, {}).get("description") or "")))
    # gates
    res["H4_whitespace_names"] = sum(1 for n in nodes.values() if n["canonical_name"] != n["canonical_name"].strip())
    res["ids_with_whitespace"] = sum(1 for e in nodes if any(c.isspace() for c in e))
    res["R8"] = dict(Counter(n["type"] for n in nodes.values() if n["type"] in ("Event", "Object", "Theme")
                             and n["canonical_name"] != "這是基督嗎？" and _is_junk_name(n["canonical_name"])))
    cur = curated_alias_pairs()
    res["R10_all"] = r10(nodes)
    res["R10_excl_curated"] = r10(nodes, cur)
    res["R10_before_all"] = len(r10(b_nodes))
    res["ambiguous_aliases"] = {e: n["ambiguous_aliases"] for e, n in nodes.items() if n.get("ambiguous_aliases")}
    names = defaultdict(set)
    for n in nodes.values():
        names[n["canonical_name"].strip()].add(n["type"])
    bnames = defaultdict(set)
    for n in b_nodes.values():
        bnames[n["canonical_name"].strip()].add(n["type"])
    res["R5_cross_type_names"] = {"before": sum(1 for v in bnames.values() if len(v) > 1), "after": sum(1 for v in names.values() if len(v) > 1)}
    hb, ha = h10(b_nodes, b_edges), h10(nodes, edges)
    res["H10"] = {"before": hb[0], "after": ha[0], "same_fingerprint": hb[1] == ha[1]}
    ev_lost = Counter(e for l, s, e in set(b_edges) - set(edges) if b_nodes.get(e, {}).get("type") == "Event")
    res["H10_event_mentions_removed_by_id"] = dict(ev_lost)
    res["event_mentions_removed_protected"] = sorted(e for e in ev_lost if e in prot)
    reg_b, reg_a = registry(b_nodes, b_edges), registry(nodes, edges)
    res["registry"] = {"events_before": len(reg_b["events"]), "events_after": len(reg_a["events"]),
                       "identical": exr._comparable(reg_a) == exr._comparable(reg_b),
                       "equals_committed": exr._comparable(reg_a) == exr._comparable(json.load(open(ROOT / "backend/data/event_registry.json")))}
    res["event_extraction_method_null"] = sum(1 for n in nodes.values() if n["type"] == "Event" and not n.get("extraction_method"))
    res["H7_prefix_mismatch"] = sorted(e for e, n in nodes.items() if e.split(":")[0] != n["type"].lower())
    res["find_by_name_liwei_before"] = find_by_name(b_nodes, "利未")
    res["find_by_name_liwei_after"] = find_by_name(nodes, "利未")
    res["migration_rows"] = mig
    res["drop_list"] = {e: r for e, r in sorted(drop.items())}
    return res


if __name__ == "__main__":
    out = {}
    for policy in ("keep", "rename"):
        for scope in (("Event",), ("Event", "Object", "Theme")):
            key = f"{policy}|{'+'.join(scope)}"
            r = analyse(policy, scope)
            out[key] = r
            short = {k: v for k, v in r.items() if k not in ("migration_rows", "drop_list", "replay_stale", "ambiguous_aliases")}
            print("=====", key)
            print(json.dumps(short, ensure_ascii=False)[:4000])
    dump("s4_compile_1d.json", out)

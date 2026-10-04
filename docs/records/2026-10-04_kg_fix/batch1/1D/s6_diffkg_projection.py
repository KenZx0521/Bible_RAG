"""S6: 1D's expected diff_kg sections (prod-equivalent chain projection vs 1D compile).

Relations: projection of Step 6.1 over output/relations.jsonl only (apoc.merge
first-row-wins per (head,type,tail)); 10.3 co-occurrence is retired by 1A and
not modelled. Pure JSONL.
"""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ro import OUT, jsonl, dump
from compile_sim import chain, compile_1d, replay, load_titles, titles_for
from scripts.relation_extraction import desc_generator as dg

b_nodes, b_edges, _, _ = chain()
nodes, edges, rows, mig, drop, stats = compile_1d(id_policy="keep", dictname_scope=("Event", "Object", "Theme"))
per, ch = load_titles()
rep, titles = replay(nodes, edges, per, ch)
# inheritance through merges (proposal): survivor without own hit takes a merged id's entry at the same titles_sha
cache = dg.load_cache(OUT / "frozen/descriptions.jsonl")
inherited = []
for m in mig:
    if m["op"] != "merge":
        continue
    s, l = m["new_id"], m["old_id"]
    sha = dg.titles_sha(titles.get(s, []))
    if sha not in cache.get(s, {}) and sha in cache.get(l, {}) and not nodes[s].get("description_inherited"):
        nodes[s]["description"] = cache[l][sha]["description"]; nodes[s]["description_inherited"] = l
        inherited.append((s, l))
# stale P/P/G -> hidden (D5): base description for P/P/G is "" already; E/O/T keep extraction text

out = {}
lab = lambda ns: Counter(n["type"] for n in ns.values())
lb, la = lab(b_nodes), lab(nodes)
out["labels"] = {k: la[k] - lb[k] for k in sorted(set(lb) | set(la)) if la[k] != lb[k]}
out["labels"]["Entity"] = len(nodes) - len(b_nodes)
def mkey(es):
    c = Counter()
    for (l, s, e), p in es.items():
        c[f"{l} source={p.get('source', '-') if p else '-'}"] += 1
    return c
mb, ma = mkey(b_edges), mkey(edges)
out["mentions"] = {k: ma[k] - mb[k] for k in sorted(set(mb) | set(ma)) if ma[k] != mb[k]}
out["relationships_MENTIONS"] = len(edges) - len(b_edges)
# relations projection
def project(nodeset, remap):
    first = {}
    for r in jsonl(OUT / "relations.jsonl"):
        h, t = remap.get(r["head_id"], r["head_id"]), remap.get(r["tail_id"], r["tail_id"])
        if h is None or t is None or h not in nodeset or t not in nodeset:
            continue
        first.setdefault((h, r["relation"], t), r)
    return first
rb = project(set(b_nodes), {})
ra = project(set(nodes), {m["old_id"]: m["new_id"] for m in mig})
cnt = lambda f: Counter(f"{k[1]} phase={v['extraction_phase']} source=-" for k, v in f.items())
cb, ca = cnt(rb), cnt(ra)
out["ee_edges"] = {k: ca[k] - cb[k] for k in sorted(set(cb) | set(ca)) if ca[k] != cb[k]}
out["ee_total"] = {"before": len(rb), "after": len(ra)}
out["self_loops_after"] = sum(1 for k in ra if k[0] == k[2])
rt = lambda f: Counter(k[1] for k in f)
out["relationships_semantic"] = {k: rt(ra)[k] - rt(rb)[k] for k in set(rt(rb)) | set(rt(ra)) if rt(ra)[k] != rt(rb)[k]}
# entity-level sections
gone = sorted(set(b_nodes) - set(nodes)); new = sorted(set(nodes) - set(b_nodes))
out["entity_ids"] = {"only_a": len(gone), "only_b": len(new), "explained_by_id_migration": sum(1 for g in gone if g in {m['old_id'] for m in mig})}
desc_diff = [e for e in set(nodes) & set(b_nodes) if (nodes[e].get("description") or "") != (b_nodes[e].get("description") or "")]
out["descriptions"] = {"n": len(desc_diff),
                       "emptied_stale": sorted(e for e in desc_diff if not nodes[e].get("description")),
                       "filled_inherited": sorted(e for e in desc_diff if nodes[e].get("description_inherited")),
                       "other": sorted(e for e in desc_diff if nodes[e].get("description") and not nodes[e].get("description_inherited"))}
al_diff = {e: (b_nodes[e]["aliases"], nodes[e]["aliases"]) for e in set(nodes) & set(b_nodes)
           if sorted(set(nodes[e]["aliases"])) != sorted(set(b_nodes[e]["aliases"]))}
out["aliases"] = {"n": len(al_diff), "lost_to_ambiguous": {e: v for e, v in al_diff.items() if nodes[e].get("ambiguous_aliases")},
                  "gained": {e: v for e, v in al_diff.items() if not nodes[e].get("ambiguous_aliases")}}
out["replay"] = {k: len(v) for k, v in rep.items()}
out["inherited"] = len(inherited)
ppg = ("Person", "Place", "Group")
out["ppg_descriptions"] = {"before": sum(1 for n in b_nodes.values() if n["type"] in ppg and n.get("description")),
                           "after": sum(1 for n in nodes.values() if n["type"] in ppg and n.get("description"))}
out["dict_name_events_after"] = sorted(e for e, n in nodes.items() if n["type"] == "Event" and n["canonical_name"] in __import__("s2_junk_stop").dict_names())
print(json.dumps({k: v for k, v in out.items() if k not in ("aliases",)}, ensure_ascii=False, indent=1)[:5000])
print("aliases lost_to_ambiguous:", json.dumps(out["aliases"]["lost_to_ambiguous"], ensure_ascii=False))
print("aliases gained:", len(out["aliases"]["gained"]), json.dumps(dict(list(out["aliases"]["gained"].items())[:12]), ensure_ascii=False))
dump("s6_diffkg_projection.json", out)

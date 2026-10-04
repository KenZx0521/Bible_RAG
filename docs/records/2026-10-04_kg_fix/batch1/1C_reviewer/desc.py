import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, hashlib, collections
from edges import *
G = json.load(open("graphs.json"))
T = {(t["lab"], t["id"]): t["title"] for t in G["titles"]}
def titles_sha(ts):
    return hashlib.sha256(json.dumps(list(ts or []), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
def titles_by_entity(edge_keys):
    per = collections.defaultdict(set)
    for (lab, sid, eid) in edge_keys:
        t = T.get((lab, sid))
        if t: per[eid].add(t)
    return {e: sorted(s)[:6] for e, s in per.items()}
cache = collections.defaultdict(dict)
for l in open(BIBLE_RAG_ROOT + "/output/frozen/descriptions.jsonl"):
    d = json.loads(l); cache[d["entity_id"]][d["titles_sha"]] = d
stg = G["staging"]
all_edges_stg = [(m["lab"], m["sid"], m["eid"]) for m in stg["mentions"]]
ents_stg = {e["eid"] for e in stg["entities"]}
def classify(edge_keys, ents):
    tb = titles_by_entity(edge_keys)
    st, mi = [], []
    for eid in cache:
        if eid not in ents: mi.append(eid); continue
        if titles_sha(tb.get(eid, [])) not in cache[eid]: st.append(eid)
    return st, mi
s0, m0 = classify(all_edges_stg, ents_stg)
print("staging self-check stale", len(s0), "missing", len(m0), "cache", len(cache))
# final: replace PPG non-curated edges by simulated ones
F, _ = edges_of("rrows_final.jsonl")
ppg_types = {"Person", "Place", "Group"}
keep = [(m["lab"], m["sid"], m["eid"]) for m in stg["mentions"] if not (m["etype"] in ppg_types and not m["cur"])]
new_edges = keep + list(F.keys())
ents_new = {e["eid"] for e in stg["entities"] if e["t"] not in ppg_types} | {json.loads(l)["entity_id"] for l in open("rents_final.jsonl")}
# curated ppg edge endpoints must exist
s1, m1 = classify(new_edges, ents_new)
print("final stale", len(s1), "missing", len(m1))
ws = lambda e: any(c.isspace() or c == "　" for c in e)
print("missing ws", sum(ws(e) for e in m1), "missing non-ws", sorted(e for e in m1 if not ws(e)))
print("stale sample", sorted(s1)[:60])
# carry-over: missing ws whose stripped twin id exists and has no own cache entry and sha matches
import sys; sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts")
tb = titles_by_entity(new_edges)
carry = 0; twin_has_desc = 0; no_twin = 0
for e in m1:
    if not ws(e): continue
    pre, name = e.split(":", 1)
    # twin id: recompute via pinyin of stripped canonical
    from pypinyin import lazy_pinyin
    cn = [x for x in G["staging"]["entities"] if x["eid"] == e][0]["name"]
    tid = f"{pre}:{''.join(lazy_pinyin(cn.strip()))}"
    if tid not in ents_new: no_twin += 1; continue
    if tid in cache: twin_has_desc += 1; continue
    if titles_sha(tb.get(tid, [])) in cache[e]: carry += 1
print("ws missing: carry-over exact", carry, "twin already has desc", twin_has_desc, "no twin", no_twin)
json.dump({"stale": sorted(s1), "missing": sorted(m1)}, open("r_desc.json", "w"), ensure_ascii=False)

"""Why is each cached description stale/missing after 1C?  Attribute with the chain
steps: an entity is charged to the first step whose edge set changes its titles."""
import json, sys, collections, re
sys.path.insert(0, ".")
from edgelib import *
from ner_sim_geo import is_geo_context
titles = load_titles(); texts = load_texts()
g = json.load(open("graph_staging.json"))
stg_types = {e["eid"]: e["el"] for e in g["entities"]}; stg_name = {e["eid"]: e["name"] for e in g["entities"]}
other = [(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if not (m["el"] in PPG and not m["curated"])]
cache = collections.defaultdict(set)
for l in open(f"{ROOT}/frozen/descriptions.jsonl"):
    d = json.loads(l); cache[d["entity_id"]].add(d["titles_sha"])
def ctx_of(r):
    t = texts[r["source_id"]]["text"]; s, e = r["start_pos"], r["end_pos"]
    a, b = max(0, s - 30), min(len(t), e + 30)
    return ("..." if a > 0 else "") + t[a:b] + ("..." if b < len(t) else "")
def edges(step):
    rows = [json.loads(l) for l in open(f"rows_S{step}.jsonl")]
    E = edges_first_wins(rows)
    if step < 5:
        keep = {r["source_id"].split(":v:")[0] for r in rows if r["entity_id"] == "place:dan" and is_geo_context(ctx_of(r))}
        E = {k: v for k, v in E.items() if not (k[2] == "place:dan" and k[1] not in keep)}
    return set(E), {r["entity_id"] for r in rows}
stg_E = {(m["sl"], m["sid"], m["eid"]) for m in g["mentions"] if m["el"] in PPG and not m["curated"]}
steps = [("S0_dict_drift+tiebreak", 0), ("S1_ckip_idx", 1), ("S2_region(book removed + ckip context)", 2), ("S3_xref_title", 3), ("S4_normalize", 4), ("S5_dan", 5)]
state_titles = titles_of(other + list(stg_E), titles); state_ids = set(stg_types)
first_cause = {}
ppg_cached = [e for e in cache if stg_types.get(e) in PPG]
for name, s in steps:
    E, ids = edges(s)
    T = titles_of(other + list(E), titles)
    all_ids = (set(stg_types) - {e for e, t in stg_types.items() if t in PPG}) | ids
    for eid in ppg_cached:
        if eid in first_cause: continue
        if eid not in all_ids: first_cause[eid] = (name, "missing")
        elif titles_sha(T.get(eid, [])) not in cache[eid]: first_cause[eid] = (name, "stale")
c = collections.Counter(first_cause.values())
for k, v in sorted(c.items()): print(k, v)
# split S2 stale into: lost only book-region edges vs other
E1, _ = edges(1); E2, _ = edges(2)
rows1 = collections.defaultdict(list)
for l in open("rows_S1.jsonl"):
    r = json.loads(l); rows1[edge_key(r)].append(r)
reg = lambda r: "book" if r["start_pos"] < texts[r["source_id"]]["title_start"] else "other"
s2 = [e for e, (n, k) in first_cause.items() if n.startswith("S2")]
book_only_change = 0
for eid in s2:
    rem = [k for k in E1 - E2 if k[2] == eid]; add = [k for k in E2 - E1 if k[2] == eid]
    if not add and rem and all(all(reg(r) == "book" for r in rows1[k]) for k in rem): book_only_change += 1
print("S2-charged:", len(s2), "of which only lost book-region edges:", book_only_change)
missing_ws = sum(1 for e, (n, k) in first_cause.items() if k == "missing" and stg_name[e] != stg_name[e].strip())
print("missing with whitespace name:", missing_ws)
json.dump({e: list(v) for e, v in first_cause.items()}, open("stale_causes.json", "w"), ensure_ascii=False, indent=0)
big = sorted((e for e in first_cause), key=lambda e: -max((m["mc"] or 0) for m in g["entities"] if m["eid"] == e))[:25]
mc = {e["eid"]: e["mc"] for e in g["entities"]}
print("highest-mc affected:", [f"{stg_name[e]}({first_cause[e][1]},{first_cause[e][0][:3]},mc={mc[e]})" for e in sorted(first_cause, key=lambda e: -(mc[e] or 0))[:30]])

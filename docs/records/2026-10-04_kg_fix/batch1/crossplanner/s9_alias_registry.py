"""Would 1D's alias-ambiguity rule (R10: alias owned by >=2 entities or equal to another
entity's canonical -> ambiguous_aliases) strip a registry trigger? Read-only."""
import sys, os, json, pickle, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
from export_event_registry import curated_event_ids, event_keywords
D = os.path.dirname(os.path.abspath(__file__))
kg = pickle.load(open(f"{D}/graph_staging.pkl", "rb"))["kg"]
owners = collections.defaultdict(set); canon = collections.defaultdict(set)
for eid, r in kg.entities.items():
    canon[(r["canonical_name"] or "").strip()].add(eid)
    for a in r["aliases"] if isinstance(r["aliases"], list) else []:
        owners[a.strip()].add(eid)
conflict = {a for a, who in owners.items() if len(who) > 1 or canon.get(a, set()) - who}
cur = curated_event_ids(); kw = event_keywords()
reg = json.load(open("/home/kenzx0521/Bible_RAG/backend/data/event_registry.json"))
trig = {(e["id"], t) for e in reg["events"] for t in e["triggers"]}
hit = []
for eid in cur:
    r = kg.entities.get(eid)
    if not r: continue
    for a in r["aliases"] or []:
        if a.strip() in conflict:
            others = sorted((owners[a.strip()] | canon.get(a.strip(), set())) - {eid})
            hit.append((eid, r["canonical_name"], a, (eid, a) in trig, others[:4]))
print("R10 conflicting aliases total:", len(conflict))
print("conflicting aliases on curated events:", len(hit), "| of which registry triggers:", sum(h[3] for h in hit))
for h in hit: print(" ", h)

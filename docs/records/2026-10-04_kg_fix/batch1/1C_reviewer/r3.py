import json, collections
from edges import *
G = json.load(open("graphs.json"))["staging"]
E = {e["eid"]: e for e in G["entities"]}
FE = {json.loads(l)["entity_id"]: json.loads(l) for l in open("rents_final.jsonl")}
def foreign(edges, ents):
    out = collections.defaultdict(set)
    for eid, span in edges:
        ent = ents.get(eid)
        if ent is None: continue
        sp = (span or "").strip()
        if not sp: continue
        al = ent["aliases"] if isinstance(ent["aliases"], list) else []
        if sp not in {(ent["name"] or "").strip(), *(a.strip() for a in al)}:
            out[eid].add(sp)
    return out
s = foreign([(m["eid"], m["span"]) for m in G["mentions"]], E)
print("staging R3 foreign_surface_entities", len(s), "person", sum(1 for e in s if E[e]["t"] == "Person"))
F, Frows = edges_of("rrows_final.jsonl")
own = {"pericope": "pericope", "chunk": "chunk"}
def rep(k, rs):
    lab = k[0]
    def key(r):
        own_text = (lab == "Chunk" and r["source_type"] == "chunk") or (lab == "Pericope" and r["source_type"] == "pericope")
        return (0 if own_text else 1, 0 if r["region"] == "body" else 1, r["start_pos"], r["source_id"])
    return min(rs, key=key)
ents2 = {}
for eid, e in E.items():
    if e["t"] not in ("Person", "Place", "Group"): ents2[eid] = e
for eid, e in FE.items():
    old = E.get(eid)
    ents2[eid] = {"name": e["canonical_name"], "aliases": (old["aliases"] if old else e["aliases"]) or [], "t": e["type"]}
other = [(m["eid"], m["span"]) for m in G["mentions"] if not (m["etype"] in ("Person","Place","Group") and not m["cur"])]
for name, chooser in (("C8 representative", rep), ("first-row-wins", lambda k, rs: rs[0]), ("min start_pos", lambda k, rs: min(rs, key=lambda r: r["start_pos"]))):
    edges = other + [(k[2], chooser(k, rs)["text_span"]) for k, rs in Frows.items()]
    f = foreign(edges, ents2)
    print(name, "R3 foreign_surface_entities", len(f), "person", sum(1 for e in f if ents2[e]["t"] == "Person"),
          "new vs staging", len(set(f) - set(s)), "fixed", len(set(s) - set(f)))
    if name == "C8 representative": print(sorted(set(f) - set(s))[:40])

import sys, os, json, pickle, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
R = "/home/kenzx0521/Bible_RAG"; D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); edges, ents = g["edges"], g["ents"]
s = pickle.load(open(f"{D}/sim1c1d.pkl", "rb")); d = json.load(open(f"{D}/sim1c1d_desc.json"))
name = {e["eid"]: e["name"] for e in ents}
remap = s["remap"]
mi = set(d["missing_1c"])
print("missing_1c that are whitespace ids:", len(mi & set(remap)), "others:", sorted(mi - set(remap))[:20])
twin = {e for e, t in remap.items() if t in name}
print("  merged into existing twin:", len(mi & twin), " renamed (no twin):", len(mi & (set(remap) - twin)))
print("stale_1c sample:", [(e, name.get(e)) for e in d["stale_1c"][:15]])
for e in ("person:er", "place:yue", "place:la", "place:you", "place:ha", "place:fu", "place:e"):
    rows = [(x["sid"], x["span"], x["start_pos"]) for x in edges if x["eid"] == e]
    print(e, name.get(e), len(rows), rows[:6])

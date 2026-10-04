import sys, os, pickle, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
D = os.path.dirname(os.path.abspath(__file__))
kg = pickle.load(open(f"{D}/graph_staging.pkl", "rb"))["kg"]
clean = pickle.load(open(f"{D}/sim1a_clean.pkl", "rb"))["clean"]
ch = collections.defaultdict(list)
for r in clean:
    if r["type"] == "FATHER_OF":
        ch[r["tail"]].append((r["head"], r["extraction_phase"], r["source_pericope_id"]))
print("children", len(ch), "multi", sum(len(v) > 1 for v in ch.values()))
for t, v in ch.items():
    if len(v) > 1: print(t, v)

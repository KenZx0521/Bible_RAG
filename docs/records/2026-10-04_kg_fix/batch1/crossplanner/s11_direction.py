"""1A gate 'same-type directed relation without inverse name, n>=30: share head<tail in 0.3-0.7' on the 1A sim."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import sys, os, pickle, collections
sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts")
D = os.path.dirname(os.path.abspath(__file__))
kg = pickle.load(open(f"{D}/graph_staging.pkl", "rb"))["kg"]
clean = pickle.load(open(f"{D}/sim1a_clean.pkl", "rb"))["clean"]
st = collections.defaultdict(lambda: [0, 0])
for r in clean:
    if kg.label(r["head"]) == kg.label(r["tail"]):
        k = (r["type"], kg.label(r["head"])); st[k][0] += 1; st[k][1] += r["head"] < r["tail"]
for k, (n, lt) in sorted(st.items(), key=lambda x: -x[1][0]):
    if n >= 10: print(k, n, f"head<tail {lt/n:.2f}", "phase4" )

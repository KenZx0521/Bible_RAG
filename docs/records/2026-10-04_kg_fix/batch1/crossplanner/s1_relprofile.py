import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import pickle, collections, os, sys
import sys; sys.path.insert(0, BIBLE_RAG_ROOT + "/scripts")
D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); kg = g["kg"]
c = collections.Counter()
for r in kg.relations:
    c[(r["extraction_phase"], (r["notes"] or "")[:13], r["backfilled"], r["source"], r["curated"])] += 1
for k, v in c.most_common(30): print(k, v)

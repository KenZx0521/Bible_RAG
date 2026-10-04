"""Offline: compute TSK pericope pairs and overlap with markdown/supplementary edges in neo4j_relationships.jsonl (no DB)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import sys, json
from collections import defaultdict
from pathlib import Path
ROOT = Path(BIBLE_RAG_ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util
spec = importlib.util.spec_from_file_location("tsk", ROOT / "scripts/import_tsk_crossrefs.py")
tsk = importlib.util.module_from_spec(spec); spec.loader.exec_module(tsk)
vmap = tsk.build_verse_map(ROOT / "output/embedding_queue.jsonl")
pairs = set()
with open(ROOT / "output/cross_references_tsk.txt", encoding="utf-8") as f:
    next(f)
    for line in f:
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 3: continue
        try: votes = int(cols[2])
        except ValueError: continue
        if votes < 0: continue
        fr = tsk.parse_ref(cols[0])
        if not fr: continue
        fp = vmap.get(fr)
        if not fp: continue
        for tp in tsk.expand_to_range(cols[1], vmap):
            if tp != fp: pairs.add((fp, tp))
print("tsk unique pairs", len(pairs))
existing = defaultdict(set)
for line in open(ROOT / "output/neo4j_relationships.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r["type"] == "CROSS_REFERENCES":
        existing[r["properties"].get("source")].add((r["start"], r["end"]))
for src, s in existing.items():
    print(src, "edges", len(s), "shadowing tsk pairs", len(s & pairs))
print("total shadowed", len(set().union(*existing.values()) & pairs))

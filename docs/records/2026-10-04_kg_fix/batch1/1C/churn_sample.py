"""Fixed-seed sample of the non-book S1->S2 churn for eyeballing (seed 20261004)."""
import json, sys, random, collections
sys.path.insert(0, ".")
from edgelib import *
texts = load_texts()
def rows(p): return [json.loads(l) for l in open(p)]
R1, R2 = rows("rows_S1.jsonl"), rows("rows_S2.jsonl")
def by_edge(R):
    d = collections.defaultdict(list)
    for r in R: d[edge_key(r)].append(r)
    return d
B1, B2 = by_edge(R1), by_edge(R2)
region = lambda r: ("book" if r["start_pos"] < texts[r["source_id"]]["title_start"] else
                    "title" if r["start_pos"] < texts[r["source_id"]]["body_start"] else "body")
rem = sorted(k for k in set(B1) - set(B2) if {region(r) for r in B1[k]} != {"book"})
add = sorted(set(B2) - set(B1))
rng = random.Random(20261004)
for name, keys, B in (("REMOVED", rem, B1), ("ADDED", add, B2)):
    print("==", name, len(keys))
    for k in rng.sample(keys, 25):
        r = B[k][0]; t = texts[r["source_id"]]["text"]; s = r["start_pos"]
        print(f"  {k[2]:28s} {r['text_span']!r:10s} {t[max(0, s - 10):s]}【{t[s:r['end_pos']]}】{t[r['end_pos']:r['end_pos'] + 8]}")

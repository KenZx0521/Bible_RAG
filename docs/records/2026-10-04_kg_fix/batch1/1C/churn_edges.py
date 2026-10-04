"""Edge-level split of the S1->S2 change: book-region-only vs CKIP body churn, by the
granularity/length of the rows that supported the edge."""
import json, sys, collections
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
def kind(rs):
    ks = set()
    for r in rs:
        t = texts[r["source_id"]]
        ks.add(("verse" if r["source_type"] == "verse" else "long" if len(t["text"]) > 510 else "short"))
    return "+".join(sorted(ks))
def region(r):
    t = texts[r["source_id"]]
    return "book" if r["start_pos"] < t["title_start"] else "title" if r["start_pos"] < t["body_start"] else "body"
rem = set(B1) - set(B2); add = set(B2) - set(B1)
c = collections.Counter()
for k in rem:
    regs = {region(r) for r in B1[k]}
    c[("removed", "book_only" if regs == {"book"} else "has_title_or_body", kind(B1[k]))] += 1
for k in add:
    c[("added", "-", kind(B2[k]))] += 1
for k, v in sorted(c.items()): print(k, v)
names = {}
for r in R1 + R2: names.setdefault(r["entity_id"], r["text_span"])
dict_like = lambda eid: eid
print("removed non-book edges whose entity has >=5 rows in S1:", sum(1 for k in rem if {region(r) for r in B1[k]} != {"book"} and sum(1 for r in R1 if r["entity_id"] == k[2]) >= 5) if False else "skipped")

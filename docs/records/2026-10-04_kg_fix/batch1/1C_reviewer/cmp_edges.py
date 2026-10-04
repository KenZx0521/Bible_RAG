import json, collections, sys
from edges import *
S = staging_ppg()
F, Frows = edges_of("rrows_final.jsonl")
print("staging PPG non-curated edges", len(S), "final", len(F))
gone = set(S) - set(F); new = set(F) - set(S)
print("removed", len(gone), "added", len(new), "kept", len(set(S) & set(F)))
books = {b["id"]: b["name"] for b in map(json.loads, open(f"{ROOT}/books.jsonl"))}
# R1 in staging (first row start < len(book))
r1 = [k for k, m in S.items() if m["sp"] is not None and m["sp"] < len(books[k[1].split(":")[0]])]
print("staging R1", len(r1))
# classify removed
cur = json.load(open("graphs.json"))["staging"]
txt = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(f"{ROOT}/embedding_queue.jsonl")}
ent_new = {json.loads(l)["entity_id"] for l in open("rents_final.jsonl")}
cls = collections.Counter()
for k in gone:
    eid = k[2]
    if eid not in ent_new:
        cls["entity_gone:" + ("ws" if any(c.isspace() or c == '　' for c in eid) else "other")] += 1
    else:
        cls["entity_kept"] += 1
print(cls)
# place:dan
print("dan staging", sorted(k for k in S if k[2] == "place:dan") == sorted(k for k in F if k[2] == "place:dan"), sum(1 for k in F if k[2] == "place:dan"))
print("make", sum(1 for k in F if k[2] == "person:make"), "lujia", sum(1 for k in F if k[2] == "person:lujia"), "matai", sum(1 for k in F if k[2] == "person:matai"))
# entities
Sent = {e["eid"]: e for e in cur["entities"] if e["t"] in ("Person", "Place", "Group")}
print("PPG entities staging", len(Sent), "final", len(ent_new), "gone", len(set(Sent) - ent_new), "new", len(ent_new - set(Sent)))
print("gone non-ws:", sorted(e for e in set(Sent) - ent_new if not any(c.isspace() or c == '　' for c in e)))

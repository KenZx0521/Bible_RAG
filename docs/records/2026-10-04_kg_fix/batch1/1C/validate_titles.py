"""Check: titles_sha computed from staging edges + neo4j_nodes titles == cache titles_sha (replay stale 0)."""
import json, sys, collections
sys.path.insert(0, ".")
from edgelib import *
g = json.load(open("graph_staging.json"))
titles = load_titles()
# also compare graph titles to file titles
mism = sum(1 for m in g["mentions"] if titles.get((m["sl"], m["sid"])) != m["title"])
print("edge title vs neo4j_nodes title mismatches:", mism)
T = titles_of([(m["sl"], m["sid"], m["eid"]) for m in g["mentions"]], titles)
cache = collections.defaultdict(set)
types = {e["eid"]: e["el"] for e in g["entities"]}
for l in open(f"{ROOT}/frozen/descriptions.jsonl"):
    d = json.loads(l); cache[d["entity_id"]].add(d["titles_sha"])
c = collections.Counter()
for eid, shas in cache.items():
    ok = titles_sha(T.get(eid, [])) in shas
    c[(types.get(eid), ok)] += 1
print(sorted(c.items(), key=str))

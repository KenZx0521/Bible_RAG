"""Offline: simulate Step 6 R1 pair mining on (a) pre-P0 MENTIONS (pericope-type mentions only) and (b) current-code import (pericope + verse remap); compare with checkpoint."""
import json, sys
from itertools import combinations
from collections import defaultdict
from pathlib import Path
ROOT = Path("/home/kenzx0521/Bible_RAG")
sys.path.insert(0, str(ROOT))
from scripts.relation_extraction.schema_loader import RelationSchema
schema = RelationSchema.load(ROOT / "config/relations/biblical_relations.yaml")
ents = {}
for l in open(ROOT / "output/entities.jsonl"):
    r = json.loads(l); ents[r["entity_id"]] = r["type"]
peri_nodes = set()
for l in open(ROOT / "output/neo4j_nodes.jsonl"):
    r = json.loads(l)
    if "Pericope" in r["labels"]: peri_nodes.add(r["properties"]["id"])
generic = {json.loads(l)["entity_id"] for l in open(ROOT / "output/backups/generic_events_20260706_102830.jsonl")}
dan_deleted = {json.loads(l)["source_id"] for l in open(ROOT / "output/backups/dan_mentions_20260706_102830.jsonl")}
pre, cur = defaultdict(set), defaultdict(set)
for l in open(ROOT / "output/entity_mentions.jsonl"):
    r = json.loads(l)
    sid, st, eid = r["source_id"], r.get("source_type") or "pericope", r["entity_id"]
    if st == "pericope" and sid in peri_nodes:
        pre[sid].add(eid)
    if st == "verse" or ":v:" in sid:
        sid = sid.split(":v:")[0]; st = "pericope"
    if st == "pericope" and sid in peri_nodes:
        if eid in generic: continue
        if eid == "place:dan" and sid in dan_deleted: continue
        cur[sid].add(eid)
def mine(m):
    keys = set()
    for pid, es in m.items():
        if len(es) < 2: continue
        n = 0
        for a, b in combinations(sorted(es), 2):
            if not (schema.candidates_for(ents[a], ents[b]) or schema.candidates_for(ents[b], ents[a])):
                continue
            keys.add(f"{min(a,b)}|{max(a,b)}|{pid}"); n += 1
            if n >= 80: break
    return keys
ck = {json.loads(l)["pair_key"] for l in open(ROOT / "output/relations_checkpoint.jsonl")}
kp, kc = mine(pre), mine(cur)
print("checkpoint", len(ck))
print("sim pre-P0 pairs", len(kp), "overlap ck", len(kp & ck))
print("sim current pairs", len(kc), "overlap ck", len(kc & ck), "NEW (need R4)", len(kc - ck), "GONE", len(ck - kc))

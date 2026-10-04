"""Check: edges(entity_mentions.jsonl NER half) minus 10.2 'dan' == staging P/P/G NER edges."""
import json, sys
sys.path.insert(0, ".")
from edgelib import *
from ner_sim_geo import is_geo_context
g = json.load(open("graph_staging.json"))
ents = {json.loads(l)["entity_id"]: json.loads(l)["type"] for l in open(f"{ROOT}/entities.jsonl")}
rows = [json.loads(l) for l in open(f"{ROOT}/entity_mentions.jsonl")]
ner_rows = [r for r in rows if ents[r["entity_id"]] in PPG]
keep = {r["source_id"].split(":v:")[0] for r in ner_rows if r["entity_id"] == "place:dan" and is_geo_context(r.get("context", ""))}
E = edges_first_wins(ner_rows)
E = {k: v for k, v in E.items() if not (k[2] == "place:dan" and k[1] not in keep)}
S = {(m["sl"], m["sid"], m["eid"]): m for m in g["mentions"] if m["el"] in PPG and not m["curated"]}
print("model", len(E), "staging", len(S), "model-staging", len(set(E) - set(S)), "staging-model", len(set(S) - set(E)))
pos_diff = sum(1 for k in set(E) & set(S) if (E[k].get("start_pos"), E[k]["text_span"]) != (S[k]["sp"], S[k]["span"]))
print("same key, different first row (start_pos/span):", pos_diff)

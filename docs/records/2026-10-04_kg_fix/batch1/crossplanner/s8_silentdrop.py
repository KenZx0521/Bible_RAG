import sys, os, json, pickle, collections
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); ents = {e["eid"]: e for e in g["ents"]}
gen = set()
from cleanup_noise_entities import GENERIC_EVENT_STOPLIST
miss = collections.Counter(); ex = []
for l in open("/home/kenzx0521/Bible_RAG/output/relations.jsonl"):
    r = json.loads(l)
    gone = [x for x in (r["head_id"], r["tail_id"]) if x not in ents]
    if gone:
        miss[r["extraction_phase"]] += 1
        if len(ex) < 6: ex.append((r["head_canonical"], r["relation"], r["tail_canonical"], gone))
print("relations.jsonl rows with an endpoint absent from the graph:", sum(miss.values()), dict(miss)); print(ex)

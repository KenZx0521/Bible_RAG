"""Offline simulation of 1A's Step 6.05 core rules on the staging graph (read-only inputs).
Rules simulated: drop phase-2 rule triples, phase-5 inverses, 10.3 co-occurrence (D2),
LLM Event-Event edges; provenance gate (source pericope or its chunks MENTIONS both ends;
priors exempt); domain/range per biblical_relations.yaml with the final node label.
Not simulated: anchored_rules additions (~77 per proto), prior-contradiction drops of
same-type phase-4 edges (75 flagged only)."""
import sys, os, pickle, json, collections, dataclasses
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
from kg_validate.registry import Context, load_baseline, load_probes, run_checks
from relation_extraction.schema_loader import RelationSchema
R = "/home/kenzx0521/Bible_RAG"
D = os.path.dirname(os.path.abspath(__file__))
g = pickle.load(open(f"{D}/graph_staging.pkl", "rb")); kg = g["kg"]
schema = RelationSchema.load(__import__("pathlib").Path(f"{R}/config/relations/biblical_relations.yaml"))
ctx = Context(baseline=load_baseline(f"{R}/config/kg_quality_baseline"), probes=load_probes(f"{R}/config/kg_probes.yaml"))

def support_from_live(kg):
    return {(kg.pericope_of(m), m["entity_id"]) for m in kg.mentions}

def support_from_jsonl():
    """entity_mentions.jsonl as 6.05 would read it before 1C/1D exist (no 10.2 dan cleanup)."""
    chunk_parent = kg.chunk_parent
    s = set()
    for l in open(f"{R}/output/entity_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l); sid = m["source_id"]
        pid = chunk_parent.get(sid, sid) if m.get("source_type") == "chunk" else sid.split(":v:")[0]
        s.add((pid, m["entity_id"]))
    return s

def postprocess(rels, support, label):
    out, drops = [], collections.Counter()
    for r in rels:
        ph, notes = r["extraction_phase"], r["notes"] or ""
        if ph == 3:
            out.append(r); continue
        if ph == 2: drops["phase2_rule"] += 1; continue
        if ph == 5 and notes.startswith("cooccurrence"): drops["10.3_cooccurrence"] += 1; continue
        if ph == 5: drops["phase5_inverse"] += 1; continue
        if label(r["head"]) == "Event" and label(r["tail"]) == "Event": drops["llm_event_event"] += 1; continue
        pid = r["source_pericope_id"]
        if not ((pid, r["head"]) in support and (pid, r["tail"]) in support):
            drops["provenance_gate"] += 1; continue
        e = schema.get(r["type"])
        if e is None or not e.accepts_pair(label(r["head"]), label(r["tail"])):
            drops["domain_range"] += 1; continue
        out.append(r)
    return out, drops

def score(rels, tag):
    k2 = dataclasses.replace(kg, relations=rels)
    for a in ("relation_keys",):
        k2.__dict__.pop(a, None)
    res = run_checks(k2, ctx, {"H3", "H9", "R6"})
    m = {cid: res[cid].metrics for cid in res}
    print(tag, "edges", len(rels), json.dumps({c: {k: v for k, v in mm.items() if k != "failing_probes"} for c, mm in m.items()}, ensure_ascii=False))
    return m

base = score(kg.relations, "BASE(staging)")
sup_live = support_from_live(kg)
clean, drops = postprocess(kg.relations, sup_live, kg.label)
print("drops(live mentions):", dict(drops))
score(clean, "1A sim, gate on post-10.2 mentions")
print(" by type:", dict(collections.Counter(r["type"] for r in clean).most_common()))
sup_jsonl = support_from_jsonl()
clean_j, drops_j = postprocess(kg.relations, sup_jsonl, kg.label)
print("drops(jsonl mentions, no dan cleanup):", dict(drops_j))
score(clean_j, "1A sim, gate on raw entity_mentions.jsonl")
extra = {(r["head"], r["type"], r["tail"]) for r in clean_j} - {(r["head"], r["type"], r["tail"]) for r in clean}
print(" kept only because JSONL still has the 10.2-deleted MENTIONS:", sorted(extra))
# label used for domain/range: what if 6.05 reads entities.jsonl types (group:yehehua still Group)?
jtype = {}
for l in open(f"{R}/output/entities.jsonl", encoding="utf-8"):
    e = json.loads(l); jtype[e["entity_id"]] = e["type"]
clean_t, drops_t = postprocess(kg.relations, sup_live, lambda eid: jtype.get(eid))
print("drops(domain/range with entities.jsonl types):", dict(drops_t))
score(clean_t, "1A sim, domain/range on JSONL types (yehehua=Group)")
pickle.dump({"clean": clean}, open(f"{D}/sim1a_clean.pkl", "wb"))

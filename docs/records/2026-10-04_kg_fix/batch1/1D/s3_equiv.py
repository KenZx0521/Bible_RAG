"""S3: does a compile-time projection of the batch-0 chain (Kc + replay moved
offline) reproduce staging Neo4j (7688, built by the real scripts)?  And how
do staging PG / Qdrant differ from it?  Read-only.
"""
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from ro import neo4j, read, pg_rows, dump
from compile_sim import chain

nodes, edges, rep, titles = chain()
print("replay:", {k: len(v) for k, v in rep.items()})

drv = neo4j("staging")
ents = read(drv, """MATCH (e:Entity) RETURN e.entity_id AS id, [l IN labels(e) WHERE l<>'Entity'] AS ls,
  e.canonical_name AS name, e.aliases AS aliases, coalesce(e.description,'') AS d, e.extraction_method AS m,
  e.mention_count AS mc""")
men = read(drv, """MATCH (s)-[m:MENTIONS]->(e:Entity) RETURN [l IN labels(s) WHERE l IN ['Pericope','Chunk']][0] AS lab,
  s.id AS sid, e.entity_id AS eid""")
drv.close()
st = {r["id"]: r for r in ents}
diff = Counter(); samples = {}
def hit(k, s):
    diff[k] += 1
    samples.setdefault(k, []).append(s) if len(samples.get(k, [])) < 5 else None
for e in set(st) - set(nodes): hit("only_staging", e)
for e in set(nodes) - set(st): hit("only_sim", e)
for e in set(st) & set(nodes):
    a, b = nodes[e], st[e]
    if [a["type"]] != b["ls"]: hit("type", (e, a["type"], b["ls"]))
    if a["canonical_name"] != b["name"]: hit("canonical", e)
    if sorted(set(a["aliases"])) != sorted(set(b["aliases"] or [])): hit("aliases_set", (e, a["aliases"], b["aliases"]))
    elif list(a["aliases"]) != list(b["aliases"] or []): hit("aliases_order", (e, a["aliases"], b["aliases"]))
    if (a.get("description") or "") != b["d"]: hit("description", (e, (a.get("description") or "")[:30], b["d"][:30]))
    if a.get("mention_count") != b["mc"]: hit("mention_count", (e, a.get("mention_count"), b["mc"]))
sim_keys = set(edges)
st_keys = {(r["lab"], r["sid"], r["eid"]) for r in men}
diff["mentions_only_sim"] = len(sim_keys - st_keys); diff["mentions_only_staging"] = len(st_keys - sim_keys)
samples["mentions_only_sim"] = sorted(sim_keys - st_keys)[:5]; samples["mentions_only_staging"] = sorted(st_keys - sim_keys)[:5]
print("sim vs staging Neo4j:", dict(diff))
for k, v in samples.items():
    if diff.get(k): print("  ", k, v)

# staging PG vs the same projection (what Step 3 + 10.x left in PG)
pgr = {r["entity_id"]: r for r in pg_rows("staging", "SELECT entity_id, type, canonical_name, aliases, coalesce(description,'') d FROM entities")}
pd = Counter(); ps = {}
for e in set(pgr) & set(nodes):
    a, b = nodes[e], pgr[e]
    if sorted(set(a["aliases"])) != sorted(set(b["aliases"] or [])):
        pd["aliases"] += 1; ps.setdefault("aliases", []).append((e, a["aliases"], b["aliases"]))
    if (a.get("description") or "") != b["d"]:
        pd["description"] += 1
        pd["description_" + a["type"]] += 1
print("sim vs staging PG:", dict(pd)); print("   aliases diffs:", ps.get("aliases"))
dump("s3_equiv.json", {"replay": {k: len(v) for k, v in rep.items()}, "neo4j_diff": dict(diff),
                       "neo4j_samples": samples, "pg_diff": dict(pd), "pg_alias_diffs": ps.get("aliases")})

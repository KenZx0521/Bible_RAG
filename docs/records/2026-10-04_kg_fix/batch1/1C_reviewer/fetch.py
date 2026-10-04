"""READ-only fetch of staging (7688) and prod (7687) graph pieces needed by the review sims."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import os, sys, json
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + "/.env")
def run(target, q, **kw):
    uri = "bolt://localhost:7687" if target == "prod" else "bolt://localhost:7688"
    d = GraphDatabase.driver(uri, auth=(env.get("NEO4J_USER", "neo4j"), env.get("NEO4J_PASSWORD")))
    with d.session(default_access_mode=READ_ACCESS) as s:
        rows = [r.data() for r in s.run(q, **kw)]
    d.close(); return rows
out = {}
for tgt in ("staging", "prod"):
    g = {}
    g["mentions"] = run(tgt, """MATCH (s)-[m:MENTIONS]->(e:Entity)
      RETURN CASE WHEN s:Chunk THEN 'Chunk' ELSE 'Pericope' END AS lab, s.id AS sid, e.entity_id AS eid,
             [l IN labels(e) WHERE l<>'Entity'][0] AS etype, m.start_pos AS sp, m.end_pos AS ep, m.text_span AS span,
             m.source_granularity AS g, m.source AS src, m.curated AS cur""")
    g["entities"] = run(tgt, """MATCH (e:Entity) RETURN e.entity_id AS eid, [l IN labels(e) WHERE l<>'Entity'][0] AS t,
             e.canonical_name AS name, e.mention_count AS mc, e.aliases AS aliases, e.description AS desc""")
    g["rels"] = run(tgt, """MATCH (a:Entity)-[r]->(b:Entity) WHERE NOT type(r) IN ['MENTIONS','CROSS_REFERENCES']
             RETURN a.entity_id AS h, type(r) AS t, b.entity_id AS tl, r.source_pericope_id AS pid, r.extraction_phase AS ph""")
    out[tgt] = g
    print(tgt, {k: len(v) for k, v in g.items()})
nodes = run("staging", "MATCH (p:Pericope) RETURN 'Pericope' AS lab, p.id AS id, p.title AS title UNION ALL MATCH (c:Chunk) RETURN 'Chunk' AS lab, c.id AS id, c.pericope_title AS title")
out["titles"] = nodes
json.dump(out, open("graphs.json", "w"), ensure_ascii=False)

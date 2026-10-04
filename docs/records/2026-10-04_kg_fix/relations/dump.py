import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, os
from dotenv import load_dotenv
from neo4j import GraphDatabase
load_dotenv(BIBLE_RAG_ROOT + '/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
Q = """
MATCH (a:Entity)-[r]->(b:Entity) WHERE NOT type(r) IN ['MENTIONS','CROSS_REFERENCES']
RETURN elementId(r) AS rid, type(r) AS rel, a.entity_id AS h, b.entity_id AS t, a.canonical_name AS hn, b.canonical_name AS tn,
 [l IN labels(a) WHERE l<>'Entity'][0] AS ht, [l IN labels(b) WHERE l<>'Entity'][0] AS tt, properties(r) AS props
"""
def tx(t):
    return [dict(x) for x in t.run(Q)]
with d.session(default_access_mode='READ') as s:
    rows = s.execute_read(tx)
json.dump(rows, open('edges.json','w'), ensure_ascii=False)
print(len(rows))

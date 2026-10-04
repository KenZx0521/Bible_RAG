import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, os
from dotenv import load_dotenv
from neo4j import GraphDatabase
load_dotenv(BIBLE_RAG_ROOT + '/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
Q = """
MATCH (a:Entity)-[r]->(b:Entity) WHERE NOT type(r) IN ['MENTIONS','CROSS_REFERENCES']
RETURN type(r) AS rel, a.entity_id AS h, b.entity_id AS t, a.canonical_name AS hn, b.canonical_name AS tn,
 labels(a) AS hl, labels(b) AS tl, properties(r) AS props
"""
with d.session(default_access_mode='READ') as s:
    rows = s.execute_read(lambda tx: [dict(x) for x in tx.run(Q)])
json.dump(rows, open('edges.json','w'), ensure_ascii=False)
print(len(rows))

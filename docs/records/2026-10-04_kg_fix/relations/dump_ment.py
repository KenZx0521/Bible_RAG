import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, os
from dotenv import load_dotenv
from neo4j import GraphDatabase
load_dotenv(BIBLE_RAG_ROOT + '/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
Q = """MATCH (p:Pericope)-[r:MENTIONS]->(e:Entity) RETURN p.id AS pid, e.entity_id AS eid, e.canonical_name AS n, [l IN labels(e) WHERE l<>'Entity'][0] AS t, coalesce(r.backfilled,false) AS bf"""
with d.session(default_access_mode='READ') as s:
    rows = s.execute_read(lambda t: [dict(x) for x in t.run(Q)])
json.dump(rows, open('ment.json','w'), ensure_ascii=False); print(len(rows))

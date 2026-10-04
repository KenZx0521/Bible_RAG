import os, json
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS
load_dotenv('/home/kenzx0521/Bible_RAG/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
ids = json.load(open('ids268.json'))
def q(c, **p):
    with d.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(c, **p)])
print(q("""MATCH (e:Entity) WHERE e.entity_id IN $ids
OPTIONAL MATCH (e)<-[m:MENTIONS]-() WITH e, count(m) AS mc, sum(CASE WHEN m.text_span IS NOT NULL THEN 1 ELSE 0 END) AS ts
RETURN count(e) AS nodes, sum(mc) AS mentions, sum(ts) AS with_span""", ids=ids))
print(q("""MATCH (e:Entity)-[r]-(o:Entity) WHERE e.entity_id IN $ids AND type(r)<>'MENTIONS'
WITH DISTINCT r RETURN count(r) AS rels, sum(CASE WHEN r.source_pericope_id IS NOT NULL AND r.source_pericope_id<>'' THEN 1 ELSE 0 END) AS with_src""", ids=ids))
print(q("MATCH (a:Entity)-[r]->(b:Entity) RETURN count(r) AS all_entity_rels"))
# curated ids intersection
reg=json.load(open('/home/kenzx0521/Bible_RAG/backend/data/event_registry.json'))
print(type(reg), list(reg.keys())[:10] if isinstance(reg,dict) else len(reg))

import json, os
from dotenv import load_dotenv
from neo4j import GraphDatabase
load_dotenv('/home/kenzx0521/Bible_RAG/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
with d.session(default_access_mode='READ') as s:
    rows = s.execute_read(lambda t: [dict(x) for x in t.run("MATCH (e:Entity) RETURN e.entity_id AS id, e.canonical_name AS n, [l IN labels(e) WHERE l<>'Entity'][0] AS t, e.aliases AS aliases")])
json.dump(rows, open('entities.json','w'), ensure_ascii=False)
print(len(rows))

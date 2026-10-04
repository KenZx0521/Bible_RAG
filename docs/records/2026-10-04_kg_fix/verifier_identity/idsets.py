import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, uuid, os
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS
load_dotenv(BIBLE_RAG_ROOT + '/.env')
d = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
with d.session(default_access_mode=READ_ACCESS) as s:
    n4={r['id'] for r in s.execute_read(lambda tx: list(tx.run("MATCH (e:Entity) RETURN e.entity_id AS id")))}
pg=set(open('pg_ids.txt').read().split('\n'))-{''}
pts=json.load(open('q.json'))['result']['points']
qd={p['payload']['entity_id'] for p in pts}
uu=sum(1 for p in pts if p['id']==str(uuid.uuid5(uuid.NAMESPACE_URL,'entity:'+p['payload']['entity_id'])))
print(len(n4),len(pg),len(qd),'n4-pg',len(n4-pg),'pg-n4',len(pg-n4),'n4-qd',len(n4-qd),'qd-n4',len(qd-n4),'uuid ok',uu,len(pts))

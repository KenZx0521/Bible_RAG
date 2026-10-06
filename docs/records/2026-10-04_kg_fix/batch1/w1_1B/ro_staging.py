"""READ-only: staging (7688) xref profile + K10 mention_count."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
Q = {
 'xref': "MATCH (:Pericope)-[x:CROSS_REFERENCES]->(:Pericope) RETURN x.source AS source, x.curated AS curated, x.tsk AS tsk, count(*) AS n",
 'mc': "MATCH (e:Entity) WHERE e.entity_id IN ['event:shanshangbaoxun','person:yeteluo','event:baoluoxushuguizhujingguo','event:saoluodezhuanbian','person:liuer'] RETURN e.entity_id AS id, e.mention_count AS mc ORDER BY id",
}
for name, uri in (('prod','bolt://localhost:7687'),('staging','bolt://localhost:7688')):
    d = GraphDatabase.driver(uri, auth=auth)
    with d.session(default_access_mode=READ_ACCESS) as s:
        for k, q in Q.items():
            print(name, k, s.execute_read(lambda tx: [r.data() for r in tx.run(q)]))
    d.close()

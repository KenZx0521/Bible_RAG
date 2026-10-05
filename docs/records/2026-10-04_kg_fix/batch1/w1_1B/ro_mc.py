"""READ-only: per-entity mention_count, prod vs staging (what a diff_kg mention_count section would print)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
Q = "MATCH (e:Entity) RETURN e.entity_id AS id, e.mention_count AS mc"
out = {}
for name, uri in (('prod','bolt://localhost:7687'),('staging','bolt://localhost:7688')):
    d = GraphDatabase.driver(uri, auth=auth)
    with d.session(default_access_mode=READ_ACCESS) as s:
        out[name] = {r['id']: r['mc'] for r in s.execute_read(lambda tx: [r.data() for r in tx.run(Q)])}
    d.close()
a, b = out['prod'], out['staging']
diff = sorted((k, a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k))
print('entities', len(a), len(b), 'mention_count diffs', len(diff))
for row in diff[:30]: print(row)
print('null mc prod', sum(v is None for v in a.values()), 'staging', sum(v is None for v in b.values()))
print('types', {type(v).__name__ for v in a.values()})
json.dump(diff, open('mc_diff_prod_vs_stg0.json', 'w'), ensure_ascii=False)

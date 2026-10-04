"""Reviewer: READ-only property-level diff prod vs staging beyond diff_kg (node props of
Entity/Pericope/Chunk/Book, MENTIONS props, CROSS_REFERENCES props)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from collections import Counter
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
Q = {
 'entity': "MATCH (e:Entity) RETURN e.entity_id AS k, properties(e) AS p, labels(e) AS l",
 'pericope': "MATCH (e:Pericope) RETURN e.id AS k, properties(e) AS p, labels(e) AS l",
 'chunk': "MATCH (e:Chunk) RETURN e.id AS k, properties(e) AS p, labels(e) AS l",
 'mentions': "MATCH (s)-[m:MENTIONS]->(e:Entity) RETURN coalesce(s.id,s.entity_id)+'>'+e.entity_id AS k, properties(m) AS p, [] AS l",
}
data = {}
for name, uri in (('prod', 'bolt://localhost:7687'), ('staging', 'bolt://localhost:7688')):
    d = GraphDatabase.driver(uri, auth=auth)
    data[name] = {}
    with d.session(default_access_mode=READ_ACCESS) as s:
        for q, cy in Q.items():
            data[name][q] = {r['k']: (r['p'], sorted(r['l'])) for r in s.run(cy)}
    d.close()
res = {}
for q in Q:
    a, b = data['prod'][q], data['staging'][q]
    keydiff = Counter(); samples = {}
    for k in set(a) & set(b):
        pa, pb = a[k][0], b[k][0]
        if a[k][1] != b[k][1]:
            keydiff['<labels>'] += 1
        for f in set(pa) | set(pb):
            if f in ('embedding',):
                continue
            if pa.get(f) != pb.get(f):
                keydiff[f] += 1
                samples.setdefault(f, (k, str(pa.get(f))[:60], str(pb.get(f))[:60]))
    res[q] = {'only_prod': len(set(a) - set(b)), 'only_staging': len(set(b) - set(a)), 'field_diffs': dict(keydiff), 'samples': samples}
json.dump(res, open('r3_nodeprops.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))

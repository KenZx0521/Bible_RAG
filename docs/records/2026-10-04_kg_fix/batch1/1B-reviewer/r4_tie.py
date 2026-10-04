"""READ-only: single-seed one-hop Cypher (HEAD) on prod 7687 vs staging 7688; also full candidate list to detect tie-straddle."""
import json, collections
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env=dotenv_values('/home/kenzx0521/Bible_RAG/.env'); auth=(env.get('NEO4J_USER','neo4j'),env.get('NEO4J_PASSWORD'))
CY=("MATCH (seed:Pericope) WHERE seed.id IN $ids MATCH (seed)-[r:CROSS_REFERENCES]-(target:Pericope) WHERE NOT target.id IN $ids "
    "WITH target, count(DISTINCT seed) AS seed_support, max(coalesce(r.votes, 999)) AS votes "
    "RETURN target.id AS id, seed_support, votes ORDER BY seed_support DESC, votes DESC LIMIT $limit")
peri=[json.loads(l)['id'] for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl')]
out={}
for name,uri in (('prod','bolt://localhost:7687'),('stg','bolt://localhost:7688')):
    d=GraphDatabase.driver(uri,auth=auth); r={}
    with d.session(default_access_mode=READ_ACCESS) as s:
        for p in peri:
            r[p]=s.execute_read(lambda tx: [(x['id'],x['votes']) for x in tx.run(CY,ids=[p],limit=10)])
    d.close(); out[name]=r
diff_set=sum(set(out['prod'][p])!=set(out['stg'][p]) for p in peri)
diff_ord=sum(out['prod'][p]!=out['stg'][p] for p in peri)
# votes multiset equal?
vdiff=sum(sorted(v for _,v in out['prod'][p])!=sorted(v for _,v in out['stg'][p]) for p in peri)
print('singles',len(peri),'id-set differs',diff_set,'order differs',diff_ord,'votes-multiset differs',vdiff)

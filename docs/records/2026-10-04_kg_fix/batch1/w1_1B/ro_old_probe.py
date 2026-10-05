"""READ-only: HEAD (087ab0d) one-hop/fallback Cypher on prod vs the OLD-mode port (validates step-1 delta numbers)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, sys
sys.argv = ['x']
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
exec(open('sim_backend_w1.py').read().split("live = json.load")[0])  # G, md5, weights
live = json.load(open(KGFIX_SP + '/batch1plan/1B/xref_prod.json'))
gOld = G([(r[0], r[1], r[5], r[3], r[2]) for r in live], 'OLD')
env = dotenv_values(BIBLE_RAG_ROOT + '/.env'); auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD'))
ONE = ("MATCH (seed:Pericope) WHERE seed.id IN $ids MATCH (seed)-[r:CROSS_REFERENCES]-(target:Pericope) "
       "WHERE NOT target.id IN $ids WITH target, count(DISTINCT seed) AS seed_support, max(coalesce(r.votes, 999)) AS votes "
       "RETURN target.id AS id, votes ORDER BY seed_support DESC, votes DESC, apoc.util.md5([target.id]) LIMIT 10")
FB = ("MATCH (seed:Pericope) WHERE seed.id IN $ids MATCH path = (seed)-[:CROSS_REFERENCES*2..2]-(target:Pericope) "
      "WHERE NOT target.id IN $exclude WITH target, min(length(path)) AS hop_distance "
      "RETURN target.id AS id, hop_distance ORDER BY hop_distance ASC, apoc.util.md5([target.id]) LIMIT $limit")
peri = sorted({json.loads(l)['id'] for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')})
d = GraphDatabase.driver('bolt://localhost:7687', auth=auth); bad = 0
with d.session(default_access_mode=READ_ACCESS) as s:
    for p in peri:
        one = s.execute_read(lambda tx: [(r['id'], 1) for r in tx.run(ONE, ids=[p])])
        if len(one) < 10:
            ex = list({p} | {i for i, _ in one})
            one += s.execute_read(lambda tx: [(r['id'], r['hop_distance']) for r in tx.run(FB, ids=[p], exclude=ex, limit=10 - len(one))])
        bad += one != [(r[0], r[1]) for r in gOld.multi_hop([p])]
d.close(); print('OLD port vs HEAD Cypher on prod, single seeds mismatching:', bad, '/', len(peri))

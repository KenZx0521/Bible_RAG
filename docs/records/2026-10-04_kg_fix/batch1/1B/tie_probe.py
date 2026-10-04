"""READ-only: run the HEAD backend one-hop Cypher (neo4j_db.get_cross_references_multi_hop, verbatim) on prod (7687)
and on the batch-0 staging rebuild (7688, same data) for the 262 R3-R6 proxy seed sets and all single seeds.
Question: with identical data, do the two stores return the same top-10 (i.e. is tie order store-dependent)?"""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, collections
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
from common import *
env = dotenv_values(str(ROOT / '.env')); auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
CY = ("MATCH (seed:Pericope) WHERE seed.id IN $ids "
      "MATCH (seed)-[r:CROSS_REFERENCES]-(target:Pericope) "
      "WHERE NOT target.id IN $ids "
      "WITH target, count(DISTINCT seed) AS seed_support, "
      "     max(coalesce(r.votes, 999)) AS votes "
      "RETURN target.id AS id, seed_support, votes "
      "ORDER BY seed_support DESC, votes DESC "
      "LIMIT $limit")
vmap, peri = load_pericopes()
QT = json.load(open(KGFIX_SP + '/bench/questions_table.json'))
sets = {}
for q in QT:
    if q['route_nograph'] in ('R3', 'R4', 'R5', 'R6'):
        s = [x.split('|')[0] for x in q['nograph_top5']]; s = [x for x in s if x in peri][:5]
        if s: sets[q['qid']] = s
singles = {p: [p] for p in sorted(peri)}
out = {}
for name, uri in (('prod', 'bolt://localhost:7687'), ('staging', 'bolt://localhost:7688')):
    drv = GraphDatabase.driver(uri, auth=auth); res = {}
    with drv.session(default_access_mode=READ_ACCESS) as s:
        for k, ids in list(sets.items()) + [('single:' + p, v) for p, v in singles.items()]:
            res[k] = s.execute_read(lambda tx: [r['id'] for r in tx.run(CY, ids=ids, limit=10)])
            res[k + '#rep'] = s.execute_read(lambda tx: [r['id'] for r in tx.run(CY, ids=ids, limit=10)])
    drv.close(); out[name] = res
json.dump(out, open(OUT / 'tie_probe.json', 'w'))
keys = [k for k in out['prod'] if not k.endswith('#rep')]
C = collections.Counter()
for k in keys:
    kind = 'single' if k.startswith('single:') else 'question'
    a, a2, b = out['prod'][k], out['prod'][k + '#rep'], out['staging'][k]
    C[kind + ' total'] += 1
    C[kind + ' prod repeat differs (order)'] += a != a2
    C[kind + ' prod vs staging differs (order)'] += a != b
    C[kind + ' prod vs staging differs (id set)'] += set(a) != set(b)
for k, v in sorted(C.items()): print(k, v)

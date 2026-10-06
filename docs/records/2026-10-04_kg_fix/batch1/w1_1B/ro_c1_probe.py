"""READ-only: run the planned C1 xref Cypher (transitional coalesce + md5 tiebreak) on prod and staging
for every single seed, the 262 proxy sets and the legacy single-seed query; compare with pred_trans.json."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
W1_1B_EVIDENCE = os.environ.get("W1_1B_EVIDENCE", BIBLE_RAG_ROOT + "/bak/20261005_w1_1b_evidence")
import json, sys, time
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
CUR = "coalesce(r.curated, r.source IN ['markdown', 'supplementary'])"
ONE = ("MATCH (seed:Pericope) WHERE seed.id IN $ids "
       "MATCH (seed)-[r:CROSS_REFERENCES]-(target:Pericope) WHERE NOT target.id IN $ids "
       f"WITH target, count(DISTINCT seed) AS seed_support, max(CASE WHEN {CUR} THEN 1 ELSE 0 END) = 1 AS curated, "
       "     max(coalesce(r.votes, 0)) AS votes "
       "RETURN target.id AS id, 1 AS hop_distance, curated "
       "ORDER BY seed_support DESC, curated DESC, votes DESC, apoc.util.md5([target.id]) LIMIT $limit")
FB = ("MATCH (seed:Pericope) WHERE seed.id IN $ids "
      "MATCH path = (seed)-[:CROSS_REFERENCES*2..2]-(target:Pericope) WHERE NOT target.id IN $exclude "
      f"WITH target, length(path) AS len, all(r IN relationships(path) WHERE {CUR}) AS all_cur "
      "WITH target, min(len) AS hop_distance, collect([len, all_cur]) AS paths "
      "RETURN target.id AS id, hop_distance, any(p IN paths WHERE p[0] = hop_distance AND p[1]) AS curated "
      "ORDER BY hop_distance ASC, curated DESC, apoc.util.md5([target.id]) LIMIT $limit")
LEG = ("MATCH (p:Pericope {id: $pid})-[r:CROSS_REFERENCES]-(target:Pericope) WHERE target.id <> $pid "
       f"WITH target, max(CASE WHEN {CUR} THEN 1 ELSE 0 END) = 1 AS curated, max(coalesce(r.votes, 0)) AS votes "
       "RETURN target.id AS id, 1 AS hop_distance, curated "
       "ORDER BY curated DESC, votes DESC, apoc.util.md5([target.id]) LIMIT $limit")
HOP = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}; TSKH = {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30}
pred = json.load(open(W1_1B_EVIDENCE + '/pred_trans.json'))
QT = json.load(open(BIBLE_RAG_ROOT + '/docs/records/2026-10-04_kg_fix/batch1/inputs/bench/questions_table.json'))
pset = {k[7:] for k in pred if k.startswith('single:')}
qsets = {}
for q in QT:
    if q['route_nograph'] in ('R3', 'R4', 'R5', 'R6'):
        s = [x.split('|')[0] for x in q['nograph_top5']]; s = [x for x in s if x in pset][:5]
        if s: qsets[q['qid']] = s
def rows(recs): return [[r['id'], r['hop_distance'], r['curated'], (HOP if r['curated'] else TSKH)[r['hop_distance']]] for r in recs]
for name, uri in (('prod', 'bolt://localhost:7687'), ('staging', 'bolt://localhost:7688')):
    d = GraphDatabase.driver(uri, auth=auth); meas = {}; t0 = time.time()
    with d.session(default_access_mode=READ_ACCESS) as s:
        def multi(ids):
            out = rows(s.execute_read(lambda tx: list(tx.run(ONE, ids=ids, limit=10))))
            if len(out) < 10:
                excl = list(set(ids) | {r[0] for r in out})
                out += rows(s.execute_read(lambda tx: list(tx.run(FB, ids=ids, exclude=excl, limit=10 - len(out)))))
            return out
        for p in sorted(pset):
            meas[f'single:{p}'] = multi([p])
            meas[f'legacy:{p}'] = rows(s.execute_read(lambda tx: list(tx.run(LEG, pid=p, limit=10))))
        for qid, ids in qsets.items():
            meas[f'q:{qid}'] = multi(ids)
    d.close()
    diff = [k for k in pred if pred[k] != meas.get(k)]
    print(name, 'keys', len(meas), 'mismatch vs prediction', len(diff), diff[:5], f'{time.time()-t0:.0f}s')
    json.dump(meas, open(W1_1B_EVIDENCE + f'/meas_trans_{name}.json', 'w'))

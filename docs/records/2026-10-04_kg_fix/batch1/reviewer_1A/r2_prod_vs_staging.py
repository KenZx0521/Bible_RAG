"""Reviewer: READ-only compare of prod (7687) vs staging (7688) node/MENTIONS properties
that diff_kg does not look at (mention_count, MENTIONS start_pos). Credentials from .env."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, os
from collections import Counter
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
Q_MC = "MATCH (e:Entity) RETURN e.entity_id AS id, e.mention_count AS mc"
Q_SP = "MATCH (s)-[m:MENTIONS]->(e:Entity) RETURN coalesce(s.id,s.entity_id) AS s, e.entity_id AS e, m.start_pos AS sp"
out = {}
for name, uri in (('prod', 'bolt://localhost:7687'), ('staging', 'bolt://localhost:7688')):
    d = GraphDatabase.driver(uri, auth=auth)
    with d.session(default_access_mode=READ_ACCESS) as s:
        mc = {r['id']: r['mc'] for r in s.run(Q_MC)}
        sp = {(r['s'], r['e']): r['sp'] for r in s.run(Q_SP)}
    d.close()
    out[name] = (mc, sp)
(mca, spa), (mcb, spb) = out['prod'], out['staging']
mc_diff = [(k, mca.get(k), mcb.get(k)) for k in sorted(set(mca) | set(mcb)) if mca.get(k) != mcb.get(k)]
sp_diff = [k for k in set(spa) & set(spb) if spa[k] != spb[k]]
res = {'mention_count_diff_entities': len(mc_diff), 'mc_samples': mc_diff[:15],
       'mentions_both': len(set(spa) & set(spb)), 'start_pos_diff_edges': len(sp_diff),
       'start_pos_null_prod': sum(v is None for v in spa.values()), 'start_pos_null_staging': sum(v is None for v in spb.values()),
       'start_pos0_prod': sum(v == 0 for v in spa.values()), 'start_pos0_staging': sum(v == 0 for v in spb.values())}
json.dump(res, open('r2_prod_vs_staging.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))

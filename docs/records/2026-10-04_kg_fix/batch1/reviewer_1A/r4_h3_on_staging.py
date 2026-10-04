"""Reviewer: score the planner's simulated relations_clean (gei/declared) for H3 and H9
against the ACTUAL staging graph's MENTIONS/labels (READ only), instead of JSONL-derived support."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
from collections import Counter
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
import yaml
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
d = GraphDatabase.driver('bolt://localhost:7688', auth=auth)
with d.session(default_access_mode=READ_ACCESS) as s:
    ment = [(r['l'], r['s'], r['e']) for r in s.run(
        "MATCH (s)-[m:MENTIONS]->(e:Entity) RETURN CASE WHEN s:Chunk THEN 'Chunk' ELSE 'Pericope' END AS l, s.id AS s, e.entity_id AS e")]
    cp = {r['id']: r['p'] for r in s.run("MATCH (c:Chunk) RETURN c.id AS id, c.pericope_id AS p")}
    lab = {r['id']: [x for x in r['l'] if x != 'Entity'][0] for r in s.run("MATCH (e:Entity) RETURN e.entity_id AS id, labels(e) AS l")}
d.close()
sup = {((cp.get(sid) if l == 'Chunk' else sid), e) for l, sid, e in ment}
schema = yaml.safe_load(open(BIBLE_RAG_ROOT + '/config/relations/biblical_relations.yaml'))['relations']
def acc(rel, h, t):
    e = schema[rel]; ht, tt = lab.get(h), lab.get(t)
    ok = ht in e['domain_types'] and tt in e['range_types']
    return ok or (e['direction'] == 'undirected' and tt in e['domain_types'] and ht in e['range_types'])
F = [json.loads(l) for l in open('../planner_1A/relations_clean_sim_gei_declared.jsonl')]
final = [r for r in F if r['head_id'] in lab and r['tail_id'] in lab]
h3 = [r for r in final if r['source'] != 'prior' and not ((r['source_pericope_id'], r['head_id']) in sup and (r['source_pericope_id'], r['tail_id']) in sup)]
h9 = [r for r in final if not acc(r['relation'], r['head_id'], r['tail_id'])]
print(json.dumps({'staging_mentions': len(ment), 'final_edges_after_generic_delete': len(final),
                  'H3_unsupported_vs_staging': len(h3), 'H3_by_source': dict(Counter(r['source'] for r in h3)),
                  'H3_samples': [(r['head_id'], r['relation'], r['tail_id'], r['source_pericope_id']) for r in h3[:8]],
                  'H9_vs_staging_labels': len(h9)}, ensure_ascii=False, indent=1))

"""READ-only dump of live (prod 7687) and staging (7688) CROSS_REFERENCES.
Writes xref_<target>.json: list of [src, tgt, source, votes, verse_pairs, curated, tsk, source_verses, target_verses]."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, os, sys
from pathlib import Path
from dotenv import dotenv_values
from neo4j import GraphDatabase, READ_ACCESS
OUT = Path(__file__).parent
env = dotenv_values(BIBLE_RAG_ROOT + '/.env')
auth = (env.get('NEO4J_USER', 'neo4j'), env.get('NEO4J_PASSWORD', 'neo4j_password'))
Q = """MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
RETURN a.id AS s, b.id AS t, r.source AS source, r.votes AS votes, r.verse_pairs AS vp,
       r.curated AS curated, r.tsk AS tsk, r.source_verses AS sv, r.target_verses AS tv"""
Q2 = """MATCH (a)-[r:CROSS_REFERENCES]->(b) WHERE NOT (a:Pericope AND b:Pericope)
RETURN labels(a) AS la, labels(b) AS lb, count(*) AS n"""
for name, uri in (('prod', 'bolt://localhost:7687'), ('staging', 'bolt://localhost:7688')):
    drv = GraphDatabase.driver(uri, auth=auth)
    try:
        with drv.session(default_access_mode=READ_ACCESS) as s:
            rows = s.execute_read(lambda tx: [list(r.values()) for r in tx.run(Q)])
            other = s.execute_read(lambda tx: [r.data() for r in tx.run(Q2)])
        json.dump(rows, open(OUT / f'xref_{name}.json', 'w'), ensure_ascii=False)
        print(name, len(rows), 'non-pericope xref:', other)
    except Exception as e:
        print(name, 'ERR', e)
    finally:
        drv.close()

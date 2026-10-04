"""Read-only fetch of the staging graph (bolt 7688, READ sessions) -> pickle.
Staging == prod except the 4 SON_OF edge properties (batch-0 diff_kg)."""
import os, sys, pickle
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/scripts")
from neo4j import GraphDatabase
from check_identity import read_query
from kg_validate.model import load_live
OUT = os.path.dirname(os.path.abspath(__file__))
uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://localhost:7688"
drv = GraphDatabase.driver(uri, auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
                           notifications_min_severity="OFF")
kg = load_live(drv, origin=f"live:{uri}")
edges = read_query(drv, """
MATCH (s)-[m:MENTIONS]->(e:Entity)
RETURN CASE WHEN s:Chunk THEN 'Chunk' ELSE 'Pericope' END AS lab, s.id AS sid, e.entity_id AS eid,
       CASE WHEN s:Pericope THEN s.title WHEN s:Chunk THEN s.pericope_title END AS title,
       m.start_pos AS start_pos, m.source AS source, m.text_span AS span""")
ents = read_query(drv, """MATCH (e:Entity) RETURN e.entity_id AS eid, [l IN labels(e) WHERE l<>'Entity'][0] AS label,
       e.canonical_name AS name, e.mention_count AS mc, e.extraction_method AS em""")
drv.close()
tag = "staging" if "7688" in uri else "prod"
pickle.dump({"kg": kg, "edges": edges, "ents": ents}, open(f"{OUT}/graph_{tag}.pkl", "wb"))
print(tag, len(kg.entity_rows), len(kg.mentions), len(kg.relations), len(kg.xrefs), len(edges), len(ents))

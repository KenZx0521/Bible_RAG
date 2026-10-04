"""READ-only dump of MENTIONS (+ source titles) and entity props from a Neo4j target."""
import json, sys
from ro import run
target = sys.argv[1]
ments = run("""
MATCH (s)-[m:MENTIONS]->(e:Entity)
RETURN CASE WHEN s:Chunk THEN 'Chunk' WHEN s:Pericope THEN 'Pericope' ELSE head(labels(s)) END AS sl,
       s.id AS sid, e.entity_id AS eid, [l IN labels(e) WHERE l <> 'Entity'][0] AS el,
       CASE WHEN s:Pericope THEN s.title WHEN s:Chunk THEN s.pericope_title END AS title,
       m.text_span AS span, m.start_pos AS sp, m.end_pos AS ep, m.source_granularity AS g,
       m.curated AS curated, m.source AS source""")
ents = run("""MATCH (e:Entity) RETURN e.entity_id AS eid, [l IN labels(e) WHERE l <> 'Entity'][0] AS el,
              e.canonical_name AS name, e.mention_count AS mc, e.description AS d""")
json.dump({"mentions": ments, "entities": ents}, open(f"graph_{target}.json", "w"), ensure_ascii=False)
print(target, len(ments), len(ents))

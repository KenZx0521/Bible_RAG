"""Every Cypher query the backend may send to Neo4j: a closed set, read by name (``neo4j_db.read``).

Each reads one build (``$b``, which the caller passes). The rules, tested in test_neo4j_db: a LIMIT
comes with an ORDER BY (without one a re-projection changes the rows), no bare variable-length
pattern (depth 6 reaches millions of paths), a quantified path has its bounds in the template, a
shortest path is ALL SHORTEST (ANY SHORTEST picks differently each time), and no elementId or id().

``walk_round`` is one round of the graph walk (utils.retrieval.graph_walk), from passage and name
seeds to the passages their names reach. Scores are rounded before they are ordered: the rows reach
sum() in an order of the plan's choosing, and an unrounded tie would break differently between
projections. Names too common to mean anything (``$max_df``) carry nothing.

The kin templates answer in one row shape: ``nodes`` [[id, label]...], ``edges`` [[from, type, to,
role, evidence units]...], ``hops``. A person flagged ``kin_conflict`` may join two people, so a path
only ends there, it never goes through.
"""

from types import MappingProxyType

BUILD_INFO = "MATCH (i:BuildInfo {build_id:$b}) RETURN properties(i) AS info"

SERVER_VERSION = ("CALL dbms.components() YIELD name, versions WHERE name = 'Neo4j Kernel' "
                  "RETURN versions[0] AS version")

WALK_ROUND = """
CALL () {
  UNWIND $seeds AS s
  MATCH (:Passage {build_id:$b, id:s.id})-[:MENTIONS]->(n:Name)
  RETURN n, s.w AS w
  UNION ALL
  UNWIND $names AS s
  MATCH (n:Name {build_id:$b, id:s.id})
  RETURN n, s.w AS w
}
WITH n, round(sum(w) * n.idf, 9) AS a
WHERE n.df <= $max_df
WITH n, a
ORDER BY a DESC, n.id ASC
LIMIT $top_names
WITH collect({n: n, a: a}) AS top
CALL (top) {
  UNWIND top AS t
  WITH t.n AS n, t.a AS a
  MATCH (q:Passage)-[:MENTIONS]->(n)
  WITH q, round(sum(a * n.idf), 9) AS s
  ORDER BY s DESC, q.id ASC
  RETURN collect([q.id, s]) AS hits
}
CALL () {
  UNWIND $parallel AS s
  MATCH (:Passage {build_id:$b, id:s.id})<-[:HAS_PASSAGE]-(:Pericope)-[:PARALLEL]-(:Pericope)
        -[:HAS_PASSAGE]->(q:Passage)
  WITH DISTINCT s, q
  WITH q, round(sum($parallel_factor * s.w), 9) AS s
  ORDER BY q.id ASC
  RETURN collect([q.id, s]) AS parallel
}
RETURN [t IN top | [t.n.id, t.n.label, t.a]] AS names, hits, parallel
"""

# who may be meant by a name: the card picks among them and names their parents
KIN_PERSONS = """
UNWIND $surfaces AS s
MATCH (p:Person {build_id:$b})
WHERE p.id IS NOT NULL AND s IN p.surfaces
RETURN s AS surface, p.id AS id, p.label AS label, p.mentions AS mentions,
       p.kin_conflict AS kin_conflict, p.mention_units AS units,
       [(f:Person)-[r:PARENT_OF]->(p) | [f.id, f.label, r.role, r.evidence_units]] AS parents,
       size([(p)-[:PARENT_OF]->(c:Person) | c.id]) AS children,
       size([(p)-[:SPOUSE_OF]-(s2:Person) | s2.id]) AS spouses,
       size([(p)-[:SIBLING_OF]-(s3:Person) | s3.id]) AS siblings
ORDER BY surface, mentions DESC, id ASC
"""

# which of a name's people the other name's are closest to; pairs come from KIN_PERSONS
KIN_PAIR_HOPS = """
UNWIND $pairs AS pair
MATCH (a:Person {build_id:$b, id:pair[0]}), (c:Person {build_id:$b, id:pair[1]})
MATCH p = ALL SHORTEST (a) ((u)-[:PARENT_OF|SPOUSE_OF|SIBLING_OF]-(v) WHERE v.id = pair[1] OR NOT v.kin_conflict){1,5} (c)
WITH pair[0] AS x, pair[1] AS y, min(length(p)) AS hops
RETURN x, y, hops
ORDER BY hops, x, y
"""

_KIN_ROW = """
WITH [n IN nodes(p) | [n.id, n.label]] AS nodes,
     [r IN relationships(p) | [startNode(r).id, type(r), endNode(r).id, r.role, r.evidence_units]] AS edges
RETURN nodes, edges, size(edges) AS hops
"""

KIN_PATH = """
MATCH (a:Person {build_id:$b, id:$x}), (c:Person {build_id:$b, id:$y})
MATCH p = ALL SHORTEST (a) ((u)-[:PARENT_OF|SPOUSE_OF|SIBLING_OF]-(v) WHERE v.id = $y OR NOT v.kin_conflict){1,5} (c)
""" + _KIN_ROW + "ORDER BY nodes, edges LIMIT 9"

# the deepest first: a limit that cuts drops what the question asked for last
KIN_UP = """
MATCH p = (a:Person {build_id:$b, id:$x}) ((u)<-[:PARENT_OF]-(v) WHERE NOT v.kin_conflict){1,3} (t)
WHERE length(p) <= $depth
""" + _KIN_ROW + "ORDER BY hops DESC, nodes, edges LIMIT 64"

KIN_DOWN = """
MATCH p = (a:Person {build_id:$b, id:$x}) ((u)-[:PARENT_OF]->(v) WHERE NOT v.kin_conflict){1,3} (t)
WHERE length(p) <= $depth
""" + _KIN_ROW + "ORDER BY hops DESC, nodes, edges LIMIT 64"

KIN_SIDE = """
MATCH p = (a:Person {build_id:$b, id:$x})-[r:SIBLING_OF|SPOUSE_OF]-(:Person)
WHERE type(r) IN $types
""" + _KIN_ROW + "ORDER BY nodes, edges LIMIT 64"

KIN_NEAR = """
MATCH p = (a:Person {build_id:$b, id:$x}) ((u)-[:PARENT_OF|SPOUSE_OF|SIBLING_OF]-(v) WHERE NOT v.kin_conflict){1,2} (t)
""" + _KIN_ROW + "ORDER BY hops, nodes, edges LIMIT 64"

# a verse a heading cuts belongs to two passages
UNIT_PASSAGES = """
UNWIND $units AS u
MATCH (p:Passage)-[:HAS_VERSE]->(:Verse {build_id:$b, id:u})
RETURN u AS unit, p.id AS passage
ORDER BY unit, passage
"""

TEMPLATES = MappingProxyType({
    "build_info": BUILD_INFO,
    "server_version": SERVER_VERSION,
    "walk_round": WALK_ROUND,
    "kin_persons": KIN_PERSONS,
    "kin_pair_hops": KIN_PAIR_HOPS,
    "kin_path": KIN_PATH,
    "kin_up": KIN_UP,
    "kin_down": KIN_DOWN,
    "kin_side": KIN_SIDE,
    "kin_near": KIN_NEAR,
    "unit_passages": UNIT_PASSAGES,
})

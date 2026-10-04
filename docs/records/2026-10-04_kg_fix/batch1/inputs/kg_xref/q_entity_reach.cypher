// 實體（canonical 或 alias 命中）→ 經 Pericope/Chunk MENTIONS 可到的段落數與金錨命中
UNWIND $items AS it   // [qid, name, [gold pericope ids]]
OPTIONAL MATCH (e:Entity) WHERE e.canonical_name = it[1] OR it[1] IN coalesce(e.aliases,[])
OPTIONAL MATCH (p:Pericope)-[:MENTIONS]->(e)
OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(e)
WITH it, e, collect(DISTINCT p.id) + collect(DISTINCT c.pericope_id) AS ps0
WITH it, e, reduce(s=[], x IN ps0 | CASE WHEN x IN s THEN s ELSE s + x END) AS ps
RETURN it[0] AS q, it[1] AS name, [l IN labels(e) WHERE l <> 'Entity'] AS lab, e.entity_id AS eid, e.mention_count AS mc, size(ps) AS nper, [g IN it[2] WHERE g IN ps] AS gold_hit

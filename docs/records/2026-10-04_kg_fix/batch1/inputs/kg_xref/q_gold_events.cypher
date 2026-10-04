// 每個金錨 pericope 掛了哪些 Event，以及該 Event 連到幾段（看事件層是否把平行/引用兩端合併）
UNWIND $pids AS pid
MATCH (p:Pericope {id:pid})
OPTIONAL MATCH (p)-[:MENTIONS]->(e:Event)
OPTIONAL MATCH (p2:Pericope)-[:MENTIONS]->(e)
WITH pid, p, e, collect(DISTINCT p2.id) AS eps
RETURN pid, p.title AS title, collect(e.canonical_name + '[' + toString(size(eps)) + ']') AS events

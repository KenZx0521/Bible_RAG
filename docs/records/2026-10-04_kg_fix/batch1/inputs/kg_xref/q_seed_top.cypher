// 後端排序（max(coalesce(votes,999)) DESC）下某 seed 的前 6 名鄰居
UNWIND $seeds AS sid
MATCH (s:Pericope {id:sid})-[r:CROSS_REFERENCES]-(n:Pericope) WHERE n.id <> sid
WITH sid, n, max(coalesce(r.votes,999)) AS sc, collect(DISTINCT r.source) AS src
ORDER BY sid, sc DESC
WITH sid, collect(n.id + '(' + n.verse_range + ')' + toString(sc) + left(src[0],3)) AS nb
RETURN sid, nb[0..6] AS top6

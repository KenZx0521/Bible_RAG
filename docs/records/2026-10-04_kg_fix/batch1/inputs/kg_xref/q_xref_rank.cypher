// 金錨互達：從某一 gold pericope 出發，經 CROSS_REFERENCES（依後端排序 max(coalesce(votes,999)) DESC）
// 另一書卷的 gold pericope 落在第幾名（worst-case rank = 分數 >= 目標分數的鄰居數）
UNWIND keys($p) AS q
WITH q, $p[q][0] AS gold, $p[q][1] AS s0
UNWIND gold AS a UNWIND gold AS b
WITH q, s0, split(a,'|') AS A, split(b,'|') AS B WHERE A[0] <> B[0]
MATCH (s:Pericope {id:A[1]})-[r:CROSS_REFERENCES]-(n:Pericope) WHERE n.id <> s.id
WITH q, s0, A, B, n.id AS nid, max(coalesce(r.votes,999)) AS sc, collect(DISTINCT r.source) AS src
WITH q, s0, A, B, collect({n:nid, sc:sc, src:src}) AS nb
WITH q, s0, A, B, size(nb) AS deg, nb, [x IN nb WHERE x.n = B[1]] AS h
WITH q, s0, A, B, deg,
     CASE WHEN size(h)=0 THEN 9999 ELSE size([x IN nb WHERE x.sc >= h[0].sc]) END AS wr,
     CASE WHEN size(h)=0 THEN '-' ELSE reduce(t='', z IN h[0].src | t + left(z,3)) + '/' + toString(h[0].sc) END AS how
WITH q, B[0] AS grp, collect({w:wr, s:A[1]+'>'+B[1]+'#'+toString(wr)+'('+how+',deg'+toString(deg)+')', in0: A[1] IN s0}) AS rows
WITH q, grp, rows,
     reduce(m={w:99999,s:'none'}, x IN rows | CASE WHEN x.w < m.w THEN x ELSE m END) AS best_any,
     reduce(m={w:99999,s:'none'}, x IN [y IN rows WHERE y.in0] | CASE WHEN x.w < m.w THEN x ELSE m END) AS best_s0
RETURN q, grp, best_any.s AS best_any, best_s0.s AS best_from_s0
ORDER BY q, grp

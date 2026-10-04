// d(s,g) = 從 seed 書卷群 s 的任一 gold pericope 出發，到書卷群 g 任一 gold 的最佳 worst-case rank
// R = min_s max_{g!=s} d(s,g)：單一 seed 群能把其他所有群都帶進來所需的候選數
UNWIND keys($p) AS q
WITH q, $p[q][0] AS gold
UNWIND gold AS a UNWIND gold AS b
WITH q, split(a,'|') AS A, split(b,'|') AS B WHERE A[0] <> B[0]
MATCH (s:Pericope {id:A[1]})-[r:CROSS_REFERENCES]-(n:Pericope) WHERE n.id <> s.id
WITH q, A, B, n.id AS nid, max(coalesce(r.votes,999)) AS sc
WITH q, A, B, collect({n:nid, sc:sc}) AS nb
WITH q, A, B, [x IN nb WHERE x.n = B[1]] AS h, nb
WITH q, A[0] AS sg, B[0] AS tg, CASE WHEN size(h)=0 THEN 9999 ELSE size([x IN nb WHERE x.sc >= h[0].sc]) END AS wr
WITH q, sg, tg, min(wr) AS d
WITH q, sg, max(d) AS worst, collect(tg + ':' + toString(d)) AS ds
ORDER BY q, worst
WITH q, collect({sg:sg, worst:worst, ds:ds}) AS rows
RETURN q, rows[0].worst AS R, rows[0].sg AS best_seed, rows[0].ds AS d_from_best, [x IN rows[1..] | x.sg + '>' + toString(x.worst)] AS others
ORDER BY q

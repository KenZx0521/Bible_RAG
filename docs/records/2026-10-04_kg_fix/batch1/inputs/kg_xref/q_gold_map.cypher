// reference 段 → 金錨 pericope（verse_range 重疊）；$segs = [[qid, book_id, chapter, v0, v1], ...]（見 segs.json）
UNWIND $segs AS s
MATCH (p:Pericope {book_id:s[1], chapter_num:s[2]})
WITH s, p, toInteger(split(p.verse_range,'-')[0]) AS a0, toInteger(coalesce(split(p.verse_range,'-')[1], split(p.verse_range,'-')[0])) AS a1
WHERE a0 <= s[4] AND a1 >= s[3]
RETURN s[0] AS q, collect(DISTINCT s[1]+'|'+p.id) AS gold ORDER BY q

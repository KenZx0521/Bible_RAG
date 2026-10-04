// supplementary 引用/暗引邊驗證：source_verses 是否落在來源 pericope 的 verse_range、target_verses 是否落在目標 pericope
MATCH (a:Pericope)-[r:CROSS_REFERENCES {source:'supplementary'}]->(b:Pericope)
WITH a, b, r,
 toInteger(split(split(r.source_verses,',')[0],'-')[0]) AS sv,
 toInteger(split(split(r.target_verses,',')[0],'-')[0]) AS tv,
 toInteger(split(a.verse_range,'-')[0]) AS as0, toInteger(coalesce(split(a.verse_range,'-')[1], split(a.verse_range,'-')[0])) AS as1,
 toInteger(split(b.verse_range,'-')[0]) AS bs0, toInteger(coalesce(split(b.verse_range,'-')[1], split(b.verse_range,'-')[0])) AS bs1
WITH a, b, r, (sv>=as0 AND sv<=as1) AS src_ok, (tv>=bs0 AND tv<=bs1) AS tgt_ok
RETURN src_ok, tgt_ok, count(*) AS n
// 結果：src_ok&tgt_ok=83；src 錯(NT 端錯位)、tgt 對=59；共 142 → 41.5% NT 端錯位

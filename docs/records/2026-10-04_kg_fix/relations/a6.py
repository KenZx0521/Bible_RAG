import json, re
from collections import Counter
E = json.load(open('edges.json'))
P = {json.loads(l)['id']: json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl')}
TRAPS = {'person:maliya': ('馬利亞', ['撒馬利亞']), 'person:yiliya': ('以利亞', ['以利亞撒','以利亞敬','以利亞實','以利亞巴','以利亞他','以利亞哈巴']),
         'person:liya': ('利亞', ['撒迦利亞','亞瑪利亞','西底家','以利亞','亞撒利亞','米利亞','示利亞','希利亞','瑪利亞','馬利亞','亞利亞','耶利亞','撒利亞','提利亞','亞瑪利雅']),
         'person:yana': ('亞拿', ['亞拿突','亞拿尼亞','亞拿巴','亞拿米勒','亞拿哈拉','亞拿雅','亞拿伯']),}
c = Counter(); ex = []
for e in E:
    pr = e['props']; pid = pr.get('source_pericope_id')
    for side in ('h','t'):
        eid = e[side]
        if eid in TRAPS and pid in P:
            nm, longs = TRAPS[eid]; t = P[pid]['content']
            stripped = t
            for L in sorted(longs, key=len, reverse=True): stripped = stripped.replace(L, '□'*len(L))
            src = 'backfill' if pr.get('backfilled') else {2:'rule',4:'llm',5:'inverse'}.get(pr['extraction_phase'])
            k = 'real' if nm in stripped else 'trap_only'
            c[(eid, src, k)] += 1
            if k=='trap_only' and len(ex)<10: ex.append((e['hn'], e['rel'], e['tn'], pid))
for k in sorted(c): print(k, c[k])
print(ex)

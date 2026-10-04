import json
from collections import Counter
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
c=Counter(); who=Counter()
for e in E:
    pr=e['props']; ph=pr.get('extraction_phase')
    src='bf' if pr.get('backfilled') else ('inv' if (pr.get('notes') or '').startswith('derived_from') else str(ph))
    t=P.get(pr.get('source_pericope_id'),'')
    hl=[x for x in e['hl'] if x!='Entity'][0]; tl=[x for x in e['tl'] if x!='Entity'][0]
    miss=[n for n,ty in ((e['hn'],hl),(e['tn'],tl)) if ty!='Event' and n not in t]
    c[(src,'total')]+=1
    if miss:
        c[(src,'name_absent')]+=1
        if src=='bf':
            for m in miss: who[m]+=1
for k in sorted(c): print(k,c[k])
print(who.most_common(15))

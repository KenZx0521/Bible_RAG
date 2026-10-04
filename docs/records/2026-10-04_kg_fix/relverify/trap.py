import json, re
from collections import Counter
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
# names of all entities sorted by length for longest-match
ENT=[json.loads(l)['canonical_name'] for l in open('/home/kenzx0521/Bible_RAG/output/entities.jsonl')]
TRAPS={'馬利亞','以利亞','利亞','亞拿'}
def only_substring(name, t):
    longer=[n for n in ENT if name in n and n!=name and n in t]
    idx=[m.start() for m in re.finditer(re.escape(name), t)]
    if not idx: return None
    for i in idx:
        covered=False
        for L in longer:
            for m in re.finditer(re.escape(L), t):
                if m.start()<=i and i+len(name)<=m.end(): covered=True;break
            if covered: break
        if not covered: return False
    return True
c=Counter()
for e in E:
    pr=e['props']
    for nm in (e['hn'],e['tn']):
        if nm in TRAPS:
            t=P.get(pr.get('source_pericope_id'),'')
            src='bf' if pr.get('backfilled') else ('inv' if (pr.get('notes') or '').startswith('derived_from') else str(pr.get('extraction_phase')))
            r=only_substring(nm,t)
            c[(src, 'trap_only' if r else ('absent' if r is None else 'genuine'))]+=1
for k in sorted(c): print(k,c[k])

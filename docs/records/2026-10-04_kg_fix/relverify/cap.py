import json
from collections import Counter, defaultdict
pp=defaultdict(list)
for l in open('/home/kenzx0521/Bible_RAG/output/relations_checkpoint.jsonl'):
    a,b,pid=json.loads(l)['pair_key'].split('|',2); pp[pid].append((a,b))
M=json.load(open('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relations/ment.json'))
ents=defaultdict(set)
for m in M:
    if not m['bf']: ents[m['pid']].add(m['eid'])
c=Counter()
for pid,pairs in pp.items():
    capped=len(pairs)==80
    pperson=sum(1 for a,b in pairs if a.startswith('person:') and b.startswith('person:'))
    persons=[e for e in ents.get(pid,()) if e.startswith('person:')]
    potential=len(persons)*(len(persons)-1)//2
    key='capped' if capped else 'uncapped'
    c[key+'_pericopes']+=1; c[key+'_PP_mined']+=pperson; c[key+'_PP_potential_now']+=potential
print(dict(c))

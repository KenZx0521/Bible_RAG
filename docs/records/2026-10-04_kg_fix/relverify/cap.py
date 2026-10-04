import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json
from collections import Counter, defaultdict
pp=defaultdict(list)
for l in open(BIBLE_RAG_ROOT + '/output/relations_checkpoint.jsonl'):
    a,b,pid=json.loads(l)['pair_key'].split('|',2); pp[pid].append((a,b))
M=json.load(open(KGFIX_SP + '/kgfix/relations/ment.json'))
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

import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from collections import Counter
ENT={}
for l in open(BIBLE_RAG_ROOT + '/output/entities.jsonl'):
    d=json.loads(l); ENT[d['entity_id']]=(d['canonical_name'], d['type'])
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
c=Counter(); who=Counter()
for l in open(BIBLE_RAG_ROOT + '/output/relations_checkpoint.jsonl'):
    a,b,pid=json.loads(l)['pair_key'].split('|',2)
    if a not in ENT or b not in ENT: continue
    t=P.get(pid,'')
    c['pairs']+=1
    miss=[ENT[x][0] for x in (a,b) if ENT[x][1]!='Event' and ENT[x][0] not in t]
    if miss:
        c['nonEvent_name_absent_from_pericope']+=1
        for m in miss: who[m]+=1
    if len(t)>1500: c['pericope_gt1500']+=1
print(c); print(who.most_common(25))

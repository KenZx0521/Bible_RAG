import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
sys.path.insert(0,BIBLE_RAG_ROOT)
from collections import Counter
from scripts.relation_extraction.pair_miner import _trim_grounding
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
c=Counter(); ex=[]
for j in J:
    if j['extraction_phase']!=4: continue
    t=P.get(j['source_pericope_id'],'')
    # pair_miner passes names in sorted-id order (a,b); _trim_grounding is symmetric in names
    g=_trim_grounding(t, j['head_canonical'], j['tail_canonical'], 1)
    ev=j['evidence_span']
    c['n']+=1
    if ev in g: c['ev_in_own_grounding']+=1
    else:
        c['ev_NOT_in_own_grounding']+=1
        if len(ex)<6: ex.append((j['head_canonical'],j['relation'],j['tail_canonical'],ev[:40]))
print(c)
for e in ex: print(e)

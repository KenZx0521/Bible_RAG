import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from collections import Counter
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
c=Counter()
for j in J:
    if j['extraction_phase']!=4: continue
    ev=j['evidence_span']; t=P.get(j['source_pericope_id'],'')
    c['n']+=1
    if t.startswith(ev) and len(ev)==80: c['ev_eq_ctx80_maybe_empty']+=1
    hin=j['head_canonical'] in ev; tin=j['tail_canonical'] in ev
    if not hin and not tin: c['neither_name_in_ev']+=1
    elif not (hin and tin): c['one_name_in_ev']+=1
    if j['head_canonical'] not in t: c['head_not_in_pericope']+=1
    if j['tail_canonical'] not in t: c['tail_not_in_pericope']+=1
    if ev not in t: c['ev_not_in_pericope']+=1
print(c)

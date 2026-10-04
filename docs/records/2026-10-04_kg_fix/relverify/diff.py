import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json
from collections import Counter
W=KGFIX_SP + '/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
live={}
for e in E:
    if e['props'].get('backfilled'): continue
    live[(e['h'],e['t'],e['rel'])]=e
jk={(j['head_id'],j['tail_id'],j['relation']):j for j in J}
print('live nonbf',len(live),'jsonl',len(jk))
miss=[k for k in jk if k not in live]; extra=[k for k in live if k not in jk]
print('missing',len(miss),'extra',len(extra))
print(Counter(jk[k]['extraction_phase'] for k in miss))
# phase mismatches
pm=Counter()
for k in jk:
    if k in live:
        lp=live[k]['props'].get('extraction_phase'); jp=jk[k]['extraction_phase']
        if lp!=jp: pm[(jp,lp)]+=1
        if live[k]['props'].get('notes')!=jk[k]['notes']: pm['notes_diff']+=1
        if abs(live[k]['props'].get('confidence',0)-jk[k]['confidence'])>1e-6: pm['conf_diff']+=1
print('phase mismatch',pm)
for k in extra[:10]: print('EXTRA',k, live[k]['props'])

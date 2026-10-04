import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json
from collections import Counter
W=KGFIX_SP + '/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
live={(e['h'],e['t'],e['rel']):e for e in E if not e['props'].get('backfilled')}
jk={(j['head_id'],j['tail_id'],j['relation']):j for j in J}
for k in jk:
    if k in live and live[k]['props'].get('extraction_phase')!=jk[k]['extraction_phase']:
        print(k, live[k]['hn'], live[k]['tn']); print('  jsonl', {x:jk[k][x] for x in ('extraction_phase','notes','confidence')}); print('  live', {x:live[k]['props'].get(x) for x in ('extraction_phase','notes','confidence')})
miss=[k for k in jk if k not in live]
ids=Counter()
for k in miss:
    for x in k[:2]:
        if x.startswith('event:'): ids[x]+=1
print(len(ids), ids.most_common(20))

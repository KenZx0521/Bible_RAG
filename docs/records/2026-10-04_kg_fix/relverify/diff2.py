import json
from collections import Counter
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/relations.jsonl')]
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

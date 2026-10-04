import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json
W=KGFIX_SP + '/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
live={(e['h'],e['t'],e['rel']) for e in E if not e['props'].get('backfilled')}
G={'event:gongcheng','event:dahui','event:dashi','event:jianzhu','event:wenhou','event:fenfu','event:rizi','event:shengri','event:zhangzi','event:zhenglun','event:jiannan','event:shiyong','event:tanzi','event:jieju','event:zuoxi'}
for j in J:
    k=(j['head_id'],j['tail_id'],j['relation'])
    if k in live: continue
    if j['head_id'] in G or j['tail_id'] in G: continue
    print(k, j['head_canonical'], j['tail_canonical'])

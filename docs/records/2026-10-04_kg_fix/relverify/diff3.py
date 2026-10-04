import json
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/relations.jsonl')]
live={(e['h'],e['t'],e['rel']) for e in E if not e['props'].get('backfilled')}
G={'event:gongcheng','event:dahui','event:dashi','event:jianzhu','event:wenhou','event:fenfu','event:rizi','event:shengri','event:zhangzi','event:zhenglun','event:jiannan','event:shiyong','event:tanzi','event:jieju','event:zuoxi'}
for j in J:
    k=(j['head_id'],j['tail_id'],j['relation'])
    if k in live: continue
    if j['head_id'] in G or j['tail_id'] in G: continue
    print(k, j['head_canonical'], j['tail_canonical'])

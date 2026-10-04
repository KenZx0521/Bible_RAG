import json, random, re
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=(d.get('title'),d['content'])
B=[e for e in E if e['props'].get('backfilled') and e['t']!='place:dan']
random.seed(20261004)
for e in random.sample(B,16):
    pid=e['props']['source_pericope_id']; title,t=P.get(pid,('',''))
    other = e['hn'] if e['rel']=='PARTICIPATED_IN' else e['tn']
    ev = e['tn'] if e['rel']=='PARTICIPATED_IN' else e['hn']
    i=t.find(other)
    snip=t[max(0,i-50):i+50].replace('\n',' ') if i>=0 else '(not in text)'
    print(f"{e['hn']} -{e['rel']}-> {e['tn']} | pid={pid} title={title} | ev_in_text={ev in t}\n   ...{snip}...")

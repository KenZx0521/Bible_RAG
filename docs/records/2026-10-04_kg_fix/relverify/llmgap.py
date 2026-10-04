import json, random
from collections import Counter
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
who=Counter(); rows=[]
BOOKS={'路加','馬太','馬可','以賽亞','撒母耳','以西結','耶利米','約翰（使徒）','但以理','何西阿','約珥','阿摩司','俄巴底亞','約拿','彌迦','那鴻','哈巴谷','西番雅','哈該','撒迦利亞','瑪拉基','以斯拉','尼希米','以斯帖','約伯','路得','約書亞','雅各','猶大','彼得'}
for e in E:
    pr=e['props']
    if pr.get('extraction_phase')!=4: continue
    t=P.get(pr.get('source_pericope_id'),'')
    hl=[x for x in e['hl'] if x!='Entity'][0]; tl=[x for x in e['tl'] if x!='Entity'][0]
    miss=[n for n,ty in ((e['hn'],hl),(e['tn'],tl)) if ty!='Event' and n not in t]
    for m in miss: who[m]+=1
    if any(m in BOOKS for m in miss): rows.append((e['hn'],e['rel'],e['tn'],pr.get('source_pericope_id'),pr.get('evidence_span','')[:40]))
print(who.most_common(20)); print(len(rows))
random.seed(1)
for r in random.sample(rows,min(8,len(rows))): print(r)

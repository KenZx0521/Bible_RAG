import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, random
from collections import Counter
W=KGFIX_SP + '/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
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

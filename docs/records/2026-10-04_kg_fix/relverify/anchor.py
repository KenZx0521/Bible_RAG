import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, re
from collections import Counter, defaultdict
W=KGFIX_SP + '/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
def clauses(t):
    # split into clauses by sentence-level punct (keep 、，)
    return re.split(r'[。；：\n！？]', t)
def child_of(child, parent, t):
    # lenient: within one clause (split on 。；：), parent appears, then 的(長|次)?兒子/子/女兒, then child appears later in same clause (list allowed, any chars except 。；)
    for c in clauses(t):
        for m in re.finditer(re.escape(parent)+r'的(?:長|次|兩個|眾)?(?:兒子|子|女兒)', c):
            if child in c[m.end():]: return True
        m=re.search(re.escape(child)+r'(?:是|乃)[^，]{0,8}?'+re.escape(parent)+r'的(?:長|次)?(?:兒子|子|女兒)', c)
        if m: return True
        for m in re.finditer(re.escape(parent)+r'[^，]{0,4}?生(?:了)?', c):
            if child in c[m.end():]: return True
    return False
res=defaultdict(Counter)
for e in E:
    p=e['props']
    if p.get('extraction_phase')!=2: continue
    rel=e['rel']
    if rel not in ('SON_OF','FATHER_OF','DAUGHTER_OF','MOTHER_OF'): continue
    t=P.get(p.get('source_pericope_id'),'')
    h,tl=e['hn'],e['tn']
    if rel in ('SON_OF','DAUGHTER_OF'):
        fwd=child_of(h,tl,t); rev=child_of(tl,h,t)
    else:
        fwd=child_of(tl,h,t); rev=child_of(h,tl,t)
    k='fwd_only' if fwd and not rev else 'rev_only' if rev and not fwd else 'both' if fwd and rev else 'neither'
    res[rel][k]+=1
    res[rel+'|'+p.get('notes','')][k]+=1
for k in sorted(res): print(k, dict(res[k]), sum(res[k].values()))

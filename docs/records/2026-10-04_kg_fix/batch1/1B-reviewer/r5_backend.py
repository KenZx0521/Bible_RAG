"""Reviewer re-sim of 1-hop single-seed xref candidates under the C1+C2 Cypher
(seed_support DESC, curated DESC, votes DESC, id ASC; limit 10; weight 0.75/0.60):
old data vs new data. Seeds with <10 one-hop neighbours (fallback) reported separately."""
import json, pickle, collections
P='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/batch1plan/1B-reviewer/'
R='/home/kenzx0521/Bible_RAG/'
pairs,_=pickle.load(open(P+'r2_tsk.pkl','rb'))
xr=[json.loads(l) for l in open(R+'output/neo4j_relationships.jsonl')]
md=set((r['start'],r['end']) for r in xr if r['type']=='CROSS_REFERENCES' and r['properties']['source']=='markdown')
sp_old=set((r['start'],r['end']) for r in xr if r['type']=='CROSS_REFERENCES' and r['properties']['source']=='supplementary')
res=json.load(open(P+'r1_supp.json'))
X2={'rev 20:4','rev 19:1','rev 19:11-16'}
sp_new=set(tuple(p) for r in res if r['src'] not in X2 for p in r['new'])
sp_new.add(('rev:19:2','dan:2:3'))
def graph(cur, new):
    # edges: (a,b)->(curated, votes)
    E={}
    for p,v in pairs.items():
        if p in cur: continue
        E[p]=(False, v['votes'])
    for p in cur:
        E[p]=(True, pairs[p]['votes'] if (new and p in pairs) else None)
    # old data: TSK rows on curated pairs were swallowed -> curated edge has no votes
    if not new:
        for p in cur: E[p]=(True,None)
    nb=collections.defaultdict(dict)
    for (a,b),(c,v) in E.items():
        for s,t in ((a,b),(b,a)):
            if s==t: continue
            cc,vv=nb[s].get(t,(False,0))
            nb[s][t]=(cc or c, max(vv, v or 0))
    return nb
old=graph(md|sp_old, False); new=graph(md|sp_new, True)
peri=[json.loads(l)['id'] for l in open(R+'output/pericopes.jsonl')]
def top(nb,s):
    L=sorted(nb.get(s,{}).items(), key=lambda kv:(-kv[1][0], -kv[1][1], kv[0]))[:10]
    return [(t, 0.75 if c else 0.60) for t,(c,v) in L]
ch=ids=wt=0; sparse=0
for s in peri:
    if len(new.get(s,{}))<10 or len(old.get(s,{}))<10: sparse+=1
    a,b=top(old,s),top(new,s)
    if a!=b:
        if set(a)!=set(b):
            ch+=1
            if set(x for x,_ in a)!=set(x for x,_ in b): ids+=1
            else: wt+=1
print('singles',len(peri),'changed(set of id+weight)',ch,'id-set',ids,'weight-only',wt,'sparse(<10 nbrs, fallback not simulated)',sparse)
print('heb:1:0 new top8', top(new,'heb:1:0')[:8]); print('heb:1:0 old top8', top(old,'heb:1:0')[:8])

# --- tiebreak bias: in tie groups straddling the limit, who gets picked under id ASC?
import re
books=[json.loads(l)['id'] for l in open(R+'output/books.jsonl')]
order={b:i for i,b in enumerate(books)}
pick=pool=0; pick_d=pool_d=0; pick_ot=pool_ot=0
for s in peri:
    items=sorted(new.get(s,{}).items(), key=lambda kv:(-kv[1][0], -kv[1][1], kv[0]))
    if len(items)<=10: continue
    k=(items[9][1][0], items[9][1][1])
    grp=[t for t,(c,v) in items if (c,v)==k]
    if len(grp)<2 or items[10][1]!=items[9][1]: continue
    chosen=[t for t,_ in items[:10] if t in grp]
    pool+=len(grp); pick+=len(chosen)
    pool_d+=sum(t[0].isdigit() for t in grp); pick_d+=sum(t[0].isdigit() for t in chosen)
print(f'tie groups straddling limit: picked digit-prefixed {pick_d}/{pick} = {pick_d/pick:.2f} vs pool share {pool_d}/{pool} = {pool_d/pool:.2f}')

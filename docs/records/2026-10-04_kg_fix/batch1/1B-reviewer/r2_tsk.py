"""Reviewer re-simulation of TSK aggregation + curated overlap (independent of sim_tsk.py).
Uses import_tsk_crossrefs' own parse functions (no DB)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, sys, collections, pickle
ROOT=BIBLE_RAG_ROOT
sys.path.insert(0, ROOT+'/scripts')
import import_tsk_crossrefs as T
from pathlib import Path
OUT=KGFIX_SP + '/batch1plan/1B-reviewer/'
vmap=T.build_verse_map(Path(ROOT)/'output'/'embedding_queue.jsonl')
pairs=collections.defaultdict(lambda: {"votes":0,"verse_pairs":0})
vidx=collections.defaultdict(int)  # verse-level (from,to)->max votes, votes>=0
with open(ROOT+'/output/cross_references_tsk.txt') as f:
    next(f)
    for line in f:
        cols=line.rstrip('\n').split('\t')
        if len(cols)<3: continue
        try: votes=int(cols[2])
        except ValueError: continue
        if votes<0: continue
        fr=T.parse_ref(cols[0])
        if not fr: continue
        # verse-level index (expand to-range same chapter)
        to=cols[1]
        if '-' in to:
            lo,hi=to.split('-',1); lo=T.parse_ref(lo); hi=T.parse_ref(hi)
            tv=[] if not lo or not hi else ([(lo[0],lo[1],n) for n in range(lo[2],hi[2]+1)] if lo[:2]==hi[:2] else [lo,hi])
        else:
            s=T.parse_ref(to); tv=[s] if s else []
        for t in tv: vidx[(fr,t)]=max(vidx[(fr,t)],votes)
        fp=vmap.get(fr)
        if not fp: continue
        tps=T.expand_to_range(cols[1],vmap)
        for tp in tps:
            if tp==fp: continue
            s=pairs[(fp,tp)]; s['votes']=max(s['votes'],votes); s['verse_pairs']+=1
print('tsk rows',len(pairs))
rels=[json.loads(l) for l in open(ROOT+'/output/neo4j_relationships.jsonl')]
xr=[r for r in rels if r['type']=='CROSS_REFERENCES']
md=set((r['start'],r['end']) for r in xr if r['properties']['source']=='markdown')
sp_old=set((r['start'],r['end']) for r in xr if r['properties']['source']=='supplementary')
print('md',len(md),'supp_old',len(sp_old),'md&supp',len(md&sp_old))
cur_old=md|sp_old
print('old curated',len(cur_old),'swallowed (tsk rows on curated)',len(cur_old & set(pairs)), 'md',len(md&set(pairs)),'supp',len(sp_old&set(pairs)))
sw=[pairs[p]['votes'] for p in cur_old & set(pairs)]
import statistics
print(' swallowed votes median',statistics.median(sw),'max',max(sw),'>=50',sum(v>=50 for v in sw), 'verse_pairs sum', sum(pairs[p]['verse_pairs'] for p in cur_old&set(pairs)))
print('pure tsk live',len(set(pairs)-cur_old),'total live',len(set(pairs)|cur_old))
print('tsk votes>=999',[(p,v['votes']) for p,v in pairs.items() if v['votes']>=999])
res=json.load(open(OUT+'r1_supp.json'))
X2={'rev 20:4','rev 19:1','rev 19:11-16'}
for opt in ['c','a']:
    newsupp=set()
    for r in res:
        if r['src'] in X2: continue
        for p in r['new']: newsupp.add(tuple(p))
    if opt=='a': newsupp.add(('rev:19:2', vmap[('dan',2,47)]))
    cur_new=md|newsupp
    att=cur_new & set(pairs)
    print(f'opt {opt}: supp {len(newsupp)} curated {len(cur_new)} md&supp {len(md&newsupp)} attached {len(att)} curated_no_tsk {len(cur_new-set(pairs))} pure_tsk {len(set(pairs)-cur_new)} total {len(set(pairs)|cur_new)} delta {len(set(pairs)|cur_new)-len(set(pairs)|cur_old)}')
    # transitions
    removed=sp_old-newsupp; added=newsupp-sp_old
    print('   supp removed',len(removed),'of which in tsk',len(removed&set(pairs)),'gone',len(removed-set(pairs)-md),' added',len(added),'added in tsk',len(added&set(pairs)), 'kept',len(sp_old&newsupp))
    print('   md->cur+tsk',len(md&set(pairs)),'md->cur',len(md-set(pairs)),'supp(kept)->cur+tsk',len((sp_old&newsupp)&set(pairs)),'tsk->cur+tsk',len(added&set(pairs)))
# verse-level support for each def
def vs(spec):
    o=[]
    for part in spec.split(','):
        if '-' in part: a,b=part.split('-'); o+=range(int(a),int(b)+1)
        else: o.append(int(part))
    return o
sup=collections.Counter(); nos=[]
for r in res:
    sb,rest=r['src'].split(' '); sc,sv=rest.split(':'); tb,rest=r['tgt'].split(' '); tc,tv=rest.split(':')
    fwd=max([vidx.get(((sb,int(sc),a),(tb,int(tc),b)),-1) for a in vs(sv) for b in vs(tv)])
    rev=max([vidx.get(((tb,int(tc),b),(sb,int(sc),a)),-1) for a in vs(sv) for b in vs(tv)])
    k='fwd' if fwd>=0 else ('rev_only' if rev>=0 else 'none')
    sup[k]+=1
    if k!='fwd': nos.append((r['src'],r['tgt'],k))
    # pericope-level support (any pericope pair)
print('verse-level support',dict(sup),nos)
# per-anchor support (fanout per pericope subset)
anch=collections.Counter(); bad=[]
for r in res:
    if r['src'] in X2: continue
    sb=r['src'].split(' ')[0]; tb=r['tgt'].split(' ')[0]
    sc=int(r['src'].split(' ')[1].split(':')[0]); tc=int(r['tgt'].split(' ')[1].split(':')[0])
    for sp,svs in r['sp'].items():
        for tp,tvs in r['tp'].items():
            fwd=max([vidx.get(((sb,sc,a),(tb,tc,b)),-1) for a in svs for b in tvs])
            rev=max([vidx.get(((tb,tc,b),(sb,sc,a)),-1) for a in svs for b in tvs])
            k='fwd' if fwd>=0 else ('rev_only' if rev>=0 else 'none'); anch[k]+=1
            if k!='fwd': bad.append((r['src'],r['tgt'],sp,tp,k))
print('per-anchor support (excl XREF-2)',dict(anch),bad)
print('dan 2:47 support fwd', vidx.get((('rev',19,16),('dan',2,47))), 'rev', vidx.get((('dan',2,47),('rev',19,16))))
pickle.dump((dict(pairs),dict(vidx)),open(OUT+'r2_tsk.pkl','wb'))

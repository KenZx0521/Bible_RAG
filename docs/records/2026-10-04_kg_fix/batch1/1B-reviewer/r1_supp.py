"""Reviewer re-simulation (independent of planner's sim_supp.py):
resolve SUPPLEMENTARY_CROSS_REFS by verse coordinates, classify vs current output."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, sys, collections, pickle
ROOT=BIBLE_RAG_ROOT
sys.path.insert(0, ROOT)
from types import SimpleNamespace; from pathlib import Path  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
DEFS = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]
OUT=KGFIX_SP + '/batch1plan/1B-reviewer/'

vmap={}
for line in open(f'{ROOT}/output/embedding_queue.jsonl'):
    if '"verse"' not in line: continue
    r=json.loads(line)
    if r.get('type')!='verse': continue
    pid,vp=r['id'].split(':v:',1)
    b,c,_=pid.split(':')
    lo,hi=(vp.split('-')+[None])[:2] if '-' in vp else (vp,vp)
    for n in range(int(lo),int(hi)+1): vmap[(b,int(c),n)]=pid
peri=set(json.loads(l)['id'] for l in open(f'{ROOT}/output/pericopes.jsonl'))

def verses(spec):
    out=[]
    for part in spec.split(','):
        part=part.strip()
        if '-' in part:
            a,b=part.split('-'); out+=list(range(int(a),int(b)+1))
        else: out.append(int(part))
    return out

res=[]
for i,d in enumerate(DEFS):
    sb,sc,_=d.source_pericope_id.split(':'); tb,tc,_=d.target_pericope_id.split(':')
    sv=verses(d.source_verses); tv=verses(d.target_verses)
    smiss=[v for v in sv if (sb,int(sc),v) not in vmap]; tmiss=[v for v in tv if (tb,int(tc),v) not in vmap]
    sp=collections.OrderedDict(); tp=collections.OrderedDict()
    for v in sv:
        p=vmap.get((sb,int(sc),v));
        if p: sp.setdefault(p,[]).append(v)
    for v in tv:
        p=vmap.get((tb,int(tc),v))
        if p: tp.setdefault(p,[]).append(v)
    # old behaviour (process_bible:_supplement_cross_references)
    old_src=d.source_pericope_id
    first=int(d.target_verses.split(',')[0].split('-')[0])
    old_tgt=vmap.get((tb,int(tc),first)) or d.target_pericope_id
    old_kept = old_src in peri
    if old_kept and old_tgt not in peri: old_tgt=f'{tb}:{tc}'
    res.append(dict(i=i,src=f'{sb} {sc}:{d.source_verses}',tgt=f'{tb} {tc}:{d.target_verses}',
        old=(old_src,old_tgt) if old_kept else None, smiss=smiss,tmiss=tmiss,
        sp=dict(sp),tp=dict(tp),desc=d.description))

cnt=collections.Counter()
for r in res:
    if r['smiss'] or r['tmiss']: cnt['verse_missing']+=1
    newpairs=[(s,t) for s in r['sp'] for t in r['tp']]
    r['new']=newpairs
    if len(r['sp'])>1: cnt['src_fanout']+=1
    if len(r['tp'])>1: cnt['tgt_fanout']+=1
    if r['old'] is None: cnt['old_dropped']+=1
    elif r['old'] in newpairs:
        cnt['kept_fanout' if len(newpairs)>1 else 'kept']+=1
    else:
        # src fixed? tgt fixed?
        cnt['src_wrong' if r['old'][0] not in r['sp'] else 'tgt_wrong']+=1
print('defs',len(res),dict(cnt))
oldset=collections.Counter(r['old'] for r in res if r['old'])
print('old rows',sum(oldset.values()),'old distinct',len(oldset))
newset=collections.Counter(p for r in res for p in r['new'])
print('new anchors',sum(newset.values()),'new distinct pairs',len(newset), 'multi-def pairs',[(p,n) for p,n in newset.items() if n>1])
for r in res:
    if len(r['tp'])>1 or len(r['sp'])>1: print('fanout',r['src'],'>',r['tgt'],r['sp'],r['tp'])
json.dump(res,open(OUT+'r1_supp.json','w'),ensure_ascii=False,indent=0)

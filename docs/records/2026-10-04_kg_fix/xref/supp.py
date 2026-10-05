import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, sys, collections, re
sys.path.insert(0,BIBLE_RAG_ROOT)
from types import SimpleNamespace; from pathlib import Path  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
S = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]
R=BIBLE_RAG_ROOT + '/output/'
peri={}
vmap={}
for l in open(R+'pericopes.jsonl'):
    p=json.loads(l)
    vs=set()
    for v in p['verses']:
        n=v['num']
        if '-' in n:
            a,b=n.split('-'); rng=range(int(a),int(b)+1)
        else: rng=[int(n)]
        for x in rng:
            vs.add(x); vmap[(p['metadata']['book_id'],p['metadata']['chapter_num'],x)]=p['id']
    peri[p['id']]=dict(vs=vs,title=p['title'],vr=p['metadata']['verse_range'],book=p['metadata']['book_id'],ch=p['metadata']['chapter_num'],text={int(v['num'].split('-')[0]):v['text'] for v in p['verses']})
def nums(s):
    out=[]
    for part in s.split(','):
        part=part.strip()
        if '-' in part:
            a,b=part.split('-'); out+=list(range(int(a),int(b)+1))
        elif part: out.append(int(part))
    return out
rels=[json.loads(l) for l in open(R+'neo4j_relationships.jsonl')]
supp=[r for r in rels if r['type']=='CROSS_REFERENCES' and r['properties'].get('source')=='supplementary']
print('defs',len(S),'jsonl',len(supp))
bad_src=[];bad_tgt=[];rows=[]
dropped=[ref for ref in S if ref.source_pericope_id not in peri]
print('dropped (source pericope id nonexistent):',len(dropped))
for d in dropped: print('  DROP',d.source_pericope_id,d.source_verses,'->',d.target_pericope_id,d.target_verses,d.description, 'correct=',vmap.get((d.source_pericope_id.split(':')[0],int(d.source_pericope_id.split(':')[1]),nums(d.source_verses)[0])))
kept=[ref for ref in S if ref.source_pericope_id in peri]
assert len(kept)==len(supp)
for ref,r in zip(kept,supp):
    assert ref.source_pericope_id==r['start']
    sp=peri[r['start']]; tp=peri[r['end']]
    svs=nums(ref.source_verses); tvs=nums(ref.target_verses)
    s_in=all(v in sp['vs'] for v in svs)
    s_first_in = svs[0] in sp['vs']
    t_in=all(v in tp['vs'] for v in tvs)
    b,c,_=r['start'].split(':')
    correct_src=vmap.get((b,int(c),svs[0]))
    tb,tc,_=r['end'].split(':')
    correct_tgt=vmap.get((tb,int(tc),tvs[0]))
    rows.append(dict(start=r['start'],end=r['end'],sv=ref.source_verses,tv=ref.target_verses,s_first_in=s_first_in,s_all_in=s_in,t_all_in=t_in,correct_src=correct_src,correct_tgt=correct_tgt,desc=ref.description,svr=sp['vr'],tvr=tp['vr']))
n_first_out=sum(not x['s_first_in'] for x in rows)
n_all_out=sum(not x['s_all_in'] for x in rows)
n_t_out=sum(not x['t_all_in'] for x in rows)
print('src first verse not in start pericope:',n_first_out,' any src verse out:',n_all_out,' tgt any verse out:',n_t_out)
# unique pairs
uniq={}
for x in rows: uniq[(x['start'],x['end'])]=x  # last wins as MERGE SET +=
print('unique pairs',len(uniq))
print('unique pairs with first src verse out:',sum(not x['s_first_in'] for x in uniq.values()))
# misplaced with correct src
mis=[x for x in rows if not x['s_first_in']]
# offset of pericope index
off=collections.Counter()
for x in mis:
    a=int(x['start'].split(':')[2]); b=int(x['correct_src'].split(':')[2]) if x['correct_src'] else None
    off[(b-a) if b is not None else None]+=1
print('index offset (correct - hardcoded):',off)
by_book=collections.Counter(x['start'].split(':')[0] for x in mis)
tot_book=collections.Counter(x['start'].split(':')[0] for x in rows)
print({b:f"{by_book[b]}/{tot_book[b]}" for b in tot_book})
# collisions: correct pair already exists?
json.dump(rows,open(KGFIX_SP + '/kgfix/xref/supp_rows.json','w'),ensure_ascii=False,indent=1)
for x in mis[:80]:
    print(x['start'],x['svr'],'sv',x['sv'],'->',x['correct_src'],'|',x['end'],x['tv'],x['desc'])
print('--- tgt partial out')
for x in rows:
    if not x['t_all_in']: print(x['start'],x['end'],x['tvr'],x['tv'],x['correct_tgt'],x['desc'])

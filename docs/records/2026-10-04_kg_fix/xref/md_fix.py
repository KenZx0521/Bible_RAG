"""Prototype of a context-carrying cross-ref parser; compares against current 774 markdown edges."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, re, sys, pickle, collections
sys.path.insert(0,BIBLE_RAG_ROOT)
from bible_chunking.config import CROSS_REF_ABBREV
R=BIBLE_RAG_ROOT + '/output/'
D=KGFIX_SP + '/kgfix/xref/'
vmap={}; peri=[]
for l in open(R+'pericopes.jsonl'):
    p=json.loads(l); m=p['metadata']
    for v in p['verses']:
        n=v['num']
        for x in range(int(n.split('-')[0]),int(n.split('-')[-1])+1): vmap[(m['book_id'],m['chapter_num'],x)]=p['id']
    peri.append(p)
ABK=sorted(CROSS_REF_ABBREV,key=len,reverse=True)
SEG=re.compile(r'^(?P<bk>'+'|'.join(map(re.escape,ABK))+r')?(?P<body>[\d‧－\-，,]+)$')
def parse(text, own_book, ctx):
    """returns list of (book, ch, vs, ch_end, ve) ranges"""
    out=[]; book=ctx.get('book'); ch=ctx.get('ch')
    for part in text.strip('（）()').split('；'):
        part=part.strip()
        if not part or part=='細拉': continue
        m=SEG.match(part)
        if not m: return None
        if m.group('bk'): book=CROSS_REF_ABBREV[m.group('bk')]
        elif book is None: book=own_book   # same-book reference, no abbreviation
        body=m.group('body')
        if re.fullmatch(r'\d+',body):     # chapter-only, e.g. 詩18
            ch=int(body); out.append((book,ch,1,ch,None)); continue
        for sub in re.split(r'[，,]',body):
            mm=re.fullmatch(r'(?:(\d+)‧)?(\d+)(?:[－\-](?:(\d+)‧)?(\d+))?',sub)
            if not mm: return None
            c1,v1,c2,v2=mm.groups()
            if c1: ch=int(c1)
            if ch is None: return None
            vs=int(v1); ce=int(c2) if c2 else ch; ve=int(v2) if v2 else vs
            out.append((book,ch,vs,ce,ve)); ch=ce
    ctx['book']=book; ctx['ch']=ch
    return out
pairs=collections.defaultdict(list); fails=[]
for p in peri:
    own=p['metadata']['book_id']
    raw=[c['reference_text'] for c in p['cross_references']]
    ctx={}
    for t in raw:
        res=parse(t,own,ctx)
        if res is None: fails.append((p['id'],t)); continue
        for (b,c,vs,ce,ve) in res:
            # all pericopes touched by the range
            touched=[]
            cc,vv=c,vs
            while True:
                q=vmap.get((b,cc,vv))
                if q is None:
                    if (b,cc+1,1) in vmap and (ce>cc): cc+=1; vv=1; continue
                    break
                if q not in touched: touched.append(q)
                if ve is None and cc==c: pass
                if (cc,vv)==(ce,ve if ve else 10**6): break
                vv+=1
                if ve is None and (b,cc,vv) not in vmap: break
            for q in touched:
                if q!=p['id']: pairs[(p['id'],q)].append(t)
print('parse failures:',len(fails), fails[:10])
rels=[json.loads(l) for l in open(R+'neo4j_relationships.jsonl')]
cur=set((r['start'],r['end']) for r in rels if r['type']=='CROSS_REFERENCES' and r['properties']['source']=='markdown')
new=set(pairs)
print('fixed-parser pairs:',len(new),' current md pairs:',len(cur),' kept:',len(new&cur),' added:',len(new-cur),' current-not-in-new:',len(cur-new))
tsk=pickle.load(open(D+'tsk_pairs.pkl','rb'))
added=new-cur
print('added pairs with TSK support (either dir):',sum(((a,b) in tsk or (b,a) in tsk) for a,b in added))
by=collections.Counter()
for a,b in added:
    by['span_extra' if any(a==x[0] and (x[1] in [y[1] for y in cur if y[0]==a]) for x in []) else 'x']+=1
for k in sorted(added)[:60]: print('  +',k,pairs[k][0])
print([k for k in cur-new][:10])
cat=collections.Counter()
unparsed_texts=set()
for p in peri:
    for c in p['cross_references']:
        if not c.get('book_id'): unparsed_texts.add((p['id'],c['reference_text']))
for (a,b) in added:
    t=pairs[(a,b)][0]
    if a.startswith('job:') and b.startswith('job:'): cat['job_self_range_annotation']+=1
    elif (a,t) in unparsed_texts: cat['previously_unparsed_ref']+=1
    else: cat['span_completion(multi-pericope/cross-chapter)']+=1
print(cat)

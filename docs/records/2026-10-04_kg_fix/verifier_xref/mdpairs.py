"""Prototype of a context-carrying cross-ref parser; compares against current 774 markdown edges."""
import json, re, sys, pickle, collections
sys.path.insert(0,'/home/kenzx0521/Bible_RAG')
from bible_chunking.config import CROSS_REF_ABBREV
R='/home/kenzx0521/Bible_RAG/output/'
D='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/xref/'
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
import json as _j
from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS as S
def first(s): return int(s.split(',')[0].split('-')[0])
cs=set()
for r in S:
    b,c,_=r.source_pericope_id.split(':'); tb,tc,_=r.target_pericope_id.split(':')
    cs.add((vmap[(b,int(c),first(r.source_verses))], vmap[(tb,int(tc),first(r.target_verses))]))
newmd={k for k in pairs if not (k[0].startswith('job:') and k[1].startswith('job:'))}
print('fixed md pairs (excl job)',len(newmd),'overlap with corrected supp same-dir',len(newmd&cs), sorted(newmd&cs)[:10])

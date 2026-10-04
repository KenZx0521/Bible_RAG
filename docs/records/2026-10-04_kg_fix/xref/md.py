import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, collections, re
R=BIBLE_RAG_ROOT + '/output/'
peri={}; vmap={}; order=[]
for l in open(R+'pericopes.jsonl'):
    p=json.loads(l); m=p['metadata']
    vs=set()
    for v in p['verses']:
        n=v['num']
        rng=range(int(n.split('-')[0]),int(n.split('-')[-1])+1)
        for x in rng: vs.add(x); vmap[(m['book_id'],m['chapter_num'],x)]=p['id']
    peri[p['id']]=dict(vs=vs,vr=m['verse_range'],title=p['title'],crs=p['cross_references'],book=m['book_id'],ch=m['chapter_num'])
    order.append(p['id'])
allcr=[(pid,c) for pid in order for c in peri[pid]['crs']]
print('total md cross_refs parsed:',len(allcr))
unparsed=[(pid,c) for pid,c in allcr if not (c.get('book_id') and c.get('chapter'))]
print('unparsed (no book_id/chapter):',len(unparsed))
for pid,c in unparsed[:20]: print('  ',pid,repr(c['reference_text']), c.get('book_name'))
parsed=[(pid,c) for pid,c in allcr if c.get('book_id') and c.get('chapter')]
print('parsed:',len(parsed))
# raw text features
multi=[(pid,c) for pid,c in parsed if re.search(r'[，,]', c['reference_text']) or re.search(r'[－\-]\d+[‧·\.]\d+', c['reference_text'])]
print('ref_text with comma segments or cross-chapter range (info lost):',len(multi))
for pid,c in multi[:15]: print('  ',pid,c['reference_text'],c['chapter'],c['verse_start'],c['verse_end'])
# resolution
res=collections.Counter(); spans=[]; outs=[]
for pid,c in parsed:
    t=vmap.get((c['book_id'],c['chapter'],c['verse_start']))
    if not t: res['unresolved']+=1; outs.append((pid,c)); continue
    # how many pericopes covered by verse_start..verse_end
    covered=[]
    for v in range(c['verse_start'],(c['verse_end'] or c['verse_start'])+1):
        q=vmap.get((c['book_id'],c['chapter'],v))
        if q and q not in covered: covered.append(q)
    if len(covered)>1: res['span_multi_pericope']+=1; spans.append((pid,c,covered))
    else: res['single']+=1
print(res)
for pid,c in outs[:10]: print(' UNRES',pid,c)
for pid,c,cov in spans[:10]: print(' SPAN',pid,c['reference_text'],cov)
# self loops / testament
rels=[json.loads(l) for l in open(R+'neo4j_relationships.jsonl')]
md=[r for r in rels if r['type']=='CROSS_REFERENCES' and r['properties'].get('source')=='markdown']
print('md jsonl rels',len(md),'self-loops',sum(r['start']==r['end'] for r in md))
pairs=collections.Counter((r['start'],r['end']) for r in md)
print('dup md pairs',sum(v-1 for v in pairs.values() if v>1))
# symmetric coverage: A->B present, B->A present?
ps=set(pairs)
print('reciprocal present',sum((b,a) in ps for a,b in ps),'of',len(ps))
# same-book
print('same book',sum(a.split(':')[0]==b.split(':')[0] for a,b in ps))
# verse end checks: target verse_start in end pericope
bad=0
for r in md:
    pr=r['properties']; e=peri[r['end']]
    if pr['verse_start'] not in e['vs']: bad+=1
print('md target verse_start not in end pericope:',bad)
books=collections.Counter(r['start'].split(':')[0] for r in md)
print(books.most_common(70))

import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
ROOT=BIBLE_RAG_ROOT
sys.path.insert(0, ROOT+'/scripts')
from kg_validate.checks_r import _verses
peri={}
for l in open(ROOT+'/output/pericopes.jsonl'):
    r=json.loads(l); peri[r['id']]=r.get('verse_range') or (r.get('metadata') or {}).get('verse_range')
last={}
for l in open(ROOT+'/output/neo4j_relationships.jsonl'):
    r=json.loads(l)
    if r['type']=='CROSS_REFERENCES' and r['properties']['source']=='supplementary':
        last[(r['start'],r['end'])]=r['properties']
first=anyv=unp=0; srcbad=tgtbad=0
for (s,t),p in last.items():
    ws,wt=_verses(p['source_verses']),_verses(p['target_verses'])
    hs,ht=_verses(peri.get(s)),_verses(peri.get(t))
    if None in (ws,wt,hs,ht): unp+=1; continue
    if not (ws[0] in hs and wt[0] in ht): first+=1
    a=all(v in hs for v in ws); b=all(v in ht for v in wt)
    if not (a and b): anyv+=1
    srcbad+= not a; tgtbad += not b
print('edges',len(last),'first-verse misaligned',first,'any-verse',anyv,'src',srcbad,'tgt',tgtbad,'unparsed',unp)

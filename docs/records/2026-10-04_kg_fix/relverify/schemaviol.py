import json, sys
sys.path.insert(0,'/home/kenzx0521/Bible_RAG')
from collections import Counter
from pathlib import Path
from scripts.relation_extraction.schema_loader import RelationSchema
S=RelationSchema.load(Path('/home/kenzx0521/Bible_RAG/config/relations/biblical_relations.yaml'))
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
c=Counter(); ex=Counter()
for e in E:
    hl=[x for x in e['hl'] if x!='Entity']; tl=[x for x in e['tl'] if x!='Entity']
    ent=S.get(e['rel'])
    if ent is None: c['unknown_rel']+=1; continue
    ok=any(ent.accepts_pair(a,b) for a in hl for b in tl)
    if not ok:
        c['violation']+=1; ex[(e['rel'],tuple(hl),tuple(tl), e['h'] if 'yehehua' in e['h'] else e['t'] if 'yehehua' in e['t'] else 'other')]+=1
print(c); print(ex.most_common(12))

import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, sys
sys.path.insert(0,BIBLE_RAG_ROOT)
from collections import Counter
from pathlib import Path
from scripts.relation_extraction.schema_loader import RelationSchema
S=RelationSchema.load(Path(BIBLE_RAG_ROOT + '/config/relations/biblical_relations.yaml'))
W=KGFIX_SP + '/kgfix/relverify/'
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

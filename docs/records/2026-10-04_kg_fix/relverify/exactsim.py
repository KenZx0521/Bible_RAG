import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
sys.path.insert(0,BIBLE_RAG_ROOT)
from collections import Counter, defaultdict
from pathlib import Path
from scripts.relation_extraction.schema_loader import RelationSchema
from scripts.relation_extraction.pair_miner import _trim_grounding
from scripts.relation_extraction.models import RelationCandidate
from scripts.relation_extraction.rule_classifier import classify_by_rules
schema = RelationSchema.load(Path(BIBLE_RAG_ROOT + '/config/relations/biblical_relations.yaml'))
ENT={}
for l in open(BIBLE_RAG_ROOT + '/output/entities.jsonl'):
    d=json.loads(l); ENT[d['entity_id']]=(d['canonical_name'], d['type'])
P={}
for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl'):
    d=json.loads(l); P[d['id']]=d['content']
J=[json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/relations.jsonl')]
rule_keys={(j['head_id'],j['tail_id'],j['relation']) for j in J if j['extraction_phase']==2}
stats=Counter(); order=[]
for l in open(BIBLE_RAG_ROOT + '/output/relations_checkpoint.jsonl'):
    k=json.loads(l)['pair_key']; a,b,pid=k.split('|',2)
    if a not in ENT or b not in ENT: stats['missing_entity']+=1; continue
    order.append((a,b,pid))
stats['ckpt_pairs']=len(order)
pending=[]; rulehit=0
for a,b,pid in order:
    (na,ta),(nb,tb)=ENT[a],ENT[b]
    t=P.get(pid,'')
    g=_trim_grounding(t,na,nb,1)
    c=RelationCandidate(a,b,ta,tb,na,nb,pid,g)
    rm=classify_by_rules(c,schema)
    if rm and rm.confidence>=0.85: rulehit+=1; continue
    pending.append(c)
stats['rule_hits_resim']=rulehit; stats['llm_pending']=len(pending)
by=defaultdict(list)
for c in pending: by[c.source_pericope_id].append(c)
for pid,grp in by.items():
    for i in range(0,len(grp),8):
        batch=grp[i:i+8]; ctx=batch[0].grounding_text
        for k,c in enumerate(batch):
            if k==0: continue
            stats['k>0']+=1
            names=[(c.head_canonical,c.head_type),(c.tail_canonical,c.tail_type)]
            miss_shown=[n for n,ty in names if ty!='Event' and n not in ctx]
            if not miss_shown: continue
            stats['k>0_missing_in_shown']+=1
            # was it present in own grounding (bug-caused) ?
            if all(n in c.grounding_text for n in miss_shown):
                stats['k>0_missing_in_shown_but_in_own']+=1
            if all(n in P.get(pid,'') for n in miss_shown):
                stats['k>0_missing_in_shown_but_in_pericope']+=1
print(dict(stats))

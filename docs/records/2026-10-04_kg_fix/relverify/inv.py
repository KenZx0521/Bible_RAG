import json
from collections import Counter
W='/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/relverify/'
E=json.load(open(W+'edges.json'))
J=[json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/relations.jsonl')]
KIN={'FATHER_OF','SON_OF','MOTHER_OF','DAUGHTER_OF','SIBLING_OF','SPOUSE_OF','ANCESTOR_OF','DESCENDANT_OF'}
# use jsonl (pipeline truth) for source mapping
jk={(j['head_id'],j['tail_id'],j['relation']):j for j in J}
c=Counter(); c2=Counter()
for j in J:
    if j['extraction_phase']!=5: continue
    src=j['notes'].split('=')[1]
    s=jk.get((j['tail_id'],j['head_id'],src))
    c[(j['relation'] in KIN, s['extraction_phase'] if s else None)]+=1
print('jsonl inverse by (kin, src phase):',c)
# live
lk={(e['h'],e['t'],e['rel']):e for e in E}
c=Counter()
for e in E:
    n=e['props'].get('notes') or ''
    if not n.startswith('derived_from='): continue
    src=n.split('=')[1]
    s=lk.get((e['t'],e['h'],src))
    c[(e['rel'] in KIN, s['props'].get('extraction_phase') if s else None)]+=1
print('live inverse by (kin, src phase):',c)
# inverse of FATHER_OF derived from DAUGHTER_OF
print('FATHER_OF from DAUGHTER_OF live', sum(1 for e in E if e['rel']=='FATHER_OF' and (e['props'].get('notes') or '')=='derived_from=DAUGHTER_OF'))
print('FATHER_OF from SON_OF live', sum(1 for e in E if e['rel']=='FATHER_OF' and (e['props'].get('notes') or '')=='derived_from=SON_OF'))
print('SON_OF from MOTHER_OF live', sum(1 for e in E if e['rel']=='SON_OF' and (e['props'].get('notes') or '')=='derived_from=MOTHER_OF'))

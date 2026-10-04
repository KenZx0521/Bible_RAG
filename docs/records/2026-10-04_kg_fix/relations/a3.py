import json
from collections import Counter, defaultdict
E = json.load(open('edges.json'))
KIN = {'FATHER_OF','SON_OF','MOTHER_OF','DAUGHTER_OF','SIBLING_OF','SPOUSE_OF','ANCESTOR_OF','DESCENDANT_OF'}
# map inverse conf -> source phase via exact value
rule_c = {0.95,0.92,0.90,0.93,0.85}; llm_c = {0.80,0.78,0.75,0.70}; prior_c={0.99,0.95}
c = Counter()
for e in E:
    if e['rel'] not in KIN: continue
    pr = e['props']; ph = pr['extraction_phase']; conf = pr['confidence']
    if ph == 5:
        src = round(conf/0.9, 3)
        tag = 'inv<-prior' if src in (0.99,) else 'inv<-rule' if src in (0.95,0.92,0.85) else 'inv<-llm' if src in (0.8,0.78,0.7) else f'inv<-?{src}'
        c[tag]+=1
    else:
        c[{2:'rule',3:'prior',4:'llm'}[ph]] += 1
print(c, sum(c.values()))
# relation-level breakdown of inverses
d = defaultdict(Counter)
for e in E:
    if e['rel'] in KIN and e['props']['extraction_phase']==5:
        d[e['rel']][e['props']['notes']+f"@{e['props']['confidence']}"]+=1
for k,v in d.items(): print(k, dict(v))
# gender errors via inverse: DAUGHTER_OF->FATHER_OF, MOTHER_OF->SON_OF ok, SON_OF(x, mother)->FATHER_OF(mother,x)
fem = Counter()
for e in E:
    if e['rel']=='FATHER_OF' and e['props'].get('notes')=='derived_from=DAUGHTER_OF':
        fem['FATHER_OF<-DAUGHTER_OF']+=1
print(fem)

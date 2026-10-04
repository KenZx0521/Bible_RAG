import json
from collections import Counter, defaultdict
E = json.load(open('edges.json'))
KIN = {'FATHER_OF','SON_OF','MOTHER_OF','DAUGHTER_OF','SIBLING_OF','SPOUSE_OF','ANCESTOR_OF','DESCENDANT_OF'}
c = Counter()
for e in E:
    p = e['props']
    c[(e['rel'], p.get('extraction_phase'), bool(p.get('backfilled')))] += 1
by = defaultdict(dict)
for (rel, ph, bf), n in c.items():
    by[rel][f"{ph}{'b' if bf else ''}"] = n
for rel in sorted(by, key=lambda r: -sum(by[r].values())):
    print(rel, sum(by[rel].values()), dict(sorted(by[rel].items())))
# direction mechanism: rule phase (2) edges: head_id < tail_id ?
print('--- rule-phase lexicographic order (head_id < tail_id) by relation')
o = defaultdict(Counter)
for e in E:
    ph = e['props'].get('extraction_phase')
    if ph in (2,4):
        o[(ph, e['rel'])][e['h'] < e['t']] += 1
for k in sorted(o):
    print(k, dict(o[k]))

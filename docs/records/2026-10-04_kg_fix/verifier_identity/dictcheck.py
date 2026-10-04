import sys, collections
sys.path.insert(0,'/home/kenzx0521/Bible_RAG/scripts')
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT, find_canonical_name
D={'Person':PERSON_DICT,'Place':PLACE_DICT,'Group':GROUP_DICT}
types=collections.defaultdict(list)
for t,d in D.items():
    names=set()
    for c,a in d.items(): names|=set(a)
    for n in names: types[n].append(t)
cross={n:ts for n,ts in types.items() if len(ts)>1}
print('cross-type names', cross)
# final type in _all_entities
final={}
for t in ['Person','Place','Group']:
    for n,ts in types.items():
        if t in ts: final[n]=t
# Which dict entries never reachable: canonical c in dict t, for all its aliases a: final[a]!=t or find_canonical_name(a,t)!=c
for t,d in D.items():
    unreach=[]
    for c,a in d.items():
        ok=False
        for x in a:
            if final.get(x)==t and find_canonical_name(x,t)==c: ok=True
        if not ok: unreach.append(c)
    print(t,'unreachable via dict:',unreach)
# ambiguous within-type aliases
for t,d in D.items():
    own=collections.defaultdict(list)
    for c,a in d.items():
        for x in a: own[x].append(c)
    print(t,'ambiguous', {k:v for k,v in own.items() if len(v)>1})

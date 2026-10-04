import json, collections, sys
sys.path.insert(0,'scripts')
from entity_extraction.entity_dict import PERSON_DICT, PLACE_DICT, GROUP_DICT
ents={}
for l in open('output/entities.jsonl'):
    e=json.loads(l); ents[e['entity_id']]=e
spans=collections.defaultdict(collections.Counter)
for l in open('output/entity_mentions.jsonl'):
    m=json.loads(l)
    spans[m['entity_id']][m['text_span']]+=1
D={'Person':PERSON_DICT,'Place':PLACE_DICT,'Group':GROUP_DICT}
res=collections.defaultdict(list)
for eid,c in spans.items():
    e=ents.get(eid)
    if not e: continue
    t=e['type']
    canon=e['canonical_name']
    allowed={canon}|set(e['aliases'])
    d=D.get(t,{})
    for k,v in d.items():
        if k==canon: allowed|=v
    others={s:n for s,n in c.items() if s not in allowed}
    if others:
        res[t].append((eid,canon,dict(c)))
for t,v in res.items():
    print(t, len(v))
out={t:v for t,v in res.items()}
json.dump(out, open(sys.argv[1],'w'), ensure_ascii=False, indent=1)
for eid,canon,c in sorted(res['Person'], key=lambda x:-sum(x[2].values()))[:60]:
    print(eid, canon, c)

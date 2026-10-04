import json, collections
ids=set(json.load(open('ids268.json')))
ents={}
for l in open('/home/kenzx0521/Bible_RAG/output/entities.jsonl'):
    e=json.loads(l); ents[e['entity_id']]=e
pairs=collections.defaultdict(set)
for l in open('/home/kenzx0521/Bible_RAG/output/entity_mentions.jsonl'):
    m=json.loads(l)
    if m['entity_id'] not in ids: continue
    sid=m['source_id']; st=m.get('source_type','')
    if st=='verse' or ':v:' in sid: sid=sid.split(':v:')[0]
    pairs[(sid,m['entity_id'])].add(m['text_span'].strip())
multi=[(k,v) for k,v in pairs.items() if len(v)>1]
print('source-entity pairs',len(pairs),'with >1 surface',len(multi))
c=collections.Counter(k[1] for k,v in multi)
print(c.most_common(10))
print([ (k,sorted(v)) for k,v in multi if k[1] in ('person:mijia','person:lude','person:feili','person:xila')][:10])

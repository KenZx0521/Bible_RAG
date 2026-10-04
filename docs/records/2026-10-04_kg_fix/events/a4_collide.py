import json,collections,sys
from pypinyin import lazy_pinyin
ents={}
for l in open('output/entities.jsonl'):
    e=json.loads(l); ents[e['entity_id']]=e
# mentions per event id: which text_spans
spans=collections.defaultdict(collections.Counter)
for l in open('output/entity_mentions.jsonl'):
    r=json.loads(l)
    if r['entity_id'].startswith(('event:','object:','theme:')):
        spans[r['entity_id']][r.get('text_span')]+=1
multi={k:v for k,v in spans.items() if len(v)>1}
ev_multi={k:v for k,v in multi.items() if k.startswith('event:')}
print('E/O/T ids whose mentions carry >1 distinct text_span (homophone merge):',len(multi),'events:',len(ev_multi))
for k,v in list(ev_multi.items())[:40]:
    print(' ',k,ents.get(k,{}).get('canonical_name'),dict(v))

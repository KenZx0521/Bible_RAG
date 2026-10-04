import json, collections
ents=[json.loads(l) for l in open('output/entities.jsonl')]
ev=[e for e in ents if e['type']=='Event']
print('jsonl events', len(ev))
print(collections.Counter(e['extraction_method'] for e in ev))
titles=collections.defaultdict(list)
for l in open('output/pericopes.jsonl'):
    p=json.loads(l); titles[p['title'].strip()].append(p['id'])
print('pericopes',sum(len(v) for v in titles.values()),'unique titles',len(titles))
eq=[e for e in ev if e['canonical_name'] in titles]
print('event name == some pericope title:', len(eq))
print(collections.Counter(e['extraction_method'] for e in eq))
neq=[e for e in ev if e['canonical_name'] not in titles]
print('not title:',len(neq), collections.Counter(e['extraction_method'] for e in neq))
print([ (e['canonical_name'],e['extraction_method'],e['mention_count']) for e in sorted(neq,key=lambda x:-x['mention_count'])[:60]])
# mentions per event in jsonl
m=collections.defaultdict(set)
for l in open('output/entity_mentions.jsonl'):
    r=json.loads(l)
    if r['entity_id'].startswith('event:'):
        sid=r['source_id'].split(':v:')[0]
        m[r['entity_id']].add((r['source_type'],sid))
srctypes=collections.Counter()
for k,v in m.items():
    for st,_ in v: srctypes[st]+=1
print('event mention source types', srctypes)
# description check
d_eq_prefix=0
for e in ev:
    d=e.get('description') or ''
    ids=titles.get(e['canonical_name'],[])
print('desc lens', collections.Counter(min(len(e.get('description') or ''),100)//10*10 for e in ev))

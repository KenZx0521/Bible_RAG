import json,re,collections
P={}; bytitle=collections.defaultdict(list)
for l in open('output/pericopes.jsonl'):
    p=json.loads(l); P[p['id']]=p; bytitle[p['title'].strip()].append(p['id'])
def full(pid):
    vs=re.findall(r'\*\*\d+\*\*\s*(.*)',P[pid]['content'])
    return " ".join(v.strip() for v in vs)
ents=[json.loads(l) for l in open('output/entities.jsonl')]
ev=[e for e in ents if e['type']=='Event']
cat=collections.Counter(); ex={}
for e in ev:
    d=e.get('description') or ''
    pids=bytitle.get(e['canonical_name'],[])
    fulls=[full(p) for p in pids]
    if not d: k='empty'
    elif any(f[:100]==d for f in fulls): k='prefix100_of_title_pericope'
    elif any(f.startswith(d) for f in fulls): k='prefix_short_of_title_pericope'
    elif any(d in f for f in fulls): k='substring_of_title_pericope (LLM evidence)'
    else: k='other'
    cat[(k,e['extraction_method'])]+=1
    ex.setdefault(k,[]).append((e['canonical_name'],d[:50]))
for k,v in sorted(cat.items()): print(k,v)
for k in ex: print(k, ex[k][:4])

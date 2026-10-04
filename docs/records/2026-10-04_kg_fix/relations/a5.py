import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re
from collections import Counter, defaultdict
E = json.load(open('edges.json')); N = json.load(open('entities.json'))
P = {json.loads(l)['id']: json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')}
names = set()
for e in N:
    if e['n']: names.add(e['n'].strip())
    for a in (e['aliases'] or []): names.add(a.strip())
names = {n for n in names if len(n)>=2}
def shadowed_nonprefix(name, text):
    """True if every occurrence of `name` lies inside a longer known name that does NOT start with `name`."""
    name = name.strip()
    if not name or name not in text: return None
    longer = [m for m in names if len(m) > len(name) and name in m and not m.startswith(name) and m in text]
    if not longer: return False
    cov = [False]*len(text)
    for m in longer:
        for mm in re.finditer(re.escape(m), text):
            for i in range(mm.start(), mm.end()): cov[i] = True
    return all(all(cov[i] for i in range(mm.start(), mm.end())) for mm in re.finditer(re.escape(name), text))
res = defaultdict(Counter); top = Counter(); ex=defaultdict(list)
for e in E:
    pr = e['props']; pid = pr.get('source_pericope_id')
    if not pid or pid not in P: continue
    t = P[pid]['content']
    src = 'backfill' if pr.get('backfilled') else {2:'rule',4:'llm',5:'inverse'}.get(pr['extraction_phase'])
    bad = False
    for nm, ty in ((e['hn'], e['ht']), (e['tn'], e['tt'])):
        if ty in ('Person','Place','Group') and shadowed_nonprefix(nm or '', t):
            bad = True; top[(nm.strip(), ty)] += 1
    res[src]['shadowed' if bad else 'ok'] += 1
    if bad and len(ex[src])<8: ex[src].append((e['hn'], e['rel'], e['tn'], pid))
for s in res: print(s, dict(res[s]), round(res[s]['shadowed']/sum(res[s].values()),3))
print(top.most_common(30))
for s in ex: print(s, ex[s])

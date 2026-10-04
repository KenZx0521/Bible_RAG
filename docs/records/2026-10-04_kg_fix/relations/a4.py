import json, re
from collections import Counter, defaultdict
E = json.load(open('edges.json')); N = json.load(open('entities.json'))
P = {json.loads(l)['id']: json.loads(l) for l in open('/home/kenzx0521/Bible_RAG/output/pericopes.jsonl')}
# extra longer names: all canonical names + aliases + place-suffix forms (e.g., 亞拿突 might not be an entity)
names = set()
for e in N:
    if e['n']: names.add(e['n'].strip())
    for a in (e['aliases'] or []): names.add(a.strip())
names = {n for n in names if len(n)>=2}
by_len = sorted(names, key=len, reverse=True)
def standalone(name, text):
    name = name.strip()
    if not name or name not in text: return 'absent'
    longer = [m for m in by_len if len(m) > len(name) and name in m and m in text]
    covered = [False]*len(text)
    for m in longer:
        for mm in re.finditer(re.escape(m), text):
            for i in range(mm.start(), mm.end()): covered[i] = True
    for mm in re.finditer(re.escape(name), text):
        if not all(covered[i] for i in range(mm.start(), mm.end())):
            return 'standalone'
    return 'shadowed'
res = defaultdict(Counter)
ex = defaultdict(list)
for e in E:
    pr = e['props']; pid = pr.get('source_pericope_id')
    if not pid or pid not in P: continue
    t = P[pid]['content']
    hs = standalone(e['hn'] or '', t) if e['ht'] != 'Event' else 'event'
    ts = standalone(e['tn'] or '', t) if e['tt'] != 'Event' else 'event'
    bad = 'shadowed' in (hs, ts)
    absent = 'absent' in (hs, ts)
    src = 'backfill' if pr.get('backfilled') else {2:'rule',4:'llm',5:'inverse'}.get(pr['extraction_phase'], str(pr['extraction_phase']))
    k = 'shadowed' if bad else 'absent' if absent else 'ok'
    res[src][k] += 1
    if bad and len(ex[src])<12: ex[src].append((e['hn'], e['rel'], e['tn'], pid, hs, ts))
for s in res: print(s, dict(res[s]), sum(res[s].values()))
for s in ex:
    print('==', s)
    for x in ex[s]: print('  ', x)

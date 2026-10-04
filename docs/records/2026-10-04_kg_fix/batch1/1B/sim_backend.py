"""1B offline simulation of backend xref candidate lists: OLD vs TRANS (step 1 of deploy) vs NEW (step 2).
(A) every Pericope as a single seed; (B) 500 questions, proxy seeds; (C) kg_xref 68 gold reachability."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, collections
from common import *
from xrefgraph import graphs
gO, gT, gN = graphs()
vmap, peri = load_pericopes()
P = sorted(peri)
def cmp(a, b):
    ids_a = [r[0] for r in a]; ids_b = [r[0] for r in b]
    return dict(set=set(ids_a) != set(ids_b), order=ids_a != ids_b,
                weight=[(r[0], r[2]) for r in a] != [(r[0], r[2]) for r in b] and set(ids_a) == set(ids_b) and ids_a == ids_b,
                any=a != b)
# (A) single-seed
deg = collections.Counter(len({t for t, _ in gO.adj.get(p, ())}) for p in P)
print('pericopes', len(P), ' seeds with <10 distinct neighbours (fallback fires, OLD data):', sum(n for d, n in deg.items() if d < 10),
      ' zero-degree:', deg.get(0, 0))
res = collections.Counter(); ties = collections.Counter(); per = {}
for p in P:
    o, to, fo = gO.multi_hop([p]); t, tt, ft = gT.multi_hop([p]); n, tn, fn = gN.multi_hop([p])
    c1 = cmp(o, t); c2 = cmp(o, n); c3 = cmp(t, n)
    for k, v in c1.items(): res['OLD→TRANS ' + k] += v
    for k, v in c2.items(): res['OLD→NEW ' + k] += v
    for k, v in c3.items(): res['TRANS→NEW ' + k] += v
    ties['OLD boundary tie'] += to; ties['NEW boundary tie'] += tn
    res['fallback OLD'] += fo; res['fallback NEW'] += fn
    per[p] = dict(old=o, trans=t, new=n)
for k in sorted(res): print(f'  (A) {k}: {res[k]}')
print('  (A) ties at limit:', dict(ties))
# weight-only changes OLD->TRANS: break down cause
cause = collections.Counter()
for p, d in per.items():
    if d['old'] != d['trans']:
        hops = {r[1] for r in d['old']} | {r[1] for r in d['trans']}
        cause['fallback/hop>=2' if max(hops) >= 2 else 'hop1'] += 1
print('  (A) OLD→TRANS changed seeds by cause:', dict(cause))
json.dump({p: d for p, d in per.items() if d['old'] != d['new']}, open(OUT / 'backend_single_seed_changed.json', 'w'))

# (B) 500 questions, proxy seeds = pericope ids among the no-graph top-5 (bench/questions_table.json)
QT = json.load(open(KGFIX_SP + '/bench/questions_table.json'))
rq = collections.Counter(); byroute = collections.defaultdict(collections.Counter); qlist = collections.defaultdict(list)
for q in QT:
    route = q['route_nograph']
    if route not in ('R3', 'R4', 'R5', 'R6'):
        continue
    seeds = [x.split('|')[0] for x in q['nograph_top5']]
    seeds = [s for s in seeds if s in peri][:5]
    rq['routes R3-R6'] += 1
    if not seeds: rq['no pericope seed'] += 1; continue
    o, _, _ = gO.multi_hop(seeds); t, _, _ = gT.multi_hop(seeds); n, _, _ = gN.multi_hop(seeds)
    for tag, a, b in (('OLD→TRANS', o, t), ('OLD→NEW', o, n)):
        c = cmp(a, b)
        if c['any']:
            rq[tag + ' any'] += 1; byroute[tag][route] += 1; qlist[tag].append(q['qid'])
        if c['set']: rq[tag + ' id-set'] += 1
        if c['weight']: rq[tag + ' weight-only'] += 1
print('(B)', dict(rq)); print('(B) by route', {k: dict(v) for k, v in byroute.items()})
json.dump(qlist, open(OUT / 'backend_questions_changed.json', 'w'))

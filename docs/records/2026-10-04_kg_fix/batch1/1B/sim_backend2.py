"""Tie-aware version of sim_backend.py. Neo4j ORDER BY gives no order inside a tie group, so for each state we
compute, per seed set, CERTAIN (key strictly inside the top-`limit`) and POSSIBLE (certain + the tie group at the cut)
members. A membership change is counted only when it is certain under both states; weights are per target.
(A) every Pericope as a single seed; (B) 500 questions with proxy seeds; (C) kg_xref 68 gold reach."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, collections
from common import *
from xrefgraph import graphs, HOP, TSKH
gO, gT, gN = graphs()
vmap, peri = load_pericopes()
P = sorted(peri)
LIMIT = 10

def state(g, seeds):
    rows, tie, keys = g.one_hop(seeds, LIMIT)
    order = sorted(keys, key=lambda t: keys[t])
    if len(order) <= LIMIT:
        certain = set(order); possible = set(order)
    else:
        bkey = keys[order[LIMIT - 1]]
        certain = {t for t in order if keys[t] < bkey}
        possible = certain | {t for t in order if keys[t] == bkey}
        if len(possible) == LIMIT:
            certain = set(possible)
    w = {}
    for t in possible:
        k = keys[t]
        cur = (-k[1] >= 999) if g.mode == 'OLD' else bool(-k[1])
        w[t] = (HOP if cur else TSKH)[1]
    fb = len(order) < LIMIT
    if fb:  # sparse fallback rows (hop>=2), from multi_hop; weights per state
        rows, _, _ = g.multi_hop(seeds, 2, LIMIT)
        for t, h, wt in rows:
            if h >= 2:
                certain.add(t); possible.add(t); w[t] = wt
    return dict(certain=certain, possible=possible, w=w, fallback=fb, tie=len(possible) > len(certain) and len(order) > LIMIT,
                tie_size=len(possible) - len(certain))

def diff(a, b):
    out_certain = bool(a['certain'] - b['possible']) or bool(b['certain'] - a['possible'])
    common = a['possible'] & b['possible']
    wchg = sorted(t for t in common if a['w'][t] != b['w'][t])
    return dict(member=out_certain, weight=bool(wchg), wchg=wchg, any=out_certain or bool(wchg))

# (A)
A = collections.Counter(); changed = {}
tie_sizes = []
for p in P:
    o, t, n = state(gO, [p]), state(gT, [p]), state(gN, [p])
    A['OLD tie at cut'] += o['tie']; A['NEW tie at cut'] += n['tie']
    if o['tie']: tie_sizes.append(o['tie_size'])
    A['fallback'] += o['fallback']
    for tag, a, b in (('OLD→TRANS', o, t), ('OLD→NEW', o, n)):
        d = diff(a, b)
        for k in ('member', 'weight', 'any'): A[f'{tag} {k}'] += d[k]
        if d['any'] and tag == 'OLD→NEW': changed[p] = d
print('(A) single-seed, pericopes', len(P)); [print('   ', k, v) for k, v in sorted(A.items())]
tie_sizes.sort(); print('    OLD tie-group size at the cut: median', tie_sizes[len(tie_sizes)//2], 'max', tie_sizes[-1])
# which seeds change OLD->TRANS
print('    OLD→TRANS seeds:', [p for p in P if diff(state(gO,[p]), state(gT,[p]))['any']])

# (B) questions
QT = json.load(open(KGFIX_SP + '/bench/questions_table.json'))
B = collections.Counter(); br = collections.defaultdict(collections.Counter); ql = collections.defaultdict(list)
for q in QT:
    route = q['route_nograph']
    if route not in ('R3', 'R4', 'R5', 'R6'): continue
    B['R3-R6'] += 1
    seeds = [x.split('|')[0] for x in q['nograph_top5']]; seeds = [s for s in seeds if s in peri][:5]
    if not seeds: B['no pericope seed'] += 1; continue
    o, t, n = state(gO, seeds), state(gT, seeds), state(gN, seeds)
    B['OLD tie at cut'] += o['tie']
    for tag, a, b in (('OLD→TRANS', o, t), ('OLD→NEW', o, n)):
        d = diff(a, b)
        for k in ('member', 'weight', 'any'): B[f'{tag} {k}'] += d[k]
        if d['any']: br[tag][route] += 1; ql[tag].append(q['qid'])
print('(B) questions (proxy seeds = no-graph top-5 pericopes):'); [print('   ', k, v) for k, v in sorted(B.items())]
print('    by route', {k: dict(v) for k, v in br.items()})
json.dump(ql, open(OUT / 'backend_questions_changed.json', 'w'), indent=1)

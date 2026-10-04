"""How many seed sets would change at deploy step 1 if the transitional image also adds a target.id tiebreak?
Compares the actual prod/staging outputs (tie_probe.json, HEAD Cypher) with the simulator's id-tiebreak OLD ranking,
and validates the simulator: every prod output must be a valid tie-resolution of the simulated key order."""
import json, collections
from common import *
from xrefgraph import graphs
gO, gT, gN = graphs()
tp = json.load(open(OUT / 'tie_probe.json'))
QT = json.load(open('/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/bench/questions_table.json'))
vmap, peri = load_pericopes()
sets = {}
for q in QT:
    if q['route_nograph'] in ('R3', 'R4', 'R5', 'R6'):
        s = [x.split('|')[0] for x in q['nograph_top5']]; s = [x for x in s if x in peri][:5]
        if s: sets[q['qid']] = s
C = collections.Counter()
for kind, items in (('question', sets.items()), ('single', ((p, [p]) for p in sorted(peri)))):
    for k, seeds in items:
        key = k if kind == 'question' else 'single:' + k
        rows, tie, keys = gO.one_hop(seeds, 10)
        sim = [r[0] for r in rows]
        for store in ('prod', 'staging'):
            real = tp[store][key]
            # validity: real must have the same multiset of keys as sim (same tie groups, any order inside)
            ok = sorted(keys[t] for t in real) == sorted(keys[t] for t in sim) and all(t in keys for t in real)
            C[f'{kind} {store} consistent with simulator'] += ok
            C[f'{kind} {store} id-set differs from id-tiebreak'] += set(real) != set(sim)
        C[f'{kind} total'] += 1
for k, v in sorted(C.items()): print(k, v)

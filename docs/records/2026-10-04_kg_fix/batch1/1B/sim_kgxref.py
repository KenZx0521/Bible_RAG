"""kg_xref 68 (2026-10-03 audit set, scratchpad kg_xref/): can xref expansion bring the missing gold group?
C1: worst-case rank of the missing gold group from S0-retrieved gold seeds (single seed, as q_xref_rank.cypher), OLD vs NEW.
C2: seeds = S0 top-5 pericopes (R5-style deduped[:5]); missing gold in the top-10 xref candidates (certain / possible)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
import json, collections
from common import *
from xrefgraph import graphs
gO, gT, gN = graphs()
vmap, peri = load_pericopes()
KX = KGFIX_SP + '/kg_xref/'
qp = json.load(open(KX + 'qparams.json'))
sel = {x['qid'][-3:]: x for x in json.load(open(KX + 'sel.json'))}
def worst_rank(g, seed, target):
    _, _, keys = g.one_hop([seed], 10**6)
    if target not in keys: return None
    return sum(1 for t, k in keys.items() if k <= keys[target])   # neighbours scoring >= target (worst case)
def best_rank(g, seed, target):
    _, _, keys = g.one_hop([seed], 10**6)
    if target not in keys: return None
    return 1 + sum(1 for t, k in keys.items() if k < keys[target])
C = collections.Counter(); rows = []
for q, d in sorted(qp.items()):
    groups = collections.defaultdict(list)
    for x in d['g']:
        b, p = x.split('|'); groups[b].append(p)
    s0 = [p for p in d['s0'] if p in peri]
    have = {b for b, ps in groups.items() if any(p in s0 for p in ps)}
    missing = [b for b in groups if b not in have]
    if not have or not missing:
        continue
    seeds = [p for b in have for p in groups[b] if p in s0]
    rec = dict(q=q, family=sel[q]['family'], route=sel[q]['route_nograph'], missing=missing)
    for tag, g in (('OLD', gO), ('NEW', gN)):
        wr = min((r for s in seeds for b in missing for t in groups[b] for r in [worst_rank(g, s, t)] if r), default=None)
        br = min((r for s in seeds for b in missing for t in groups[b] for r in [best_rank(g, s, t)] if r), default=None)
        rec[tag + '_worst'] = wr; rec[tag + '_best'] = br
        # C2: all S0 top-5 as seeds
        rows_, tie, keys = g.one_hop(s0, 10)
        order = sorted(keys, key=lambda t: keys[t])
        if len(order) > 10:
            bk = keys[order[9]]; cert = {t for t in order if keys[t] < bk}; poss = cert | {t for t in order if keys[t] == bk}
            if len(poss) == 10: cert = set(poss)
        else:
            cert = poss = set(order)
        gold_missing = {t for b in missing for t in groups[b]}
        rec[tag + '_c2'] = 'certain' if gold_missing & cert else ('possible' if gold_missing & poss else 'no')
    rows.append(rec)
print('questions with S0 partial gold:', len(rows))
for tag in ('OLD', 'NEW'):
    print(tag, 'C1 worst-rank<=5:', sum(1 for r in rows if r[tag + '_worst'] and r[tag + '_worst'] <= 5),
          ' worst<=10:', sum(1 for r in rows if r[tag + '_worst'] and r[tag + '_worst'] <= 10),
          ' best<=10:', sum(1 for r in rows if r[tag + '_best'] and r[tag + '_best'] <= 10),
          '| C2 (S0 top-5 seeds, top-10 cands):', collections.Counter(r[tag + '_c2'] for r in rows))
for r in rows:
    if (r['OLD_worst'], r['OLD_c2']) != (r['NEW_worst'], r['NEW_c2']):
        print('  changed', r)
json.dump(rows, open(OUT / 'kgxref_reach.json', 'w'), indent=1, ensure_ascii=False)

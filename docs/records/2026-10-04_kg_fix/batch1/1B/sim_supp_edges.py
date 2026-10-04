"""Edge-level view of the 142 live supplementary edges + verse-level TSK support of the 161 definitions."""
import json, collections
from common import *
import import_tsk_crossrefs as T
rows = json.load(open(OUT / 'supp_sim.json'))
live = load_live('prod')
tsk = load_tsk()
vmap, peri = load_pericopes()
live_supp = {(r[0], r[1]): r for r in live if r[2] == 'supplementary'}
by_old = collections.defaultdict(list)
for r in rows:
    if r['old_pair']: by_old[tuple(r['old_pair'])].append(r)
cls_edge = collections.Counter(); detail = collections.defaultdict(list)
for pair in live_supp:
    defs = by_old[pair]
    kinds = sorted({d['cls'] for d in defs})
    k = '+'.join(kinds)
    cls_edge[k] += 1; detail[k].append((pair, [d['desc'] for d in defs]))
print('142 live supplementary edges by fate of the definition(s) that produced them:', dict(cls_edge))
for k in detail:
    if k not in ('unchanged', 'fix_src'): print(' ', k, detail[k])
# R4 (validate_kg) on live: first source verse in source pericope, first target verse in target pericope
mis = 0
for (s, t), r in live_supp.items():
    sv, tv = r[7], r[8]
    ok_s = nums(sv)[0] in peri[s]['vs']; ok_t = nums(tv)[0] in peri[t]['vs']
    mis += not (ok_s and ok_t)
print('R4 on live (first verse rule):', mis)
# pure-fake vs real-but-misplaced: the wrong (old) pair has any TSK support either direction?
fix = [r for r in rows if r['cls'] in ('fix_src',)]
wrong_has_tsk = sum(1 for r in fix if tuple(r['old_pair']) in tsk or tuple(r['old_pair'][::-1]) in tsk)
print('fix_src defs:', len(fix), ' old (wrong) pair has TSK support either dir:', wrong_has_tsk, ' pure fake:', len(fix) - wrong_has_tsk)
# verse-level TSK support: a TSK row whose from-verse is one of the source verses and to-range touches one of the target verses (or reverse)
tskv = collections.defaultdict(int)
with open(ROOT / 'output/cross_references_tsk.txt', encoding='utf-8') as f:
    next(f)
    for line in f:
        c = line.rstrip('\n').split('\t')
        if len(c) < 3: continue
        try: v = int(c[2])
        except ValueError: continue
        if v < 0: continue
        fr = T.parse_ref(c[0])
        if not fr: continue
        if '-' in c[1]:
            lo, hi = c[1].split('-', 1); lo, hi = T.parse_ref(lo), T.parse_ref(hi)
            if not lo or not hi: continue
            tos = [(lo[0], lo[1], n) for n in range(lo[2], hi[2] + 1)] if lo[:2] == hi[:2] else [lo, hi]
        else:
            t1 = T.parse_ref(c[1]); tos = [t1] if t1 else []
        for to in tos:
            tskv[(fr, to)] = max(tskv[(fr, to)], v)
def vsupport(r):
    sb, sc = r['src_id'].split(':')[:2]; tb, tc = r['tgt_id'].split(':')[:2]
    S_ = [(sb, int(sc), v) for v in nums(r['sv'])]; T_ = [(tb, int(tc), v) for v in nums(r['tv'])]
    best = None; same_dir = False
    for a in S_:
        for b in T_:
            for k, sd in (((a, b), True), ((b, a), False)):
                if k in tskv:
                    best = max(best or 0, tskv[k]); same_dir |= sd
    return best, same_dir
vs = [(r, *vsupport(r)) for r in rows]
keep = [x for x in vs if x[0]['action'] == 'keep']
print('verse-level TSK support (either dir): kept', sum(x[1] is not None for x in keep), '/', len(keep),
      '; all 161:', sum(x[1] is not None for x in vs))
print('  same-direction NT->OT verse-level:', sum(x[2] for x in keep), '/', len(keep))
print('  kept defs WITHOUT verse-level support:', [(x[0]['i'], x[0]['src_id'], x[0]['sv'], x[0]['tgt_id'], x[0]['tv'], x[0]['desc'], 'peri-level votes', x[0]['tsk_votes']) for x in keep if x[1] is None])
print('  XREF-2 rows:', [(x[0]['src_id'], x[0]['sv'], x[0]['tgt_id'], x[0]['tv'], x[0]['desc'], 'verse', x[1], 'peri', x[0]['tsk_votes']) for x in vs if x[0]['action'] != 'keep'])
json.dump([dict(i=x[0]['i'], verse_votes=x[1], same_dir=x[2]) for x in vs], open(OUT / 'supp_verse_support.json', 'w'))

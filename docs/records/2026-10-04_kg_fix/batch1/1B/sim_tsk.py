"""1B offline simulation: TSK evidence swallowed by curated edges (XREF-4), before/after supplementary re-anchoring.
Builds the projected post-1B CROSS_REFERENCES edge table (xref_new.json) used by sim_backend.py."""
import json, collections
from common import *
tsk = load_tsk()
live = load_live('prod')
E = json.load(open(OUT / 'supp_edges.json'))
new_supp = {tuple(p) for p in E['new_supp_pairs']}
live_md = {(r[0], r[1]) for r in live if r[2] == 'markdown'}
live_supp = {(r[0], r[1]) for r in live if r[2] == 'supplementary'}
live_tsk = {(r[0], r[1]): r[3] for r in live if r[2] == 'tsk'}
old_cur = live_md | live_supp
print('live: md', len(live_md), 'supp', len(live_supp), 'curated pairs', len(old_cur), 'tsk edges', len(live_tsk), 'TSK pairs', len(tsk))
sw_old = old_cur & set(tsk)
print('TSK pairs swallowed by curated edges today (same direction):', len(sw_old),
      ' by md', len(live_md & set(tsk)), ' by supp', len(live_supp & set(tsk)))
assert len(live_tsk) == len(tsk) - len(sw_old)
assert all(live_tsk[k] == tsk[k]['votes'] for k in live_tsk)
v = sorted(tsk[k]['votes'] for k in sw_old)
print('  swallowed votes: min', v[0], 'median', v[len(v)//2], 'max', v[-1], ' votes>=50:', sum(x >= 50 for x in v), ' verse_pairs total', sum(tsk[k]['verse_pairs'] for k in sw_old))
print('votes>=999 TSK edges:', [(k, tsk[k]['votes']) for k in tsk if tsk[k]['votes'] >= 999])
new_cur = live_md | new_supp
sw_new = new_cur & set(tsk)
print('after 1B: curated pairs', len(new_cur), '(md', len(live_md), '+ supp', len(new_supp), ', overlap', len(live_md & new_supp), ')')
print('  curated edges carrying TSK votes (tsk=true):', len(sw_new), ' by md', len(live_md & set(tsk)), ' by supp', len(new_supp & set(tsk)))
print('  curated edges w/o TSK evidence:', len(new_cur - set(tsk)), ' (md', len(live_md - set(tsk)), ', supp', len(new_supp - set(tsk)), ')')
total_new = len(set(tsk) | new_cur)
print('  total CROSS_REFERENCES after 1B:', total_new, ' (live 250,418; delta', total_new - 250418, ')')
print('  edges with votes (R11):', len(tsk))
print('  pure TSK edges (curated=false):', len(set(tsk) - new_cur), ' (live tsk edges', len(live_tsk), ')')
# transitions per directed pair between live and post-1B
def state_old(k):
    if k in live_md: return 'md'
    if k in live_supp: return 'supp'
    if k in live_tsk: return 'tsk'
    return None
def state_new(k):
    c = k in new_cur; t = k in tsk
    if c and t: return 'cur+tsk'
    if c: return 'cur'
    if t: return 'tsk'
    return None
trans = collections.Counter()
for k in set(tsk) | old_cur | new_cur:
    trans[(state_old(k), state_new(k))] += 1
for k, n in sorted(trans.items(), key=lambda x: -x[1]): print('  ', k, n)
# projected post-1B edge table: [s, t, curated, votes, tsk, sources]
rows = []
for k in sorted(set(tsk) | new_cur):
    srcs = (['markdown'] if k in live_md else []) + (['supplementary'] if k in new_supp else [])
    rows.append([k[0], k[1], bool(srcs), tsk[k]['votes'] if k in tsk else None, k in tsk, srcs])
json.dump(rows, open(OUT / 'xref_new.json', 'w'))

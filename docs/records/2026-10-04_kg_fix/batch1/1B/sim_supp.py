"""1B offline simulation: re-anchor the 161 supplementary definitions by verse coordinates.

Old behaviour = process_bible._supplement_cross_references (HEAD a32fbea) + import_neo4j MERGE/SET += (last wins).
New behaviour = verse-coordinate resolution on BOTH ends (book:chapter from the old ids + *_verses),
every verse must land in a pericope; XREF-2 per plan (D10 pending).
Outputs supp_sim.json (per-definition rows) and prints the summary tables used in the plan."""
import json, collections
from common import *
from types import SimpleNamespace; from pathlib import Path  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
S = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]

vmap, peri = load_pericopes()
tsk = load_tsk()
live = load_live('prod')
live_supp = {(r[0], r[1]) for r in live if r[2] == 'supplementary'}
live_md = {(r[0], r[1]) for r in live if r[2] == 'markdown'}
jsonl_rows = [json.loads(l) for l in open(ROOT / 'output/neo4j_relationships.jsonl', encoding='utf-8')]
md_rows = [r for r in jsonl_rows if r['type'] == 'CROSS_REFERENCES' and r['properties']['source'] == 'markdown']
assert {(r['start'], r['end']) for r in md_rows} == live_md and len(md_rows) == len(live_md) == 774

# --- old behaviour, re-implemented 1:1 from process_bible.py:185-242 -------------
def old_pair(ref):
    tb, tc = ref.target_pericope_id.split(':')[:2]
    first_v = ref.target_verses.split(',')[0].split('-')[0].strip()
    tgt = vmap.get((tb, int(tc), int(first_v))) or ref.target_pericope_id
    if ref.source_pericope_id not in peri:
        return None                                   # silently dropped (:222-223)
    return (ref.source_pericope_id, tgt)

# --- new behaviour --------------------------------------------------------------
XREF2_DELETE = {('rev:20:0', 'isa:65:0', '4', '17'), ('rev:19:1', 'psa:118:0', '1', '1')}
XREF2_RETARGET = {('rev:19:2', 'dan:7:0', '11-16', '13-14')}   # D10: dan:2:47 / deu:10:17 / downgrade

def span(book, ch, spec):
    vs = nums(spec)
    hits = [(v, vmap.get((book, ch, v))) for v in vs]
    missing = [v for v, p in hits if p is None]
    pids = list(dict.fromkeys(p for _, p in hits if p))
    return pids, missing, {p: [v for v, q in hits if q == p] for p in pids}

def tsk_support(src_pids, tgt_pids):
    best = None
    for a in src_pids:
        for b in tgt_pids:
            for k in ((a, b), (b, a)):
                if k in tsk:
                    best = max(best or 0, tsk[k]['votes'])
    return best

rows = []
for i, ref in enumerate(S):
    key = (ref.source_pericope_id, ref.target_pericope_id, ref.source_verses, ref.target_verses)
    sb, sc = ref.source_pericope_id.split(':')[:2]; tb, tc = ref.target_pericope_id.split(':')[:2]
    sp, smiss, sparts = span(sb, int(sc), ref.source_verses)
    tp, tmiss, tparts = span(tb, int(tc), ref.target_verses)
    op = old_pair(ref)
    action = 'delete_xref2' if key in XREF2_DELETE else ('retarget_xref2' if key in XREF2_RETARGET else 'keep')
    new_pairs = [(a, b) for a in sp for b in tp] if action == 'keep' else []
    rows.append(dict(i=i, src_id=ref.source_pericope_id, tgt_id=ref.target_pericope_id, sv=ref.source_verses,
                     tv=ref.target_verses, desc=ref.description, ref_type=ref.ref_type, old_pair=op,
                     src_pids=sp, tgt_pids=tp, src_missing=smiss, tgt_missing=tmiss, src_parts=sparts,
                     tgt_parts=tparts, action=action, new_pairs=new_pairs,
                     tsk_votes=tsk_support(sp, tp), old_src_ok=(ref.source_pericope_id in sp),
                     old_tgt_ok=(op is not None and op[1] in tp)))

C = collections.Counter
print('definitions', len(S))
print('missing verses (must be 0):', sum(bool(r['src_missing'] or r['tgt_missing']) for r in rows))
print('fan-out source >1 pericope:', [(r['src_id'], r['sv'], r['src_pids']) for r in rows if len(r['src_pids']) > 1])
print('fan-out target >1 pericope:', [(r['tgt_id'], r['tv'], r['tgt_pids'], r['desc']) for r in rows if len(r['tgt_pids']) > 1])

# per-definition classification (relative to what the old code emitted)
def cls(r):
    if r['action'] != 'keep':
        return r['action']
    if r['old_pair'] is None:
        return 'previously_dropped'
    old = r['old_pair']
    if old in r['new_pairs'] and len(r['new_pairs']) == 1:
        return 'unchanged'
    if old in r['new_pairs']:
        return 'unchanged+fanout'
    s = old[0] in r['src_pids']; t = old[1] in r['tgt_pids']
    return {(False, True): 'fix_src', (True, False): 'fix_tgt', (False, False): 'fix_both'}[(s, t)]
for r in rows: r['cls'] = cls(r)
print('per-definition:', C(r['cls'] for r in rows))

# old JSONL rows -> live edges (last row wins on SET +=): which defs got swallowed
old_emitted = [r for r in rows if r['old_pair'] is not None]
dup = C(r['old_pair'] for r in old_emitted)
print('old emitted rows', len(old_emitted), 'unique old pairs', len(dup), 'rows swallowed', len(old_emitted) - len(dup))
assert set(dup) == live_supp, (len(set(dup)), len(live_supp))

# new curated pair set (aggregated); md + supp
new_supp = collections.defaultdict(list)
for r in rows:
    for p in r['new_pairs']:
        new_supp[p].append(r['i'])
new_supp_pairs = set(new_supp)
print('new supplementary unique pairs', len(new_supp_pairs), ' rows mapping to a pair shared with another def:',
      sum(len(v) for v in new_supp.values() if len(v) > 1), ' pairs w/ >1 def:', sum(len(v) > 1 for v in new_supp.values()))
print('new supp pairs that coincide with a markdown pair (aggregated into one curated edge):',
      len(new_supp_pairs & live_md), sorted(new_supp_pairs & live_md))
print('old supp pairs that coincided with markdown:', len(live_supp & live_md))
# edge-level diff for supplementary edges
kept = live_supp & new_supp_pairs
removed = live_supp - new_supp_pairs
added = new_supp_pairs - live_supp
print(f'edge level: live supp edges {len(live_supp)} -> kept {len(kept)}, removed {len(removed)}, added {len(added)}, new total {len(new_supp_pairs)}')
removed_still_curated = removed & live_md
print('removed supp pairs still present as markdown edge:', len(removed_still_curated))
# what happens to removed pairs: do they have TSK evidence (they become pure TSK edges) or disappear?
rm_tsk = [p for p in removed if p in tsk]
print('removed supp pairs: become pure TSK edge', len(rm_tsk), '| vanish entirely', len(removed) - len(rm_tsk) - len(removed_still_curated))
# R4-style misalignment on old live edges (first verse) and all-verse
def misaligned(pairs_rows):
    n = 0
    for r in pairs_rows:
        pass
# TSK support of the new definitions
keep_rows = [r for r in rows if r['action'] == 'keep']
sup = [r for r in keep_rows if r['tsk_votes'] is not None]
print(f'TSK support (pericope pair, either direction): {len(sup)}/{len(keep_rows)} kept defs; unsupported:',
      [(r['src_pids'], r['tgt_pids'], r['desc']) for r in keep_rows if r['tsk_votes'] is None])
print('all 161 incl. XREF-2 rows, support:', sum(r['tsk_votes'] is not None for r in rows), '/', len(rows),
      [(r['i'], r['src_id'], r['sv'], r['tgt_id'], r['tv'], r['desc']) for r in rows if r['tsk_votes'] is None])
json.dump(rows, open(OUT / 'supp_sim.json', 'w'), ensure_ascii=False, indent=1, default=list)
json.dump({'kept': sorted(kept), 'removed': sorted(removed), 'added': sorted(added),
           'new_supp_pairs': sorted(new_supp_pairs)}, open(OUT / 'supp_edges.json', 'w'), ensure_ascii=False, indent=1)

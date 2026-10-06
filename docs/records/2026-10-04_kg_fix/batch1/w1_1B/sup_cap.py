"""Verse-level TSK support of the final 162 anchors with expand_to_range's 60-verse cap applied at verse level."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, sys
sys.path.insert(0, BIBLE_RAG_ROOT + '/scripts')
import import_tsk_crossrefs as T
idx = {}
with open(BIBLE_RAG_ROOT + '/output/cross_references_tsk.txt', encoding='utf-8') as f:
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
            tos = [(lo[0], lo[1], n) for n in range(lo[2], min(hi[2], lo[2] + T.MAX_RANGE_VERSES) + 1)] if lo[:2] == hi[:2] else [lo, hi]
        else:
            t = T.parse_ref(c[1]); tos = [t] if t else []
        for t in tos: idx[(fr, t)] = max(idx.get((fr, t), -1), v)
def vs(spec):
    o = []
    for part in spec.split(','):
        a, _, b = part.partition('-'); o += range(int(a), int(b or a) + 1)
    return o
def side(s):
    b, r = s.split(' '); c, v = r.split(':'); return [(b, int(c), x) for x in vs(v)]
fwd = rev = none = 0
for anchor, s, t in json.load(open('golden_final.json')):
    a, b = anchor.split('>'); A, B = side(a), side(b)
    f = any((x, y) in idx for x in A for y in B); r = any((y, x) in idx for x in A for y in B)
    fwd += f; rev += (not f and r); none += not (f or r)
print('anchors', fwd + rev + none, 'fwd', fwd, 'rev-only', rev, 'none', none)

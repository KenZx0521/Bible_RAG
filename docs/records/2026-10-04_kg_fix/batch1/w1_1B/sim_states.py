"""Intermediate commit states of the 1B Step 0 change: S3 (coordinates, no X2), C5a (2 deletions), C5b (X2(a)).
Counts of supplementary anchors / distinct pairs / JSONL CROSS_REFERENCES rows (S3: one row per anchor; from S4 on: aggregated)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
W1_1B_EVIDENCE = os.environ.get("W1_1B_EVIDENCE", BIBLE_RAG_ROOT + "/bak/20261005_w1_1b_evidence")
import collections, hashlib, json, sys
from pathlib import Path
ROOT = Path(BIBLE_RAG_ROOT); sys.path.insert(0, str(ROOT))
from types import SimpleNamespace  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
DEFS = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]
vmap = {}; pids = set()
for l in open(ROOT / 'output/pericopes.jsonl', encoding='utf-8'):
    p = json.loads(l); m = p['metadata']; pids.add(p['id'])
    for v in p['verses']:
        n = v['num']; a, b = n.split('-') if '-' in n else (n, n)
        for x in range(int(a), int(b) + 1): vmap[(m['book_id'], m['chapter_num'], x)] = p['id']
def vs(spec):
    o = []
    for part in spec.split(','):
        a, _, b = part.strip().partition('-'); o += range(int(a), int(b or a) + 1)
    return o
coords = []
for d in DEFS:
    sb, sc, _ = d.source_pericope_id.split(':'); tb, tc, _ = d.target_pericope_id.split(':')
    coords.append((f'{sb} {sc}:{d.source_verses}', f'{tb} {tc}:{d.target_verses}', d))
def anchors(defs):
    out = []
    for s, t, d in defs:
        b1, r1 = s.split(' '); c1, v1 = r1.split(':'); b2, r2 = t.split(' '); c2, v2 = r2.split(':')
        sp = list(dict.fromkeys(vmap[(b1, int(c1), v)] for v in vs(v1))); tp = list(dict.fromkeys(vmap[(b2, int(c2), v)] for v in vs(v2)))
        out += [(a, b) for a in sp for b in tp]
    return out
# old pairs (HEAD behaviour) per definition
def old_pair(d):
    tb, tc = d.target_pericope_id.split(':')[:2]; fv = int(d.target_verses.split(',')[0].split('-')[0])
    if d.source_pericope_id not in pids: return None
    return (d.source_pericope_id, vmap.get((tb, int(tc), fv)) or d.target_pericope_id)
cls = collections.Counter()
for s, t, d in coords:
    new = anchors([(s, t, d)]); op = old_pair(d)
    if op is None: cls['recovered (old code dropped)'] += 1
    elif op in new: cls['kept' + (' + fan-out' if len(new) > 1 else '')] += 1
    elif op[0] not in {a for a, _ in new}: cls['source fixed'] += 1
    else: cls['target fixed'] += 1
print('per-definition vs HEAD:', dict(cls))
DEL = {('rev 20:4', 'isa 65:17'), ('rev 19:1', 'psa 118:1')}
s3 = coords
c5a = [c for c in coords if (c[0], c[1]) not in DEL]
c5b = [((('rev 19:16', 'dan 2:47') if (c[0], c[1]) == ('rev 19:11-16', 'dan 7:13-14') else (c[0], c[1])) + (c[2],)) for c in c5a]
REL_PRE1B = W1_1B_EVIDENCE + '/neo4j_relationships_pre1b.jsonl'  # W1 Step 0 overwrites output/neo4j_relationships.jsonl
assert hashlib.sha256(open(REL_PRE1B, 'rb').read()).hexdigest() == '15ed25053c6cd299546ec234b59d281a9f5f48c48c52e1d4a0f16176a77fc166', REL_PRE1B
md = [json.loads(l) for l in open(REL_PRE1B, encoding='utf-8')]
md = {(r['start'], r['end']) for r in md if r['type'] == 'CROSS_REFERENCES' and r['properties']['source'] == 'markdown'}
for name, defs in (('S3 (coordinates)', s3), ('C5a (2 deletions)', c5a), ('C5b (X2 a)', c5b)):
    a = anchors(defs); pairs = set(a)
    print(f'{name}: defs {len(defs)} anchors {len(a)} distinct supp pairs {len(pairs)} | JSONL xref rows per-anchor {774 + len(a)} aggregated {len(md | pairs)}',
          '| rev:19:2 targets', sorted(t for s, t in pairs if s == 'rev:19:2'))

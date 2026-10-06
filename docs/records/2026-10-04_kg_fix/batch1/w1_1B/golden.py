"""Golden anchor tables for the 1B Step 0 commits: [anchor, start, end] sorted, one per touched pericope pair."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import hashlib, json, sys
from pathlib import Path
ROOT = Path(BIBLE_RAG_ROOT); sys.path.insert(0, str(ROOT))
from types import SimpleNamespace  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
DEFS = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]
vmap = {}
for l in open(ROOT / 'output/pericopes.jsonl', encoding='utf-8'):
    p = json.loads(l); m = p['metadata']
    for v in p['verses']:
        n = v['num']; a, b = n.split('-') if '-' in n else (n, n)
        for x in range(int(a), int(b) + 1): vmap[(m['book_id'], m['chapter_num'], x)] = p['id']
def vs(spec):
    o = []
    for part in spec.split(','):
        a, _, b = part.strip().partition('-'); o += range(int(a), int(b or a) + 1)
    return o
def fmt(v):
    v = sorted(set(v)); runs = []; s = p = v[0]
    for x in v[1:]:
        if x == p + 1: p = x; continue
        runs.append((s, p)); s = p = x
    runs.append((s, p)); return ','.join(f'{a}' if a == b else f'{a}-{b}' for a, b in runs)
def table(defs):
    rows = []
    for s, t in defs:
        b1, r1 = s.split(' '); c1, v1 = r1.split(':'); b2, r2 = t.split(' '); c2, v2 = r2.split(':')
        sp, tp = {}, {}
        for v in vs(v1): sp.setdefault(vmap[(b1, int(c1), v)], []).append(v)
        for v in vs(v2): tp.setdefault(vmap[(b2, int(c2), v)], []).append(v)
        rows += [[f'{b1} {c1}:{fmt(a)}>{b2} {c2}:{fmt(b)}', x, y] for x, a in sp.items() for y, b in tp.items()]
    return sorted(rows)
coords = [(f"{d.source_pericope_id.split(':')[0]} {d.source_pericope_id.split(':')[1]}:{d.source_verses.replace(' ', '')}",
           f"{d.target_pericope_id.split(':')[0]} {d.target_pericope_id.split(':')[1]}:{d.target_verses.replace(' ', '')}") for d in DEFS]
DEL = {('rev 20:4', 'isa 65:17'), ('rev 19:1', 'psa 118:1')}
final = [(('rev 19:16', 'dan 2:47') if c == ('rev 19:11-16', 'dan 7:13-14') else c) for c in coords if c not in DEL]
for name, defs in (('s3', coords), ('final', final)):
    t = table(defs); blob = json.dumps(t, ensure_ascii=False, separators=(',', ':')).encode()
    Path(f'golden_{name}.json').write_text(json.dumps(t, ensure_ascii=False, indent=0))
    print(name, len(t), 'anchors', len({(r[1], r[2]) for r in t}), 'pairs', 'sha256(compact json)', hashlib.sha256(blob).hexdigest()[:16])
print('defs with spaces in verse specs:', [(d.source_verses, d.target_verses) for d in DEFS if ' ' in d.source_verses + d.target_verses])
print([r for r in table(final) if r[1] in ('rev:18:0', 'rev:11:1', 'mat:4:1', 'rev:19:2', '1pe:2:2', 'heb:3:1', 'mat:4:0') and r[2] in ('jer:51:0','jer:51:5','dan:7:1','dan:7:2','isa:9:0','isa:9:1','dan:2:3','isa:53:0','psa:95:0','deu:6:1')])

"""Build a self-contained regression fixture for anchored_rules from the W1 reference
simulation (ppg lexicon, list-stop 'cont', guard 'any', homonym 2, gei, declared).
common.py is ../planner_1A/common.py; replay: docs/records/2026-10-04_kg_fix/README.md."""
import argparse, json, random, re, sys
from collections import defaultdict
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent / 'planner_1A'))   # common.py
from common import OUT, jl, load_entities, load_mentions, load_pericopes, load_chunk_parent, verses_of
import anchored_w1 as A
ap = argparse.ArgumentParser()
ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'anchored_regression.jsonl')
args = ap.parse_args()
A.STOP_DE = 'cont'
HOMONYM = {'person:bide', 'person:yuehan（shitu）'}
ents, types = load_entities()
ment = load_mentions(apply_dan=True)
cp = load_chunk_parent(); peri = load_pericopes()
PPG = ('Person', 'Place', 'Group')
lex = set()
for eid, e in ents.items():
    if types[eid] in PPG:
        lex.add((e['canonical_name'] or '').strip()); lex.update(a.strip() for a in (e.get('aliases') or []))
lex.update(m['span'] for m in ment if types.get(m['eid']) in PPG)
lex = {n for n in lex if n and len(n) >= 2}
big = A.build_tokenizer(lex)
declared = {eid: {(e['canonical_name'] or '').strip(), *[(a or '').strip() for a in (e.get('aliases') or [])]} for eid, e in ents.items()}
span_map = defaultdict(lambda: defaultdict(set))
for m in ment:
    pid = cp.get(m['sid'], m['sid']) if m['label'] == 'Chunk' else m['sid']
    if m['eid'].startswith('person:') and m['eid'] != 'group:yehehua' and m['span'] and m['span'] in declared.get(m['eid'], ()):
        span_map[pid][m['span']].add(m['eid'])
parents = defaultdict(set)
for r in jl(OUT / 'relations.jsonl'):
    if r['extraction_phase'] not in (3, 4):
        continue
    if r['relation'] in ('FATHER_OF', 'MOTHER_OF'): parents[r['tail_id']].add(r['head_id'])
    elif r['relation'] in ('SON_OF', 'DAUGHTER_OF'): parents[r['head_id']].add(r['tail_id'])

def run_verse(pid, text):
    smap = span_map.get(pid, {})
    def resolve(nm):
        ids = smap.get(nm)
        return next(iter(ids)) if ids and len(ids) == 1 else None
    exp, abst = [], []
    for h, rel, t, pat, _ in A.extract(pid, 0, text, big, resolve, 'gei'):
        pc = (t, h) if rel in ('SON_OF', 'DAUGHTER_OF') else (h, t) if rel == 'FATHER_OF' else None
        if pc:
            p, c = pc
            if p in HOMONYM or c in HOMONYM:
                abst.append([h, rel, t, pat, 'homonym']); continue
            others = parents.get(c, set()) - {p}
            if others:
                abst.append([h, rel, t, pat, 'other_parent:' + ','.join(sorted(others))]); continue
        exp.append([h, rel, t, pat])
    used = {nm for nm in lex if nm in text}
    spans = {s: sorted(ids) for s, ids in smap.items() if s in text}
    kids = {x for row in exp + abst for x in (row[0], row[2])}
    return {'pericope_id': pid, 'text': text, 'lexicon': sorted(used), 'spans': spans,
            'parents': {k: sorted(parents[k]) for k in sorted(kids) if parents.get(k)},
            'homonym_ids': sorted(HOMONYM), 'expected': exp, 'abstained': abst}

named = [('2ch:28:2', 12), ('jer:36:1', 12), ('jer:38:0', 1), ('jer:38:0', 6), ('gen:36:0', 3), ('gen:28:1', 9),
         ('2sa:2:2', 13), ('mrk:6:0', 3), ('jhn:1:3', 42), ('gen:36:0', 14), ('1ch:29:2', 26), ('luk:3:2', 24),
         ('luk:3:2', 30), ('1ch:1:1', 28), ('gen:11:2', 26), ('gen:30:2', 25), ('luk:3:2', 31), ('2sa:2:2', 18)]
rows, seen = [], set()
for pid, v in named:
    vs = dict(verses_of(peri[pid]['content'])) if pid in peri else {}
    if v not in vs:
        print('MISSING named', pid, v); continue
    rows.append({'case': f'named:{pid}:{v}', 'verse': v, **run_verse(pid, vs[v])}); seen.add((pid, v))
pool = []
for pid, p in peri.items():
    for v, text in verses_of(p['content']):
        if (pid, v) in seen: continue
        r = run_verse(pid, text)
        if r['expected']:
            pool.append((pid, v))
pool.sort()
for pid, v in random.Random(20261005).sample(pool, 30):
    text = dict(verses_of(peri[pid]['content']))[v]
    rows.append({'case': f'sample:{pid}:{v}', 'verse': v, **run_verse(pid, text)})
out = args.out
with open(out, 'w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
print('rows', len(rows), 'positive pool', len(pool), 'expected triples', sum(len(r['expected']) for r in rows), 'abstained', sum(len(r['abstained']) for r in rows))
for r in rows[:18]:
    print(r['case'], 'EXP', [(e[0].split(':')[1], e[1], e[2].split(':')[1]) for e in r['expected']], 'ABST', [(a[0].split(':')[1], a[1], a[2].split(':')[1], a[4][:20]) for a in r['abstained']])

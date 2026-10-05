"""W1 stream 1B recompute (offline, read-only on output/): X2 = (a) rev 19:16>dan 2:47, X4 fan-out
(one anchor per touched pericope pair, max 3 per definition), md+supp aggregated per (start,end),
TSK aggregated exactly as import_tsk_crossrefs, SET semantics. Writes expected tables to this dir."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
W1_1B_EVIDENCE = os.environ.get("W1_1B_EVIDENCE", BIBLE_RAG_ROOT + "/bak/20261005_w1_1b_evidence")
import collections, hashlib, json, sys
from pathlib import Path
ROOT = Path(BIBLE_RAG_ROOT); OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from types import SimpleNamespace  # archived evidence script: frozen a32fbea definitions, see docs/records/2026-10-04_kg_fix/README.md
DEFS = [SimpleNamespace(**d) for d in json.load(open(Path(BIBLE_RAG_ROOT)/'docs/records/2026-10-04_kg_fix/xref/supp_defs_a32fbea.json', encoding='utf-8'))]
import import_tsk_crossrefs as T

# --- verse map from pericopes.jsonl (what process_bible's verse_lookup holds) -------
vmap, pvs, pids = {}, {}, set()
for l in open(ROOT / 'output/pericopes.jsonl', encoding='utf-8'):
    p = json.loads(l); m = p['metadata']; pids.add(p['id']); s = set()
    for v in p['verses']:
        n = v['num']; a, b = n.split('-') if '-' in n else (n, n)
        for x in range(int(a), int(b) + 1):
            vmap[(m['book_id'], m['chapter_num'], x)] = p['id']; s.add(x)
    pvs[p['id']] = s
vmap_q = T.build_verse_map(ROOT / 'output/embedding_queue.jsonl')
assert vmap_q == vmap, 'pericopes.jsonl and embedding_queue verse maps differ'

def verses(spec):
    out = []
    for part in spec.split(','):
        a, _, b = part.strip().partition('-'); out += range(int(a), int(b or a) + 1)
    return out

def fmt(vs):
    vs = sorted(set(vs)); runs = []; start = prev = vs[0]
    for v in vs[1:]:
        if v == prev + 1: prev = v; continue
        runs.append((start, prev)); start = prev = v
    runs.append((start, prev))
    return ','.join(f'{a}' if a == b else f'{a}-{b}' for a, b in runs)

# --- 161 defs -> coordinates (mechanical: book:chapter of the old id + *_verses) ----
coords = []
for d in DEFS:
    sb, sc, _ = d.source_pericope_id.split(':'); tb, tc, _ = d.target_pericope_id.split(':')
    coords.append(dict(src=f'{sb} {sc}:{d.source_verses}', tgt=f'{tb} {tc}:{d.target_verses}',
                       ref_type=d.ref_type, desc=d.description))
assert len(coords) == 161
DELETE = {('rev 20:4', 'isa 65:17'), ('rev 19:1', 'psa 118:1')}
RETARGET = {('rev 19:11-16', 'dan 7:13-14'): ('rev 19:16', 'dan 2:47')}
defs = []
for c in coords:
    k = (c['src'], c['tgt'])
    if k in DELETE: continue
    if k in RETARGET: c = {**c, 'src': RETARGET[k][0], 'tgt': RETARGET[k][1]}
    defs.append(c)
print('definitions after X2(a):', len(defs))

def parse(coord):
    book, rest = coord.split(' '); ch, vs = rest.split(':'); return book, int(ch), verses(vs)

def resolve(coord):
    b, c, vs = parse(coord); parts = collections.OrderedDict(); miss = []
    for v in vs:
        p = vmap.get((b, c, v))
        if p is None: miss.append(v)
        else: parts.setdefault(p, []).append(v)
    return b, c, parts, miss

anchors = []  # (start, end, anchor_str, ref_type, desc, def_index)
fan = []
for i, d in enumerate(defs):
    sb, sc, sp, sm = resolve(d['src']); tb, tc, tp, tm = resolve(d['tgt'])
    assert not sm and not tm, (d, sm, tm)
    n = len(sp) * len(tp); assert n <= 3, d
    if n > 1: fan.append((d['src'], d['tgt'], list(sp), list(tp)))
    for s, svs in sp.items():
        for t, tvs in tp.items():
            anchors.append((s, t, f'{sb} {sc}:{fmt(svs)}>{tb} {tc}:{fmt(tvs)}', d['ref_type'], d['desc'], i))
print('anchors', len(anchors), 'fan-out defs', len(fan)); [print('  fan', f) for f in fan]
supp_pairs = collections.defaultdict(list)
for a in anchors: supp_pairs[(a[0], a[1])].append(a)
print('distinct supplementary pairs', len(supp_pairs), 'multi-anchor pairs',
      sorted((k, len(v)) for k, v in supp_pairs.items() if len(v) > 1))

# --- markdown rows (unchanged Step 0 output) + md_anchors and their R4 any-verse check ---
REL_PRE1B = W1_1B_EVIDENCE + '/neo4j_relationships_pre1b.jsonl'  # W1 Step 0 overwrites output/neo4j_relationships.jsonl
assert hashlib.sha256(open(REL_PRE1B, 'rb').read()).hexdigest() == '15ed25053c6cd299546ec234b59d281a9f5f48c48c52e1d4a0f16176a77fc166', REL_PRE1B
rels = [json.loads(l) for l in open(REL_PRE1B, encoding='utf-8')]
md = [r for r in rels if r['type'] == 'CROSS_REFERENCES' and r['properties']['source'] == 'markdown']
md_pairs = collections.defaultdict(list)
for r in md: md_pairs[(r['start'], r['end'])].append(r)
print('markdown rows', len(md), 'distinct pairs', len(md_pairs),
      'non-Pericope endpoints', sum(r['start'] not in pids or r['end'] not in pids for r in md),
      'null verse_start', sum(r['properties']['verse_start'] is None for r in md),
      'null verse_end', sum(r['properties']['verse_end'] is None for r in md))
md_mis_first = md_mis_any = 0; md_mis_samples = []
for r in md:
    p = r['properties']; ve = p['verse_end'] if p['verse_end'] and p['verse_end'] >= p['verse_start'] else p['verse_start']
    vs = list(range(p['verse_start'], ve + 1))
    have = pvs[r['end']]
    md_mis_first += vs[0] not in have
    if not set(vs) <= have:
        md_mis_any += 1
        if len(md_mis_samples) < 5: md_mis_samples.append((r['start'], r['end'], p['ref_text'], p['verse_start'], p['verse_end']))
print('markdown target-verse check: first-verse misaligned', md_mis_first, '| any-verse misaligned', md_mis_any, md_mis_samples)
print('markdown cross-chapter (verse_end<verse_start)', sum(r['properties']['verse_end'] < r['properties']['verse_start'] for r in md))

# --- curated aggregation --------------------------------------------------------------
cur = {}
for k in set(md_pairs) | set(supp_pairs):
    srcs = (['markdown'] if k in md_pairs else []) + (['supplementary'] if k in supp_pairs else [])
    cur[k] = srcs
print('curated rows', len(cur), 'md&supp overlap', len(set(md_pairs) & set(supp_pairs)))

# --- TSK aggregation (import_tsk_crossrefs semantics) + verse-level index ---------------
pairs = collections.defaultdict(lambda: {'votes': 0, 'verse_pairs': 0}); vidx = collections.defaultdict(lambda: -1)
with open(ROOT / 'output/cross_references_tsk.txt', encoding='utf-8') as f:
    next(f)
    for line in f:
        cols = line.rstrip('\n').split('\t')
        if len(cols) < 3: continue
        try: votes = int(cols[2])
        except ValueError: continue
        if votes < 0: continue
        fr = T.parse_ref(cols[0])
        if not fr: continue
        to = cols[1]
        if '-' in to:
            lo, hi = to.split('-', 1); lo, hi = T.parse_ref(lo), T.parse_ref(hi)
            tv = [] if not lo or not hi else ([(lo[0], lo[1], n) for n in range(lo[2], hi[2] + 1)] if lo[:2] == hi[:2] else [lo, hi])
        else:
            s = T.parse_ref(to); tv = [s] if s else []
        for t in tv: vidx[(fr, t)] = max(vidx[(fr, t)], votes)
        fp = vmap.get(fr)
        if not fp: continue
        for tp in T.expand_to_range(cols[1], vmap):
            if tp == fp: continue
            s = pairs[(fp, tp)]; s['votes'] = max(s['votes'], votes); s['verse_pairs'] += 1
pairs = dict(pairs)
print('TSK rows', len(pairs), 'votes>=999', sorted((k, v['votes']) for k, v in pairs.items() if v['votes'] >= 999))

# --- verse-level support per anchor and per definition --------------------------------
def anchor_support(a):
    s, t = a[2].split('>'); sb, sc, svs = parse(s); tb, tc, tvs = parse(t)
    fwd = max(vidx.get(((sb, sc, x), (tb, tc, y)), -1) for x in svs for y in tvs)
    rev = max(vidx.get(((tb, tc, y), (sb, sc, x)), -1) for x in svs for y in tvs)
    return fwd, rev
sup = collections.Counter(('fwd' if f >= 0 else 'rev_only' if r >= 0 else 'none') for f, r in map(anchor_support, anchors))
by_def = collections.defaultdict(list)
for a in anchors: by_def[a[5]].append(anchor_support(a))
dsup = collections.Counter(('fwd' if any(f >= 0 for f, _ in v) else 'rev' if any(r >= 0 for _, r in v) else 'none') for v in by_def.values())
print('anchor verse-level support', dict(sup), '| per definition', dict(dsup), '| defs covered', len(by_def))
print('rev 19:16>dan 2:47 support', [anchor_support(a) for a in anchors if a[2].startswith('rev 19:16')])

# --- projected post-1B edge table (Step 5 rows + Step 9 SET) ------------------------------
edges = {}
for k, srcs in cur.items():
    t = pairs.get(k)
    edges[k] = dict(source=srcs[0], curated=True, curated_sources=srcs, tsk=t is not None,
                    votes=t['votes'] if t else None, verse_pairs=t['verse_pairs'] if t else None)
for k, t in pairs.items():
    if k not in edges:
        edges[k] = dict(source='tsk', curated=False, curated_sources=[], tsk=True, votes=t['votes'], verse_pairs=t['verse_pairs'])
attached = sum(1 for k in cur if k in pairs)
print('total CROSS_REFERENCES', len(edges), 'attached_to_curated', attached, 'curated w/o TSK', len(cur) - attached,
      'pure TSK', len(pairs) - attached, 'votes non-null (R11)', sum(e['votes'] is not None for e in edges.values()))
prov = collections.Counter(f"source={e['source']} curated={e['curated']} tsk={e['tsk']}" for e in edges.values())
print('xref_provenance', dict(prov))
print('xrefs by source', dict(collections.Counter(e['source'] for e in edges.values())))
fp = hashlib.sha256('\n'.join(json.dumps([a, b, e['votes'], e['verse_pairs'], e['curated'], e['tsk']])
                              for (a, b), e in sorted(edges.items())).encode()).hexdigest()
print('fingerprint (a.id,b.id,votes,verse_pairs,curated,tsk) sorted sha256:', fp)
json.dump([[a, b, e['curated'], e['votes'], e['tsk'], e['curated_sources'], e['source']] for (a, b), e in sorted(edges.items())],
          open(W1_1B_EVIDENCE + '/xref_new_w1.json', 'w'))
json.dump(sorted([list(k), [x[2] for x in v]] for k, v in supp_pairs.items()), open(OUT / 'supp_expected_pairs.json', 'w'), ensure_ascii=False, indent=0)
json.dump(coords, open(OUT / 'supp_defs_a32fbea_coords.json', 'w'), ensure_ascii=False, indent=0)

# --- transitions vs live (prod dump of 2026-10-04, still identical) ------------------------
live = json.load(open(KGFIX_SP + '/batch1plan/1B/xref_prod.json'))
old = {(r[0], r[1]): r[2] for r in live}
def st_old(k): return {'markdown': 'md', 'supplementary': 'supp', 'tsk': 'tsk'}.get(old.get(k))
def st_new(k):
    e = edges.get(k)
    if not e: return None
    return 'cur+tsk' if e['curated'] and e['tsk'] else 'cur' if e['curated'] else 'tsk'
tr = collections.Counter((st_old(k), st_new(k)) for k in set(old) | set(edges))
print('transitions', sorted(tr.items(), key=lambda x: -x[1]))
print('delta CROSS_REFERENCES', len(edges) - len(old))

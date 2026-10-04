"""Shared offline loaders for the 1B simulation (read-only: output/*.jsonl, repo code)."""
import json, sys, collections, pickle
from pathlib import Path
ROOT = Path('/home/kenzx0521/Bible_RAG')
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))

def load_pericopes():
    vmap, peri = {}, {}
    for l in open(ROOT / 'output/pericopes.jsonl', encoding='utf-8'):
        p = json.loads(l); m = p['metadata']
        vs = []
        for v in p['verses']:
            n = v['num']; a, b = (n.split('-') + [n])[:2] if '-' in n else (n, n)
            for x in range(int(a), int(b) + 1):
                vmap[(m['book_id'], m['chapter_num'], x)] = p['id']; vs.append(x)
        peri[p['id']] = dict(book=m['book_id'], ch=m['chapter_num'], vr=m['verse_range'], title=p['title'],
                             vs=set(vs), text={v['num']: v['text'] for v in p['verses']})
    return vmap, peri

def nums(spec):
    out = []
    for part in spec.replace('，', ',').split(','):
        part = part.strip()
        if not part: continue
        if '-' in part:
            a, b = part.split('-'); out += list(range(int(a), int(b) + 1))
        else: out.append(int(part))
    return out

def load_tsk(cache=OUT / 'tsk_pairs.pkl'):
    """{(from_pid, to_pid): {'votes': max, 'verse_pairs': n, 'rows': [(from_ref, to_ref, votes)]}} exactly as import_tsk_crossrefs builds it."""
    if cache.exists():
        return pickle.load(open(cache, 'rb'))
    import import_tsk_crossrefs as tsk
    vmap = tsk.build_verse_map(ROOT / 'output/embedding_queue.jsonl')
    pairs = collections.defaultdict(lambda: {'votes': 0, 'verse_pairs': 0, 'rows': []})
    with open(ROOT / 'output/cross_references_tsk.txt', encoding='utf-8') as f:
        next(f)
        for line in f:
            cols = line.rstrip('\n').split('\t')
            if len(cols) < 3: continue
            try: votes = int(cols[2])
            except ValueError: continue
            if votes < 0: continue
            fr = tsk.parse_ref(cols[0])
            if not fr: continue
            fp = vmap.get(fr)
            if not fp: continue
            for tp in tsk.expand_to_range(cols[1], vmap):
                if tp == fp: continue
                s = pairs[(fp, tp)]; s['votes'] = max(s['votes'], votes); s['verse_pairs'] += 1
                s['rows'].append((cols[0], cols[1], votes))
    pairs = {k: dict(v) for k, v in pairs.items()}
    pickle.dump(pairs, open(cache, 'wb'))
    return pairs

def load_live(name='prod'):
    return json.load(open(OUT / f'xref_{name}.json'))

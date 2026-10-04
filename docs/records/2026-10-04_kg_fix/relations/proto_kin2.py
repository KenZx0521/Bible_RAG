"""Prototype: anchored, direction-explicit kinship patterns over longest-match tokenized verses (no LLM)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json, re, random
from collections import Counter, defaultdict
N = json.load(open('entities.json'))
P = [json.loads(l) for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')]
E = json.load(open('edges.json'))
name2 = defaultdict(set)
for e in N:
    nm = (e['n'] or '').strip()
    if len(nm) >= 1: name2[nm].add((e['id'], e['t']))
names_sorted = sorted(name2, key=len, reverse=True)
big = re.compile('|'.join(re.escape(n) for n in names_sorted if len(n) >= 2))
def tokenize(v):
    # longest-leftmost match over ALL entity names (any type) -> list of (start,end,name)
    return [(m.start(), m.end(), m.group()) for m in big.finditer(v)]
def person(nm):
    ids = [i for i, t in name2[nm] if t == 'Person']
    return ids[0] if ids else None
SEP = None
DELIM = set('、，；。：（）「」『』和與及並就是之又生的，也 ')
def bound(v, end):
    return end >= len(v) or v[end] in DELIM
out = []
for p in P:
    for v in p['content'].split('\n'):
        v = re.sub(r'^\*\*\d+\*\*\s*', '', v.strip())
        if not v: continue
        toks = tokenize(v)
        for i, (s, e, nm) in enumerate(toks):
            pid = person(nm)
            if not pid or not bound(v, e) or (s > 0 and v[s-1] not in DELIM and v[s-1] not in '給叫名'): continue
            rest = v[e:]
            # A的(長|次)?(兒子|女兒)(是|有)?B[、B...]  -> B CHILD_OF A
            m = re.match(r'的(?:長|次|三|四)?(兒子|女兒|子)(?:是|有|就是)?', rest)
            if m:
                rel = 'SON_OF' if m.group(1) in ('兒子','子') else 'DAUGHTER_OF'
                j = i + 1; cur = e + m.end()
                while j < len(toks) and (toks[j][0] == cur or (toks[j][0] == cur + 1 and v[cur] in '、和')):
                    if not bound(v, toks[j][1]): break
                    c = person(toks[j][2])
                    if c and c != pid: out.append((c, rel, pid, p['id'], v[:60], toks[j][2], nm))
                    cur = toks[j][1]; j += 1
                    if cur < len(v) and v[cur] in '。；：': break
            # A生(了)?B、C  -> A FATHER_OF B (parent; gender unknown => PARENT_OF)
            m = re.match(r'(?:又)?生(?:了)?', rest)
            if m:
                j = i + 1; cur = e + m.end()
                while j < len(toks) and (toks[j][0] == cur or (toks[j][0] == cur + 1 and v[cur] in '、和')):
                    if not bound(v, toks[j][1]): break
                    c = person(toks[j][2])
                    if c and c != pid: out.append((pid, 'PARENT_OF', c, p['id'], v[:60], nm, toks[j][2]))
                    cur = toks[j][1]; j += 1
uniq = {}
for o in out: uniq.setdefault((o[0], o[1], o[2]), o)
print('anchored triples', len(out), 'unique', len(uniq), Counter(k[1] for k in uniq))
# overlap with existing graph (normalize to parent->child)
def norm(h, r, t):
    if r in ('SON_OF','DAUGHTER_OF'): return (t, h)
    if r in ('FATHER_OF','MOTHER_OF','PARENT_OF'): return (h, t)
    return None
proto = {norm(*k) for k in uniq}
live = defaultdict(set)
for e in E:
    n = norm(e['h'], e['rel'], e['t'])
    if n: live[e['props']['extraction_phase']].add(n)
for ph in sorted(live):
    print('phase', ph, 'live parent-child pairs', len(live[ph]), 'agree with proto', len(live[ph] & proto), 'reversed in proto', len({(b,a) for a,b in live[ph]} & proto))
random.seed(11)
for o in random.sample(list(uniq.values()), 30): print(o)
json.dump([list(o) for o in uniq.values()], open('proto_kin.json','w'), ensure_ascii=False)

"""Port of the C1 backend xref ranking with the 087ab0d md5 tiebreak (X1), offline.
Modes: OLD = HEAD 087ab0d Cypher (coalesce(votes,999), curated := score>=999, fallback weights TSK curve);
       C1  = transitional coalesce(r.curated, r.source IN md/supp), ORDER BY seed_support, curated, votes, md5;
             fallback ORDER BY hop, curated (some shortest path all-curated), md5.
Edge tables: live = prod dump (xref_prod.json, unchanged since 2026-10-04, verified by READ count),
             new  = xref_new_w1.json (sim_w1_1b.py)."""
import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
KGFIX_SP = os.environ.get("KGFIX_SP", BIBLE_RAG_ROOT + "/bak/20261004_kgfix_evidence/scratchpad")
W1_1B_EVIDENCE = os.environ.get("W1_1B_EVIDENCE", BIBLE_RAG_ROOT + "/bak/20261005_w1_1b_evidence")
import collections, hashlib, json
from pathlib import Path
OUT = Path(__file__).parent
HOP = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}; TSKH = {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30}
md5 = lambda s: hashlib.md5(s.encode()).hexdigest()
CUR_SRC = ('markdown', 'supplementary')

class G:
    def __init__(self, edges, mode):
        self.mode = mode; self.adj = collections.defaultdict(list)
        for s, t, cur, votes, src in edges:
            if s == t: continue
            e = (cur, votes, src); self.adj[s].append((t, e)); self.adj[t].append((s, e))
    def is_cur(self, e):
        cur, votes, src = e
        if self.mode == 'OLD': return votes is None or votes >= 999
        return bool(cur) if cur is not None else src in CUR_SRC
    def one_hop(self, seeds, limit=10):
        S = set(seeds); agg = {}
        for s in dict.fromkeys(seeds):
            for t, e in self.adj.get(s, ()):
                if t in S: continue
                a = agg.setdefault(t, {'seeds': set(), 'score': None, 'cur': False, 'votes': 0})
                a['seeds'].add(s)
                if self.mode == 'OLD':
                    sc = 999 if e[1] is None else e[1]; a['score'] = sc if a['score'] is None else max(a['score'], sc)
                else:
                    a['cur'] = a['cur'] or self.is_cur(e); a['votes'] = max(a['votes'], e[1] or 0)
        def key(t):
            a = agg[t]
            k = (-len(a['seeds']), -a['score']) if self.mode == 'OLD' else (-len(a['seeds']), -int(a['cur']), -a['votes'])
            return (k, md5(t))
        order = sorted(agg, key=key)
        rows = []
        for t in order[:limit]:
            cur = agg[t]['score'] >= 999 if self.mode == 'OLD' else agg[t]['cur']
            rows.append((t, 1, cur, (HOP if cur else TSKH)[1]))
        return rows
    def multi_hop(self, seeds, max_hops=2, limit=10):
        rows = self.one_hop(seeds, limit)
        if len(rows) >= limit or max_hops < 2: return rows
        S = set(seeds); excl = S | {r[0] for r in rows}
        dist = {s: 0 for s in S}; allcur = {s: True for s in S}; frontier = list(S)
        hops = max(2, min(max_hops, 4))
        for d in range(1, hops + 1):
            nxt = {}
            for u in frontier:
                for v, e in self.adj.get(u, ()):
                    if v in dist and dist[v] < d: continue
                    nxt[v] = nxt.get(v, False) or (allcur[u] and self.is_cur(e))
            for v, ac in nxt.items():
                if v not in dist: dist[v] = d; allcur[v] = ac
            frontier = [v for v in nxt if dist[v] == d]
        cand = [v for v in dist if dist[v] >= 2 and v not in excl]
        if self.mode == 'OLD':
            cand.sort(key=lambda v: (dist[v], md5(v)))
            return rows + [(v, dist[v], False, TSKH[dist[v]]) for v in cand[:limit - len(rows)]]
        cand.sort(key=lambda v: (dist[v], -int(allcur[v]), md5(v)))
        return rows + [(v, dist[v], allcur[v], (HOP if allcur[v] else TSKH)[dist[v]]) for v in cand[:limit - len(rows)]]
    def legacy(self, pid, limit=10):
        return self.one_hop([pid], limit)

live = json.load(open(KGFIX_SP + '/batch1plan/1B/xref_prod.json'))
old_edges = [(r[0], r[1], r[5], r[3], r[2]) for r in live]
new = json.load(open(W1_1B_EVIDENCE + '/xref_new_w1.json'))
new_edges = [(s, t, cur, votes, src) for s, t, cur, votes, tskf, srcs, src in new]
gOld, gC1, gC1new, gOldnew = G(old_edges, 'OLD'), G(old_edges, 'C1'), G(new_edges, 'C1'), G(new_edges, 'OLD')
peri = sorted({json.loads(l)['id'] for l in open(BIBLE_RAG_ROOT + '/output/pericopes.jsonl')})
pset = set(peri)
QT = json.load(open(BIBLE_RAG_ROOT + '/docs/records/2026-10-04_kg_fix/batch1/inputs/bench/questions_table.json'))
qsets = {}
for q in QT:
    if q['route_nograph'] in ('R3', 'R4', 'R5', 'R6'):
        s = [x.split('|')[0] for x in q['nograph_top5']]; s = [x for x in s if x in pset][:5]
        if s: qsets[q['qid']] = (q['route_nograph'], s)
print('pericopes', len(peri), 'proxy question seed sets', len(qsets))

def cmp(a, b):
    return dict(set=[r[0] for r in a] and set(r[0] for r in a) != set(r[0] for r in b),
                any_wt={(r[0], r[3]) for r in a} != {(r[0], r[3]) for r in b},
                order=[r[0] for r in a] != [r[0] for r in b])
def run(tag, ga, gb):
    C = collections.Counter(); routes = collections.Counter(); qids = []
    for p in peri:
        c = cmp(ga.multi_hop([p]), gb.multi_hop([p]))
        C['single id-set'] += bool(c['set']); C['single id-set|weight'] += c['any_wt']; C['single order'] += c['order']
        C['legacy id-set|weight'] += cmp(ga.legacy(p), gb.legacy(p))['any_wt']
    for qid, (route, s) in qsets.items():
        c = cmp(ga.multi_hop(s), gb.multi_hop(s))
        C['q id-set'] += bool(c['set']); C['q id-set|weight'] += c['any_wt']; C['q order'] += c['order']
        if c['any_wt']: routes[route] += 1; qids.append(qid)
    print(tag, dict(C), 'by route', dict(routes))
    return qids
run('STEP1 deploy (OLD md5 -> C1, live data):', gOld, gC1)
q2 = run('STEP2 data (C1 live -> C1 new):', gC1, gC1new)
run('REVERSED order (OLD md5 on new data vs C1 new):', gOldnew, gC1new)
print('fallback seeds (live, C1):', sum(len(gC1.one_hop([p])) < 10 for p in peri), 'new:', sum(len(gC1new.one_hop([p])) < 10 for p in peri))
for name, g in (('OLD live', gOld), ('C1 live', gC1), ('C1 new', gC1new)):
    print(name, 'heb:1:0 top8', [(r[0], r[2]) for r in g.multi_hop(['heb:1:0'])[:8]])
for p in ('jer:29:0', 'isa:55:0', 'rom:8:1', 'eph:1:1', 'jer:1:1'):
    for name, g in (('OLD', gOld), ('C1', gC1), ('C1new', gC1new)):
        rows = g.multi_hop([p]); hit = [r for r in rows if r[0] in ('isa:55:0', 'jer:29:0', 'eph:1:1', 'jer:1:1', 'rom:8:1')]
        print(' sentinel', p, name, hit)
# predictions for the probe
def predict(g):
    out = {f'single:{p}': [list(r) for r in g.multi_hop([p])] for p in peri}
    out.update({f'q:{qid}': [list(r) for r in g.multi_hop(s)] for qid, (_, s) in qsets.items()})
    out.update({f'legacy:{p}': [list(r) for r in g.legacy(p)] for p in peri})
    return out
for name, g in (('trans', gC1), ('new', gC1new)):
    pred = predict(g); blob = json.dumps(pred, sort_keys=True).encode()
    json.dump(pred, open(W1_1B_EVIDENCE + f'/pred_{name}.json', 'w'))
    print('prediction', name, 'keys', len(pred), 'sha256', hashlib.sha256(blob).hexdigest()[:16])
json.dump(q2, open(OUT / 'step2_questions_changed.json', 'w'))

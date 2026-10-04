"""Re-implementation of backend xref ranking (neo4j_db.get_cross_references_multi_hop + cross_ref_retriever._edge_weight)
for three states:
  OLD   = HEAD backend on live data         : score max(coalesce(votes,999)); curated := score>=999; hop>=2 weight from TSK curve
  TRANS = 1B backend (transitional coalesce) on live data: curated := any(coalesce(r.curated, r.source IN md/supp)); votes max(coalesce(votes,0))
  NEW   = 1B backend on post-1B data         : curated flag from data; votes on curated edges too
Edges are walked undirected, like the Cypher (seed)-[r:CROSS_REFERENCES]-(target)."""
import collections, json
from common import *
HOP = {1: 0.75, 2: 0.55, 3: 0.40, 4: 0.30}
TSKH = {1: 0.60, 2: 0.50, 3: 0.40, 4: 0.30}

class G:
    def __init__(self, edges, mode):
        """edges: iterable of (s, t, curated_flag_or_None, votes_or_None, source_or_None)"""
        self.mode = mode
        self.adj = collections.defaultdict(list)
        for s, t, cur, votes, src in edges:
            if s == t: continue
            e = (cur, votes, src)
            self.adj[s].append((t, e)); self.adj[t].append((s, e))

    def is_cur(self, e):
        cur, votes, src = e
        if self.mode == 'OLD':
            return votes is None or votes >= 999          # coalesce(votes,999) >= 999
        if cur is not None:
            return bool(cur)
        return src in ('markdown', 'supplementary')        # transitional coalesce

    def one_hop(self, seeds, limit=10):
        seeds = list(dict.fromkeys(seeds)); S = set(seeds)
        agg = {}
        for s in seeds:
            for t, e in self.adj.get(s, ()):
                if t in S: continue
                a = agg.setdefault(t, {'seeds': set(), 'score': None, 'cur': False, 'votes': 0})
                a['seeds'].add(s)
                if self.mode == 'OLD':
                    sc = 999 if e[1] is None else e[1]
                    a['score'] = sc if a['score'] is None else max(a['score'], sc)
                else:
                    a['cur'] = a['cur'] or self.is_cur(e)
                    a['votes'] = max(a['votes'], e[1] or 0)
        def key(t):
            a = agg[t]
            if self.mode == 'OLD':
                return (-len(a['seeds']), -a['score'])
            return (-len(a['seeds']), -int(a['cur']), -a['votes'])
        order = sorted(agg, key=lambda t: (key(t), t))     # id tiebreak only for reproducibility of the sim
        rows = []
        for t in order[:limit]:
            a = agg[t]
            cur = (a['score'] >= 999) if self.mode == 'OLD' else a['cur']
            rows.append((t, 1, round((HOP if cur else TSKH)[1], 2)))
        # boundary tie: is the cut at `limit` inside a tie group? (then the real Neo4j result is order-dependent)
        tie = len(order) > limit and key(order[limit - 1]) == key(order[limit])
        return rows, tie, {t: key(t) for t in order}

    def multi_hop(self, seeds, max_hops=2, limit=10):
        rows, tie, keys = self.one_hop(seeds, limit)
        if len(rows) >= limit or max_hops < 2:
            return rows, tie, False
        S = set(seeds); excl = S | {r[0] for r in rows}
        # BFS for shortest path length; track whether some shortest path is all-curated
        dist = {s: 0 for s in S}; allcur = {s: True for s in S}
        frontier = list(S)
        for d in range(1, max_hops + 1):
            nxt = {}
            for u in frontier:
                for v, e in self.adj.get(u, ()):
                    if v in dist and dist[v] < d: continue
                    ac = allcur[u] and self.is_cur(e)
                    nxt[v] = nxt.get(v, False) or ac
            for v, ac in nxt.items():
                if v not in dist:
                    dist[v] = d; allcur[v] = ac
            frontier = [v for v in nxt if dist[v] == d]
        cand = sorted([v for v in dist if dist[v] >= 2 and v not in excl], key=lambda v: (dist[v], v))
        for v in cand[:limit - len(rows)]:
            h = dist[v]
            if self.mode == 'OLD':
                w = TSKH[h]                                  # votes is None on fallback rows -> TSK curve
            else:
                w = (HOP if allcur[v] else TSKH)[h]
            rows.append((v, h, w))
        return rows, tie, True

def graphs():
    live = load_live('prod')
    old_edges = [(r[0], r[1], r[5], r[3], r[2]) for r in live]
    new = json.load(open(OUT / 'xref_new.json'))
    new_edges = [(s, t, cur, votes, 'tsk' if not cur else 'curated') for s, t, cur, votes, tskf, srcs in new]
    return G(old_edges, 'OLD'), G(old_edges, 'TRANS'), G(new_edges, 'NEW')

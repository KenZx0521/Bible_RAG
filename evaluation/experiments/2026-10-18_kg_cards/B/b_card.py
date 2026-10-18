"""The C1 card program (probe_C1/card.py, surface names only) and the B renderings (appendix B).

Card rules (card.py, unchanged): homonym block (a name with >=2 distinct father-like parents may
not relay; such an anchor abstains), tie abstain (shortest paths <=5 hops with >=2 canonical
signatures), BFS + LCA reduction. Changes for B: the triple source is a parameter (MH kin or the
oracle triples) and units are walked in canonical verse order, so the cited verse and the path
picked among equal ties are deterministic (card.py iterated a set).
"""
from __future__ import annotations

import collections
from collections import deque

import b_lib as L

MAXLEN = 5
CARD_MAX_LINES = 6

# ---------------------------------------------------------------- subgraph and walk (card.py)


def subgraph(units, by_unit: dict) -> dict:
    """units: context verses in canonical order; by_unit: {verse: [triple]}."""
    seen = {}
    for u in units:
        for t in by_unit.get(u, []):
            k = (t["head"], t["rel"], t["tail"])
            if k not in seen:
                seen[k] = dict(role=t["role"], units=[u])
            else:
                seen[k]["units"].append(u)
    adj, fathers, edges = collections.defaultdict(list), collections.defaultdict(set), []
    for (h, rel, tl), meta in seen.items():
        u0 = meta["units"][0]
        edges.append((h, rel, tl, meta["role"], u0))
        if rel == "PARENT_OF":
            mother = meta["role"] == "M"
            adj[h].append((tl, "Dm" if mother else "D", u0))
            adj[tl].append((h, "Um" if mother else "U", u0))
            if not mother:
                fathers[tl].add(h)
        elif rel == "SPOUSE_OF":
            adj[h].append((tl, "S", u0)); adj[tl].append((h, "S", u0))
        elif rel == "SIBLING_OF":
            adj[h].append((tl, "B", u0)); adj[tl].append((h, "B", u0))
    blocked = {n for n, fs in fathers.items() if len(fs) >= 2}
    return dict(adj=adj, fathers=fathers, blocked=blocked, edges=edges)


_RED = {("D", "U"): (), ("Dm", "Um"): (), ("D", "Um"): ("S",), ("Dm", "U"): ("S",),
        ("Um", "S"): ("U",), ("U", "S"): ("Um",)}


def canon(sig) -> tuple:
    out = []
    for s in sig:
        out.extend(["U", "D"] if s == "B" else [s])
    changed = True
    while changed:
        changed = False
        for i in range(len(out) - 1):
            k = (out[i], out[i + 1])
            if k in _RED:
                out = out[:i] + list(_RED[k]) + out[i + 2:]
                changed = True
                break
    return tuple(out)


def shortest_paths(G: dict, a: str, b: str, maxlen: int = MAXLEN) -> list:
    adj, blocked = G["adj"], G["blocked"]
    best, out = None, []
    q, dist = deque([(a, [])]), {a: 0}
    while q:
        n, p = q.popleft()
        if (best is not None and len(p) >= best) or len(p) >= maxlen:
            continue
        for m, rel, u in adj[n]:
            if any(x[0] == m for x in p) or m == a:
                continue
            np_ = p + [(m, rel, u)]
            if m == b:
                if best is None or len(np_) <= best:
                    best = len(np_)
                    out.append(np_)
                continue
            if m in blocked or dist.get(m, 99) < len(np_):
                continue
            dist[m] = len(np_)
            q.append((m, np_))
    return [] if best is None else [p for p in out if len(p) == best]


def pair_card(G: dict, a: str, b: str) -> dict:
    adj = G["adj"]
    if a not in adj or b not in adj:
        return dict(status="abstain", reason="anchor_not_in_subgraph")
    if a in G["blocked"] or b in G["blocked"]:
        return dict(status="abstain", reason="anchor_homonym_flag")
    ps = shortest_paths(G, a, b)
    if not ps:
        if shortest_paths(dict(G, blocked=set()), a, b):
            return dict(status="abstain", reason="only_via_blocked_relay")
        return dict(status="abstain", reason="no_path_le5")
    sigs = {canon(tuple(r for _, r, _ in p)) for p in ps}
    if len(sigs) >= 2:
        return dict(status="abstain", reason="tie_signatures", n_sigs=len(sigs))
    return dict(status="fire", sig=list(next(iter(sigs))), path=[[m, r, u] for m, r, u in ps[0]],
                n_paths=len(ps))


def ancestor_card(G: dict, d: str, k: int) -> dict:
    """d's k-th paternal ancestor; path = [[ancestor, 'U', verse], ...]."""
    if d not in G["adj"]:
        return dict(status="abstain", reason="anchor_not_in_subgraph")
    if d in G["blocked"]:
        return dict(status="abstain", reason="anchor_homonym_flag")
    cur, path = d, []
    for step in range(k):
        fs = G["fathers"].get(cur, set())
        if len(fs) != 1:
            return dict(status="abstain", reason="father_not_unique" if fs else "no_father_edge", at=step)
        nxt = next(iter(fs))
        if step < k - 1 and nxt in G["blocked"]:
            return dict(status="abstain", reason="relay_blocked")
        verse = next(u for m, r, u in G["adj"][cur] if m == nxt and r == "U")
        path.append([nxt, "U", verse])
        cur = nxt
    return dict(status="fire", answer=cur, path=path)


# ---------------------------------------------------------------- terms (frozen, appendix B)
# A D hop carries no child gender (MH PARENT_OF), so (D, S) is 兒女的配偶, not 媳婦; other D-final
# terms default to male (兒子, 孫子, 伯父或叔父, 堂兄弟).
SIG_TERM = {
    ("U",): "父親", ("Um",): "母親", ("D",): "兒子", ("Dm",): "兒子", ("S",): "配偶", ("U", "D"): "兄弟",
    ("U", "U"): "祖父", ("U", "U", "U"): "曾祖父", ("U",) * 4: "高祖父", ("U",) * 5: "高祖父的父親",
    ("Um", "U"): "外祖父", ("U", "Um"): "祖母", ("Um", "Um"): "外祖母",
    ("U", "U", "D"): "伯父或叔父", ("U", "U", "D", "D"): "堂兄弟",
    ("Um", "U", "D"): "舅舅", ("Um", "U", "D", "D"): "表兄弟",
    ("S", "U"): "配偶的父親", ("S", "Um"): "配偶的母親", ("D", "S"): "兒女的配偶", ("Dm", "S"): "兒女的配偶",
    ("D", "D"): "孫子", ("D", "D", "D"): "曾孫",
}
HOP_WORD = {"U": "父親", "Um": "母親", "D": "兒子", "Dm": "兒子", "S": "配偶"}
LIN_WORD = {2: "祖父", 3: "曾祖父", 4: "高祖父"}


def sig_term(sig) -> str:
    """Frozen table; otherwise the hop words joined by 的 (父親的父親的兒子 …)."""
    sig = tuple(sig)
    return SIG_TERM.get(sig) or "的".join(HOP_WORD[s] for s in sig)


# ---------------------------------------------------------------- renderings (frozen, appendix B)
def edge_line(t: dict) -> str:
    ref = f"（{L.books()[t['unit_key'].split('.')[0]][1]} {t['ch']}:{t['label']}）"
    h, tl = t["head"], t["tail"]
    if t["rel"] == "PARENT_OF":
        return f"{h}是{tl}的{'母親' if t['role'] == 'M' else '父親'}{ref}"
    if t["rel"] == "SPOUSE_OF":
        return f"{h}與{tl}是夫妻{ref}"
    return f"{h}與{tl}是手足{ref}"


def edge_rows(units, by_unit: dict) -> list[tuple]:
    """All triples of the context verses in verse order, de-duplicated by (head, rel, tail)."""
    seen, out = set(), []
    for u in units:
        for t in by_unit.get(u, []):
            k = (t["head"], t["rel"], t["tail"])
            if k not in seen:
                seen.add(k)
                out.append((k, edge_line(t)))
    return out


def edge_table(units, by_unit: dict) -> str:
    rows = edge_rows(units, by_unit)
    return "\n".join(line for _, line in rows) if rows else "（無）"


def hop_line(prev: str, m: str, rel: str, u: str) -> str:
    ref = f"（{L.verse_ref(u)}）"
    if rel == "B":
        return f"{prev}與{m}是手足{ref}"
    word = {"U": "父親", "Um": "母親", "D": "孩子", "Dm": "孩子", "S": "配偶"}[rel]
    return f"{prev}的{word}是{m}{ref}"


def card_lines(res: dict, a: str, b: str | None, k: int | None) -> list[str]:
    """Fired card -> hop lines (walk order from a) + one conclusion line; <= 6 lines."""
    prev, lines = a, []
    for m, rel, u in res["path"]:
        lines.append(hop_line(prev, m, rel, u))
        prev = m
    if k is not None:
        lines.append(f"結論：{a}的{LIN_WORD[k]}是{res['answer']}")
    else:
        lines.append(f"結論：{b}是{a}的{sig_term(res['sig'])}")
    assert len(lines) <= CARD_MAX_LINES
    return lines

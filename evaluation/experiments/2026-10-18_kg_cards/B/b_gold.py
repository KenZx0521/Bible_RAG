"""TIPNR gold per pericope and the G-oracle triples (probe_C1/probe_eval.py gold_graph,
probe_oracle_extract.py gold_triples). Store only: nothing here may be written into the repo.

fixed=True (default) applies store B/gold_fixes.json (relabels, wrong / unsupported edges) and the
corrected gender; fixed=False is the v0 gold the base draw was made on (b_items.base_candidates).
"""
from __future__ import annotations

import collections
from functools import lru_cache

import b_card as Cd
import b_lib as L


def gender_of(i: str, fixed: bool = True) -> str:
    return L.tipnr()["gender" if fixed else "gender_v0"].get(i, "M")


def gender(i: str) -> str:
    return gender_of(i, True)


@lru_cache(None)
def gold_graph(p: str, fixed: bool = True) -> dict:
    """Persons labelled in pericope p; parent/partner edges whose two ends share a verse of p."""
    order, T, lab = L.struct()["order"], L.tipnr(), L.labels(fixed)
    cov, surf = collections.defaultdict(set), collections.defaultdict(collections.Counter)
    surf_ids = collections.defaultdict(set)
    for u in L.struct()["p2u"][p]:
        for c, i in lab.get(u, {}).items():
            if L.is_person(i):
                cov[i].add(u); surf[i][c] += 1; surf_ids[c].add(i)
    persons = set(cov)
    par, spouse, hopv = collections.defaultdict(set), collections.defaultdict(set), {}
    for y in persons:
        for x in T["parents"].get(y, set()) & persons:
            vs = sorted(cov[x] & cov[y], key=order.get)
            if vs and not (fixed and L.bad_edge("parent", x, y, p)):
                par[y].add(x); hopv[(x, y)] = vs
    for x in persons:
        for y in T["partners"].get(x, set()) & persons:
            vs = sorted(cov[x] & cov[y], key=order.get)
            if vs and not (fixed and L.bad_edge("partner", x, y, p)):
                spouse[x].add(y); hopv[(x, y)] = vs; hopv[(y, x)] = vs
    return dict(persons=persons, surf=surf, surf_ids=surf_ids, par=par, spouse=spouse, hopv=hopv,
                fixed=fixed)


def male_parent(g: dict, y: str):
    ms = [x for x in g["par"].get(y, ()) if gender_of(x, g["fixed"]) == "M"]
    return ms[0] if len(ms) == 1 else None


def surfaces(g: dict, i: str) -> list[str]:
    """All surfaces of individual i in the pericope, most frequent first."""
    return [c for c, _ in g["surf"][i].most_common()]


def hop_verses(g: dict, ids: list[str]) -> list[str | None]:
    """First shared verse per gold hop (None: not an edge of g, only for K0 supplement rows)."""
    out = []
    for a, b in zip(ids, ids[1:]):
        v = g["hopv"].get((b, a)) or g["hopv"].get((a, b))
        out.append(v[0] if v else None)
    return out


def chain_problem(g: dict, ids: list[str], sig: list[str]) -> str:
    """'' iff every gold hop is an edge of g (fixed gold) whose direction and parent gender match its
    sig letter, and every U hop goes to the unique male parent (probe_eval chain rule)."""
    for x, y, s in zip(ids, ids[1:], sig):
        if s in ("U", "Um"):
            ok = y in g["par"].get(x, ()) and gender_of(y, g["fixed"]) == ("F" if s == "Um" else "M")
            ok = ok and (s == "Um" or male_parent(g, x) == y)
        elif s in ("D", "Dm"):
            ok = x in g["par"].get(y, ()) and gender_of(x, g["fixed"]) == ("F" if s == "Dm" else "M")
        else:
            ok = y in g["spouse"].get(x, ())
        if not ok:
            return f"hop_{s}_not_in_gold"
    return ""


@lru_cache(None)
def oracle_triples() -> dict:
    """Gold parent/partner relations rendered as surface triples per verse (both ends labelled there;
    fixed gold); ids are iterated sorted so the oracle edge table does not depend on PYTHONHASHSEED."""
    T, by, u2p = L.tipnr(), collections.defaultdict(list), L.struct()["u2p"]
    for u, lab in L.labels(True).items():
        inv = collections.defaultdict(list)
        for c, i in lab.items():
            if L.is_person(i):
                inv[i].append(c)
        b, ch, v = u.split(".", 2)
        base, p = dict(unit_key=u, ch=int(ch), label=v), u2p.get(u, "")
        for y in inv:
            for x in sorted(T["parents"].get(y, set())):
                if x in inv and not L.bad_edge("parent", x, y, p):
                    role = "M" if gender(x) == "F" else "P"
                    by[u].append(dict(base, head=inv[x][0], rel="PARENT_OF", tail=inv[y][0], role=role))
        for x in inv:
            for y in sorted(T["partners"].get(x, set())):
                if y in inv and x < y and not L.bad_edge("partner", x, y, p):
                    by[u].append(dict(base, head=inv[x][0], rel="SPOUSE_OF", tail=inv[y][0], role="-"))
    return {u: [t for t in ts if t["head"] != t["tail"]] for u, ts in by.items()}


def _rel_key(sig: tuple) -> tuple:
    """Kinship term identity of a canonical signature: the first hop keeps its side (father /
    mother), later hops ignore it (probe_eval.judge_pair rule)."""
    return (sig[0], tuple(s.rstrip("m") for s in sig[1:])) if sig else ()


def relation_unique(g: dict, ids: list[str], sig: list[str]) -> bool:
    """True iff every shortest (<=5 hop) gold path from ids[0] to ids[-1] names the gold relation."""
    adj = collections.defaultdict(list)
    for y, ps in g["par"].items():
        for x in ps:
            mother = gender_of(x, g["fixed"]) == "F"
            adj[x].append((y, "Dm" if mother else "D", ""))
            adj[y].append((x, "Um" if mother else "U", ""))
    for x, ys in g["spouse"].items():
        for y in ys:
            adj[x].append((y, "S", ""))
    for v in adj.values():
        v.sort()
    paths = Cd.shortest_paths(dict(adj=adj, blocked=set()), ids[0], ids[-1])
    want = _rel_key(Cd.canon(tuple(sig)))
    return bool(paths) and all(_rel_key(Cd.canon(tuple(r for _, r, _ in p))) == want for p in paths)

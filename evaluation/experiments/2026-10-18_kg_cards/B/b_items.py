"""Dev pericopes, the 48 dev items and their frozen keys (prereg §3; method in appendix B).

Selection reads only pericope ids, books, item types and the gold chain (ids, surfaces); never
any card or arm outcome (items_eval PER / R5 / Q5 outcome fields are not read; R5.units is the
item's context and is read after selection). The base draw runs on the v0 gold; slots that fail the
fixed gold or are listed in gold_exclusions.json are then replaced one by one (replace()).
"""
from __future__ import annotations

import collections
import random

import b_gold as Gd
import b_lib as L
import b_terms as Tm

N_DEV_PERICOPES = 12
N_ITEMS = 48
PER_PERICOPE_CAP = 8
TYPES = ("LIN2", "LIN3", "LIN4", "SEQ", "UNC", "COU", "MGF", "PGM", "FIL", "DIL")
# base quota per stratum (SEQ split by k); collateral UNC+COU >= 20 is enforced in draw()
BASE_QUOTA = {"UNC": 10, "COU": 10, "LIN2": 4, "LIN3": 4, "LIN4": 4, "SEQ3": 3, "SEQ4": 3, "SEQ5": 2,
              "MGF": 2, "PGM": 2, "FIL": 2, "DIL": 2}
MIN_COLLATERAL = 20
# seats left after the base draw go one at a time, cycling this order, to strata with candidates
REFILL_ORDER = ("UNC", "COU", "SEQ3", "SEQ4", "SEQ5", "LIN2", "LIN3", "LIN4", "MGF", "PGM", "FIL", "DIL")


def stratum(r: dict) -> str:
    return f"SEQ{len(r['sig'])}" if r["type"] == "SEQ" else r["type"]


def item_pericopes() -> list[str]:
    fr = L.frame()
    return sorted({r["pericope"] for r in L.items_eval() if r["pericope"] in fr})


def dev_pericopes(rng: random.Random) -> tuple[list[str], dict]:
    """Proportional allocation by book (largest remainder; remainder ties by one rng draw per book
    in book-id order), then rng.sample within each book in book-id order."""
    by_book = collections.defaultdict(list)
    for p in item_pericopes():
        by_book[p.split(":")[1].split(".")[0]].append(p)
    n = sum(len(v) for v in by_book.values())
    books = sorted(by_book)
    tie = {b: rng.random() for b in books}
    exact = {b: N_DEV_PERICOPES * len(by_book[b]) / n for b in books}
    alloc = {b: int(exact[b]) for b in books}
    rest = N_DEV_PERICOPES - sum(alloc.values())
    for b in sorted(books, key=lambda b: (-(exact[b] - alloc[b]), tie[b]))[:rest]:
        alloc[b] += 1
    picked = []
    for b in books:
        picked += rng.sample(sorted(by_book[b]), alloc[b])
    meta = dict(n_item_pericopes=n, n_frame=len(L.frame()),
                alloc={b: [alloc[b], len(by_book[b])] for b in books if alloc[b]})
    return sorted(picked), meta


def _valid_v0(r: dict, g: dict) -> bool:
    """Validity rules of the base draw: no anchor surface naming >1 person in the pericope; a LIN
    anchor not named like its answer; a pair's two names differ and every shortest gold path between
    them names one relation (Gd.relation_unique)."""
    ids, surf = r["ids"], r["surfaces"]
    lin = r["type"] in Tm.LIN_WORDS
    if any(len(g["surf_ids"][s]) > 1 for s in ([surf[0]] if lin else [surf[0], surf[-1]])):
        return False
    if lin:
        return not set(Gd.surfaces(g, ids[-1])) & set(Gd.surfaces(g, ids[0]))
    return surf[0] != surf[-1] and Gd.relation_unique(g, ids, r["sig"])


def make_key(r: dict, g: dict) -> dict:
    ids, surf, typ = r["ids"], r["surfaces"], r["type"]
    a, b = surf[0], surf[-1]
    if typ in Tm.LIN_WORDS:
        accept = Gd.surfaces(g, ids[-1])
        up = Gd.male_parent(g, ids[-1])
        trap_ids = list(ids[1:-1]) + ([up] if up and up not in ids else [])
        neutral = Gd.surfaces(g, ids[0])
        trap = [s for i in trap_ids for s in Gd.surfaces(g, i) if s not in accept and s not in neutral]
        return dict(kind="name", accept=accept, trap=sorted(set(trap)), neutral=neutral,
                    question=Tm.question(typ, a, b))
    tk = Tm.term_key(typ, len(r["sig"]), Gd.gender(ids[0]), Gd.gender(ids[1]))
    accept, trap = Tm.term_table(tk)
    names = sorted({s for i in ids for s in Gd.surfaces(g, i)})
    return dict(kind="term", term_key=tk, accept=accept, trap=trap, names=names,
                question=Tm.question(typ, a, b))


def check_item(r: dict, g: dict) -> tuple[dict | None, str]:
    """(frozen key, '') on the fixed gold, or (None, reason): the question's names must still be
    surfaces of their persons, every gold hop a fixed-gold edge matching its sig letter
    (Gd.chain_problem); UNC / COU need a male b (伯叔／堂兄弟 tables); then the v0 rules."""
    ends = [(r["surfaces"][0], r["ids"][0]), (r["surfaces"][-1], r["ids"][-1])]
    if any(s not in g["surf"].get(i, {}) for s, i in ends):
        return None, "anchor_surface_not_in_gold"
    why = Gd.chain_problem(g, r["ids"], r["sig"])
    if why:
        return None, why
    if r["type"] in ("UNC", "COU") and Gd.gender(r["ids"][-1]) == "F":
        return None, "collateral_b_female"
    if not _valid_v0(r, g):
        return None, "validity_rule"
    return make_key(r, g), ""


def _rows(dev: list[str]) -> list[dict]:
    devs = set(dev)
    rows = [r for r in L.items_eval() if r["pericope"] in devs and r["type"] in TYPES]
    return sorted(rows, key=lambda r: (r["pericope"], r["type"], r["surfaces"], r["ids"]))


def base_candidates(dev: list[str]) -> dict:
    """The base draw's pool (v0 gold, v0 rules): stratum -> [(row, {question})], canonical order."""
    out = collections.defaultdict(list)
    for r in _rows(dev):
        if _valid_v0(r, Gd.gold_graph(r["pericope"], fixed=False)):
            out[stratum(r)].append((r, dict(question=Tm.question(r["type"], r["surfaces"][0], r["surfaces"][-1]))))
    return out


def candidates(dev: list[str]) -> dict:
    """Replacement pool (fixed gold, check_item): stratum -> [(row, key)], canonical order."""
    out = collections.defaultdict(list)
    for r in _rows(dev):
        key, _ = check_item(r, Gd.gold_graph(r["pericope"]))
        if key is not None:
            out[stratum(r)].append((r, key))
    return out


def item_uid(r: dict) -> str:
    return "|".join([r["pericope"], r["type"], *r["surfaces"]])


def draw_order(cands: dict) -> list[str]:
    """Scarcest first (fewest pericopes holding candidates, then fewest candidates); UNC is moved
    right after COU so the collateral floor is drawn before the other strata fill the pericopes."""
    order = sorted(BASE_QUOTA, key=lambda s: (len({r["pericope"] for r, _ in cands.get(s, [])}),
                                              len(cands.get(s, [])), s))
    order.remove("UNC")
    order.insert(order.index("COU") + 1, "UNC")
    return order


class _Draw:
    def __init__(self, cands: dict, rng: random.Random, excluded: set):
        self.order = draw_order(cands)
        self.lists = {}
        for s in self.order:
            lst = list(cands.get(s, []))
            rng.shuffle(lst)
            self.lists[s] = lst
        self.excluded, self.taken, self.seen_q = excluded, set(), set()
        self.per_p, self.count, self.picks, self.relaxed = collections.Counter(), collections.Counter(), [], []

    def take(self, s: str, cap: int | None) -> bool:
        """First eligible candidate under the cap; cap None = the least-loaded pericope (relaxed)."""
        ok = [(r, key) for r, key in self.lists.get(s, [])
              if item_uid(r) not in self.taken and item_uid(r) not in self.excluded
              and key["question"] not in self.seen_q]
        if cap is not None:
            ok = [(r, key) for r, key in ok if self.per_p[r["pericope"]] < cap]
        elif ok:
            low = min(self.per_p[r["pericope"]] for r, _ in ok)
            ok = [(r, key) for r, key in ok if self.per_p[r["pericope"]] == low]
            self.relaxed.append(dict(stratum=s, pericope=ok[0][0]["pericope"]))
        if not ok:
            return False
        r, key = ok[0]
        self.taken.add(item_uid(r)); self.seen_q.add(key["question"])
        self.per_p[r["pericope"]] += 1; self.count[s] += 1
        self.picks.append((s, r, key))
        return True

    def collateral(self) -> int:
        return self.count["UNC"] + self.count["COU"]


def draw(cands: dict, rng: random.Random, excluded: set) -> tuple[list, dict]:
    """1) each stratum up to its base quota under the per-pericope cap, in draw_order (UNC's
    quota raised to 20 - COU drawn); 2) UNC, else COU, until UNC+COU >= 20; 3) one seat at a
    time cycling REFILL_ORDER. Steps 2-3 relax the cap (least-loaded pericope, recorded) only
    when no capped candidate is left."""
    d = _Draw(cands, rng, excluded)
    for s in d.order:
        target = BASE_QUOTA[s]
        if s == "UNC":
            target = max(target, MIN_COLLATERAL - d.count["COU"])
        while d.count[s] < target and d.take(s, PER_PERICOPE_CAP):
            pass
    while d.collateral() < MIN_COLLATERAL and len(d.picks) < N_ITEMS:
        if not any(d.take(s, cap) for cap in (PER_PERICOPE_CAP, None) for s in ("UNC", "COU")):
            break
    for cap in (PER_PERICOPE_CAP, None):
        moved = True
        while len(d.picks) < N_ITEMS and moved:
            moved = False
            for s in REFILL_ORDER:
                if len(d.picks) < N_ITEMS and d.take(s, cap):
                    moved = True
    if len(d.picks) != N_ITEMS or d.collateral() < MIN_COLLATERAL:
        raise ValueError(f"draw: {len(d.picks)} items, collateral {d.collateral()}")
    return d.picks, dict(draw_order=d.order, relaxed=d.relaxed, per_pericope=dict(d.per_p),
                         per_stratum=dict(d.count))


def _tiers(s: str, p: str):
    """Replacement tiers for a slot of stratum s in pericope p: (name, strata, rule). 1-2 keep the
    stratum (same pericope; another dev pericope under the cap); 3 = the base draw's own fallback:
    draw step 2 for UNC / COU (floor UNC+COU >= 20), draw step 3 (REFILL_ORDER) otherwise; under
    the cap first, then the least-loaded pericope."""
    yield "same_pericope", (s,), ("pericope", p)
    yield "other_dev_pericope", (s,), ("cap", None)
    order = ("UNC", "COU") if s in ("UNC", "COU") else REFILL_ORDER
    for rule in ("cap", "least_loaded"):
        for t in order:
            yield f"draw_fallback_{rule}", (t,), (rule, None)


def _pick_pool(cands: list, rule: tuple, per_p: collections.Counter) -> list:
    kind, p = rule
    if kind == "pericope":
        return [c for c in cands if c[1]["pericope"] == p]
    if kind == "cap":
        return [c for c in cands if per_p[c[1]["pericope"]] < PER_PERICOPE_CAP]
    low = min((per_p[c[1]["pericope"]] for c in cands), default=None)
    return [c for c in cands if per_p[c[1]["pericope"]] == low]


def replace(ordered: list, pool: dict, bad: dict, excluded: set) -> tuple[list, list]:
    """ordered: [(stratum, row, key)] in item-id order; bad: {index: reason}. Each bad slot, in id
    order, takes a never-selected candidate by _tiers; one Random(20261018) picks among the eligible
    candidates of the first non-empty tier (canonical order)."""
    rng = random.Random(L.SEED)
    keep = [x for i, x in enumerate(ordered) if i not in bad]
    taken = {item_uid(r) for _, r, _ in ordered} | set(excluded)
    seen_q = {key["question"] for _, _, key in keep}
    per_p = collections.Counter(r["pericope"] for _, r, _ in keep)
    out, log = list(ordered), []
    for i in sorted(bad):
        s, r0, _ = ordered[i]
        for tier, strata, rule in _tiers(s, r0["pericope"]):
            cands = [(t, r, k) for t in strata for r, k in pool.get(t, [])
                     if item_uid(r) not in taken and k["question"] not in seen_q]
            cands = _pick_pool(cands, rule, per_p)
            if cands:
                break
        else:
            raise ValueError(f"replace: no candidate for slot {i + 1} ({s})")
        t, r, k = rng.choice(cands)
        taken.add(item_uid(r)); seen_q.add(k["question"]); per_p[r["pericope"]] += 1
        out[i] = (t, r, k)
        log.append(dict(slot=i + 1, stratum=s, new_stratum=t, reason=bad[i], old_uid=item_uid(r0),
                        old_pericope=r0["pericope"], new_uid=item_uid(r), new_pericope=r["pericope"],
                        tier=tier, n_eligible=len(cands)))
    return out, log

"""§4 descriptive metrics and §5/§6 comparisons on in-memory items (private part of evaluate.py).

Item is one question as the tests see it (§4 gold and missing hops, §2 category, §7
density, core, [SHORTCUT]); Table holds the top-k and f(q) of every arm over pools and
scores that may span several question sets (E2 = OLD31 ∪ HO). compare() is one X−Y
comparison with units by union-find inside the given items (§5): Δ̄, W:L, CI and, when
asked, the exact sign-flip p. hypotheses() is the §5 把關順序, descriptive() the 只描述
pairs, sensitivity() the 必報敏感度 (H3 without [SHORTCUT] questions and, given a W
table of window-max scores, GD_W−C_W with the §10 cut gaps of C_W and GD_W included),
attached_notes() the 事先寫死的附註, and v1_decision() the §6 停損 rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import _eval_metrics as M
import _eval_stats as st
import _score_w as sw
import gd_common as gd

H_PAIRS = {"H1": ("GD", "C", 10), "H2": ("GD", "C", 5),
           "H3_LEXPRF": ("GD", "LEXPRF", 10), "H3_L": ("GD", "L", 10)}
H3_ARMS = ("LEXPRF", "L")
DESCRIPTIVE = (("G", "C"), ("GD_DEGNORM", "C"), ("L", "C"), ("LEXPRF", "C"), ("GD", "G"))
W_NOT_GIVEN = "未提供 --scores-w（score.py rerank-w 的 W 逐窗重排分數）"
HOLM_RULE = "H1 過了之後 H2、H3 並列：較小 p <0.025，另一項 <0.05"
V1_MIN_DISCORDANT = 3          # §6: 不一致 ≥3 且負 ≥勝 → 結案
V1_RULE = "20 個單位中不一致 ≥3 且負 ≥勝 → 結案，不出 HO；其餘一律繼續（§6）"
SOURCE_STORED = "stored missing_rr (PN/question_summary.json)"
SOURCE_D5 = "D5≈ (R20 top 5 by −reranker score, pid)"
SOURCE_NONE = "not computed (gold only)"

Cov = Mapping[str, Fraction]           # qid -> f(q)


@dataclass(frozen=True)
class Item:
    """One question: §4 gold per hop and missing hops, §2 category, §7 density value."""
    qid: str
    set_name: str
    category: str
    gold: tuple[frozenset[str], ...]
    missing: frozenset[int]
    core: str | None
    density: Fraction
    shortcut: bool | None = None                 # HO only (§7 [SHORTCUT])
    prod_d5_missing: frozenset[int] | None = None   # OLD31 only (§4 另附)
    missing_source: str = SOURCE_STORED

    @property
    def gold_union(self) -> frozenset[str]:
        return frozenset().union(*self.gold)

    @property
    def low_density(self) -> bool:
        return self.density < M.LOW_DENSITY


def items_of(qset: gd.QuestionSet, r20: Mapping[str, Sequence[str]] | None = None,
             scores: Mapping[str, Mapping[str, float]] | None = None,
             gold_only: bool = False) -> tuple[Item, ...]:
    """Items of a set; missing hops are the stored ones (NEW82) or D5≈ from R20 and scores
    (gold_only: none, for the gold-only unit table)."""
    out = []
    for q in qset.questions:
        gold = gd.question_gold(q)
        if gold_only:
            missing, source = frozenset(), SOURCE_NONE
        elif q.missing_hops is not None:
            missing, source = q.missing_hops, SOURCE_STORED
        elif r20 is None or scores is None:
            raise gd.GdError(f"{qset.name}: §4 missing hops need D5≈ (lists R20 and scores)")
        else:
            missing, source = M.d5_missing(gold, r20[q.qid], scores[q.qid]), SOURCE_D5
        out.append(Item(q.qid, qset.name, q.category, gold, missing, q.core,
                        M.density_value(gold), q.shortcut, q.prod_d5_missing, source))
    return tuple(out)


class Table:
    """Top-k and f(q) of every arm present in `pools`, k and metric version (any-hit / strict)."""

    def __init__(self, items: Sequence[Item], pools: Mapping[str, Mapping[str, Sequence[str]]],
                 scores: Mapping[str, Mapping[str, float]]) -> None:
        self.items, self.arms = tuple(items), tuple(a for a in M.ARMS if a in pools)
        self.pools, self.scores = pools, scores
        self.top = {(a, k): {it.qid: self._top(a, it.qid, k) for it in items}
                    for a in self.arms for k in M.KS}
        self._cov: dict[tuple[str, int, bool], Cov] = {}

    def _top(self, arm: str, qid: str, k: int) -> tuple[str, ...]:
        try:
            return M.top_k(self.pools[arm][qid], self.scores[qid], k)
        except gd.GdError as err:
            raise gd.GdError(f"{qid} / {arm}: {err}") from err

    def cov(self, arm: str, k: int, strict: bool = False) -> Cov:
        key = (arm, k, strict)
        if key not in self._cov:
            tops = self.top[arm, k]
            self._cov[key] = MappingProxyType(
                {it.qid: M.coverage(it.gold, tops[it.qid], strict) for it in self.items})
        return self._cov[key]


# ------------------------------------------------------------------ comparisons (§5)

def compare(items: Sequence[Item], fx: Cov, fy: Cov, *, with_p: bool, core: bool = False,
            singletons: bool = False) -> tuple[dict[str, Any], tuple[Fraction, Fraction] | None]:
    """d = fx − fy per question, units by union-find inside `items`; returns (report, (p, Σv))."""
    if not items:
        return {"n_questions": 0}, None
    d = {it.qid: fx[it.qid] - fy[it.qid] for it in items}
    if singletons:
        units = tuple((q,) for q in sorted(d))
    else:
        units = st.clusters(d, {it.qid: it.gold_union for it in items},
                            {it.qid: it.core for it in items} if core else None)
    values = st.unit_values(units, d)
    s = st.summarize(values)
    lo, hi = st.bootstrap(values)
    out: dict[str, Any] = {
        "n_questions": len(items), "n_units": s.n_units, "max_unit": max(map(len, units)),
        "unit_W": s.wins, "unit_L": s.losses, "unit_W:L": f"{s.wins}:{s.losses}",
        "discordant_units": s.wins + s.losses, "direction": s.direction, "sum_v": str(s.total),
        "mean_unit_diff": float(s.mean), "ci95": [lo, hi],
        "question_W:L": f"{sum(v > 0 for v in d.values())}:{sum(v < 0 for v in d.values())}",
        "mean_question_diff": float(sum(d.values()) / len(d))}
    if not with_p:
        return out, None
    sf = st.sign_flip(values)
    out.update(p=float(sf.p), p_exact=str(sf.p), p_method=sf.method, dp_states=sf.states)
    return out, (sf.p, s.total)


def hypotheses(table: Table) -> dict[str, Any]:
    """§5 把關順序 on the four tested pairs; p of H2/H3 is withheld unless H1 passes."""
    res, test = {}, {}
    for name, (x, y, k) in H_PAIRS.items():
        res[name], test[name] = compare(table.items, table.cov(x, k), table.cov(y, k), with_p=True)
        res[name]["pair"] = f"{x}-{y}@{k}"
    g = st.gate(test["H1"], test["H2"], (test["H3_LEXPRF"], test["H3_L"]))
    if not g["H1"]["pass"]:
        for name in ("H2", "H3_LEXPRF", "H3_L"):
            res[name] = {k: v for k, v in res[name].items()
                         if k not in ("p", "p_exact", "p_method", "dp_states")}
            res[name]["p_withheld"] = "H1 未過：H2、H3 只報 W:L 與 CI（§5）"
    h3 = {key: val for key, val in g["H3"].items() if key != "p"}
    if "p" in g["H3"]:
        h3.update(p=float(g["H3"]["p"]), p_exact=str(g["H3"]["p"]))
    return {"H1": {**res["H1"], **g["H1"]}, "H2": {**res["H2"], **g["H2"]},
            "H3": {**h3, "parts": {"GD-LEXPRF@10": res["H3_LEXPRF"], "GD-L@10": res["H3_L"]}},
            "alpha": float(st.ALPHA), "holm": HOLM_RULE}


def descriptive(table: Table) -> dict[str, Any]:
    """§5 只描述的對: W:L, Δ̄, CI, no p."""
    out: dict[str, Any] = {}
    for x, y in DESCRIPTIVE:
        for k in M.KS:
            absent = [a for a in (x, y) if a not in table.arms]
            out[f"{x}-{y}@{k}"] = {"absent_arms": absent} if absent else compare(
                table.items, table.cov(x, k), table.cov(y, k), with_p=False)[0]
    return out


def new82_gold() -> frozenset[str]:
    return frozenset(p for q in gd.load_new82().questions for h in gd.question_gold(q) for p in h)


def subsets(items: Sequence[Item], shared: frozenset[str] | None = None) -> dict[str, dict[str, list[Item]]]:
    """§5 必報敏感度 strata; each is re-clustered inside itself by compare(). `shared` is the
    NEW82 gold (loaded when OLD31 items are present and it is not given)."""
    out = {"category": {c: [it for it in items if it.category == c] for c in gd.CATEGORIES
                        if any(it.category == c for it in items)},
           "density": {"low": [it for it in items if it.low_density],
                       "high": [it for it in items if not it.low_density]}}
    sets = sorted({it.set_name for it in items})
    if len(sets) > 1:
        out["by_set"] = {s: [it for it in items if it.set_name == s] for s in sets}
    if "old31" in sets:
        shared = new82_gold() if shared is None else shared
        kept = [it for it in items if not (it.set_name == "old31" and it.gold_union & shared)]
        out["excl_new82_shared"] = {"kept": kept}
    return out


def h3_without_shortcut(table: Table) -> dict[str, Any]:
    """§5: H3's two pairs on the items left after dropping the HO [SHORTCUT] questions."""
    ho = [it for it in table.items if it.set_name == "ho"]
    if not ho:
        return {"not_applicable": "[SHORTCUT] 只出現在 HO（§5、§7）"}
    if any(it.shortcut is None for it in ho):
        raise gd.GdError("HO items without the [SHORTCUT] flag: cannot report H3 without them (§5)")
    kept = [it for it in table.items if not it.shortcut]
    out: dict[str, Any] = {"excluded": sorted(it.qid for it in table.items if it.shortcut)}
    for y in H3_ARMS:
        out[f"GD-{y}@10"] = compare(kept, table.cov("GD", 10), table.cov(y, 10), with_p=False)[0]
    return out


def w_cut_gaps(w_table: Table, k: int) -> dict[str, Any]:
    """§10 on the W scores: smallest top-k cut gap of C_W and GD_W and the questions below
    1e−5 (listed, the decision does not change). W mixes two runs: single-window passages
    keep the whole-passage score, multi-window ones the W run's."""
    ids = [it.qid for it in w_table.items]
    gaps = M.cut_gap_table(w_table.pools, w_table.scores, sw.W_ARMS, ids)
    return {f"{a}_W@{k}": gaps[f"{a}@{k}"] for a in sw.W_ARMS}


def w_block(table: Table, w_table: Table | None, k: int) -> dict[str, Any]:
    """§5 W 版: GD_W−C_W@k on the same items and gold-cluster units (W:L and CI, no p), from
    a Table of the C and GD pools under the window-max scores, with its cut gaps;
    not_computed without one."""
    if w_table is None:
        return {"not_computed": W_NOT_GIVEN}
    gd.expect("W table questions", [it.qid for it in w_table.items], [it.qid for it in table.items])
    gd.expect("W table arms", w_table.arms, sw.W_ARMS)
    out = compare(w_table.items, w_table.cov("GD", k), w_table.cov("C", k), with_p=False)[0]
    return {"pair": f"GD_W-C_W@{k}", **out, "cut_gaps": w_cut_gaps(w_table, k)}


def sensitivity(table: Table, shared: frozenset[str] | None = None,
                w_table: Table | None = None) -> dict[str, Any]:
    """GD−C@10 and @5: question level, strict, core clusters, W (given w_table), strata (W:L
    and CI only); plus H3 without [SHORTCUT] questions."""
    out: dict[str, Any] = {}
    strata = subsets(table.items, shared)
    for k in M.KS:
        gd_, c = table.cov("GD", k), table.cov("C", k)
        row: dict[str, Any] = {
            "question_level": compare(table.items, gd_, c, with_p=False, singletons=True)[0],
            "strict": compare(table.items, table.cov("GD", k, True), table.cov("C", k, True),
                              with_p=False)[0],
            "core_cluster": compare(table.items, gd_, c, with_p=False, core=True)[0],
            "W": w_block(table, w_table, k)}
        for group, parts in strata.items():
            row[group] = {name: compare(sub, gd_, c, with_p=False)[0] for name, sub in parts.items()}
        if "excl_new82_shared" not in row:
            row["excl_new82_shared"] = {"not_applicable": "只適用於 OLD31（§5）"}
        out[f"GD-C@{k}"] = row
    out["H3_excl_shortcut"] = h3_without_shortcut(table)
    return out


def attached_notes(table: Table, hyp: Mapping[str, Any],
                   shared: frozenset[str] | None = None) -> dict[str, Any]:
    """§5 事先寫死的附註 (only when H1 passes and the relevant set is in the pool)."""
    if not hyp["H1"]["pass"]:
        return {}
    gd_, c, notes = table.cov("GD", 10), table.cov("C", 10), {}
    ho = [it for it in table.items if it.set_name == "ho"]
    if ho:
        notes["ho_only_mean_le_0"] = compare(ho, gd_, c, with_p=False)[0]["mean_unit_diff"] <= 0
    strata = subsets(table.items, shared).get("excl_new82_shared")
    if strata:
        notes["excl_new82_shared_mean_le_0"] = (
            compare(strata["kept"], gd_, c, with_p=False)[0]["mean_unit_diff"] <= 0)
    return notes


# ------------------------------------------------------------------ §6 V1

def v1_decision(values: Sequence[Fraction]) -> dict[str, Any]:
    """§6 停損 on unit values of GD−C@10: stop when ≥3 units disagree and losses ≥ wins."""
    s = st.summarize(values)
    discordant = s.wins + s.losses
    return {"n_units": s.n_units, "unit_W:L": f"{s.wins}:{s.losses}", "discordant_units": discordant,
            "stop": discordant >= V1_MIN_DISCORDANT and s.losses >= s.wins, "rule": V1_RULE}


def v1(table: Table) -> dict[str, Any]:
    """V1 on OLD31: only the stop decision and the unit W:L of GD−C@10 (no p, no CI)."""
    d = {it.qid: table.cov("GD", 10)[it.qid] - table.cov("C", 10)[it.qid] for it in table.items}
    units = st.clusters(d, {it.qid: it.gold_union for it in table.items})
    return v1_decision(st.unit_values(units, d))


# ------------------------------------------------------------------ descriptive metrics (§4)

def _hits_at(items: Sequence[Item], hits: Mapping[str, tuple[bool, ...]], which: str) -> int:
    return sum(hits[it.qid][h] for it in items for h in (getattr(it, which) or ()))


def arm_metrics(table: Table, arm: str, k: int) -> dict[str, Any]:
    tops = table.top[arm, k]
    hits = {it.qid: M.hop_hits(it.gold, tops[it.qid]) for it in table.items}
    strict = {it.qid: M.hop_hits(it.gold, tops[it.qid], True) for it in table.items}
    out: dict[str, Any] = {
        "all_hops_hit": sum(map(sum, hits.values())),
        "full_chain": sum(all(h) for h in hits.values()),
        "missing_hops_hit": _hits_at(table.items, hits, "missing"),
        "mean_coverage": float(sum(table.cov(arm, k).values()) / len(table.items)),
        "strict_all_hops_hit": sum(map(sum, strict.values())),
        "strict_full_chain": sum(all(h) for h in strict.values())}
    sets = sorted({it.set_name for it in table.items})
    if len(sets) > 1:
        out["missing_hops_hit_by_set"] = {
            s: _hits_at([it for it in table.items if it.set_name == s], hits, "missing") for s in sets}
    if any(it.prod_d5_missing is not None for it in table.items):
        out["missing_hops_hit_prod_d5"] = _hits_at(table.items, hits, "prod_d5_missing")
    return out


def missing_summary(items: Sequence[Item]) -> dict[str, Any]:
    """Per set: the §4 missing-hop source, hops and questions (and prod D5 for OLD31)."""
    out: dict[str, Any] = {}
    for s in sorted({it.set_name for it in items}):
        part = [it for it in items if it.set_name == s]
        row = {"source": sorted({it.missing_source for it in part}),
               "hops": sum(len(it.missing) for it in part),
               "questions": sum(bool(it.missing) for it in part)}
        if any(it.prod_d5_missing is not None for it in part):
            row["prod_d5_hops"] = sum(len(it.prod_d5_missing or ()) for it in part)
        out[s] = row
    return out


def unit_table(items: Sequence[Item]) -> dict[str, Any]:
    units = st.clusters([it.qid for it in items], {it.qid: it.gold_union for it in items})
    by_id = {it.qid: it for it in items}
    return {"n_questions": len(items), "n_units": len(units), "max_unit": max(map(len, units)),
            "units": [list(u) for u in units],
            "density_low": sum(it.low_density for it in items),
            "density": {it.qid: str(it.density) for it in items},
            "categories": {c: sum(by_id[q].category == c for q in by_id) for c in gd.CATEGORIES}}

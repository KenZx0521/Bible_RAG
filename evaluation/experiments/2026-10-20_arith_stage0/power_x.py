"""Power of the confirmation-set proposal (prereg §7-5, description only): powerA_strong's model, copied.

The block between the COPY markers is store kgniche/synth/powerA_strong.py from ``rng = …`` to the end of
``cell`` (sha256 pinned in x_common and checked at import when the store is mounted), unchanged except
that ``cell`` is named ``_cell``. ``cell`` resets the module rng to default_rng(20261018) and clears SIGNS
before every call, so a result does not depend on call order. ``power_report`` pools the passing or gray
families' items (weighted by item count): a = share of items whose derived lines hold the gold, h = their
mean pG, pR, pC (GEN: pC := pB), gap = pR − pC computed then clamped; h, pR, pC, gap clamped to [0.01,
0.99], a not (as A). It reports (i) the template values and (ii) the shrink-adjusted ones (pR+0.25,
pC+0.22, h−0.05, a = min(a, 0.875); only (ii) goes into the proposal), for the given C and m, the
smallest C in 8..17 reaching pow_H1_and_H2 ≥ 0.7, the nested subset, and per family whether fewer than
half its items are nested (the units must then be redefined).
"""
from __future__ import annotations

import inspect
import warnings
from fractions import Fraction

import numpy as np

import x_common as X

SEED = 20261018
NSIM = 500
C_SEARCH = tuple(range(8, 18))
M_VALUES = (2, 3, 4)
TARGET = 0.7
EPS = 0.01
SHRINK = {"pR": Fraction("0.25"), "pC": Fraction("0.22"), "h": Fraction("-0.05"), "a_cap": Fraction("0.875")}
NO_C = "資料上限內達不到 0.7"
REDEFINE = "確認集的單位要重新定義，C＝9／8 的檢定力不適用"

if X.POWER_SRC.is_file() and X.sha256_file(X.POWER_SRC) != X.POWER_SRC_SHA256:
    raise SystemExit(f"{X.POWER_SRC}: sha256 is not {X.POWER_SRC_SHA256[:12]} (prereg §7-5)")
SOURCE_CHECKED = X.POWER_SRC.is_file()

# ---- COPY BEGIN: powerA_strong.py, verbatim except cell -> _cell
rng = np.random.default_rng(20261018)
ex = lambda x: 1/(1+np.exp(-x)); lg = lambda p: np.log(p/(1-p))
NF = 2000
SIGNS = {}
def signs(C):
    if C not in SIGNS:
        SIGNS[C] = rng.choice([-1.0, 1.0], size=(NF, C))
    return SIGNS[C]
def sf_p(d):
    S = signs(len(d)); obs = abs(d.mean())
    return (1 + (np.abs(S @ d / len(d)) >= obs - 1e-12).sum()) / (NF + 1)

def one(C, m, a, h, pR, gap, w=0.05, r_wrong=0.5, R=3, sd_u=0.6, sd_e=1.0, sd_z=0.8):
    pC = max(pR - gap, 0.02)
    u = rng.normal(0, sd_u, (C, 1)); e = rng.normal(0, sd_e, (C, m))
    pr = ex(lg(pR) + u + e); pc = ex(lg(pC) + u + e)
    r = rng.random((C, m))
    ok = r < a; wrong = (r >= a) & (r < a + w); abst = ~(ok | wrong)
    hi = ex(lg(h) + rng.normal(0, sd_z, (C, m)))
    sc = lambda p: rng.binomial(R, p) / R
    sR = sc(pr); sC = sc(pc)
    sG_ok = sc(hi); sG_wr = sc(pr * r_wrong)
    sG = np.where(ok, sG_ok, np.where(wrong, sG_wr, sR))  # 棄權：與 T-rows 共用輸出
    d1 = (sG - sC).mean(1); d2 = (sG - sR).mean(1)
    p1 = sf_p(d1); h1 = (p1 < 0.05) and d1.mean() >= 0.10
    p2 = sf_p(d2); h2 = h1 and (p2 < 0.05) and d2.mean() >= 0.10
    return h1, h2, d1.mean(), d2.mean()

def _cell(C, m, a, h, pR, gap, nsim=500):
    rs = [one(C, m, a, h, pR, gap) for _ in range(nsim)]
    return dict(C=C, m=m, a=a, h=h, pR=pR, gap=gap,
                pow_H1=round(float(np.mean([x[0] for x in rs])), 3),
                pow_H1_and_H2=round(float(np.mean([x[1] for x in rs])), 3),
                mean_d1=round(float(np.mean([x[2] for x in rs])), 3),
                mean_d2=round(float(np.mean([x[3] for x in rs])), 3))
# ---- COPY END


def copied_block() -> str:
    """The source text between the COPY markers (for the verbatim check)."""
    lines = inspect.getsource(inspect.getmodule(copied_block)).splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("# ---- COPY BEGIN"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("# ---- COPY END"))
    return "\n".join(lines[start + 1:end])


def cell(C: int, m: int, a: float, h: float, pR: float, gap: float, nsim: int = NSIM) -> dict:
    """The store model's cell with rng = default_rng(20261018) and SIGNS cleared first."""
    global rng
    rng = np.random.default_rng(SEED)
    SIGNS.clear()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _cell(int(C), int(m), float(a), float(h), float(pR), float(gap), nsim=nsim)


# ---------------------------------------------------------------- inputs
def to_frac(v) -> Fraction:
    if isinstance(v, dict):
        return Fraction(v["frac"])
    if isinstance(v, (Fraction, int, str)):
        return Fraction(v)
    return Fraction(repr(float(v)))


def _mean(xs: list[Fraction]) -> Fraction | None:
    return sum(xs, Fraction(0)) / len(xs) if xs else None


def pooled(rows: list[dict]) -> dict:
    """Item-weighted a, h, pR, pC (exact) of rows {id, family, covered, nested, pG, pR, pC}."""
    cov = [r for r in rows if r["covered"]]
    return {"n_items": len(rows), "n_covered": len(cov),
            "a": Fraction(len(cov), len(rows)) if rows else Fraction(0),
            "h": _mean([to_frac(r["pG"]) for r in cov]),
            "pR": _mean([to_frac(r["pR"]) for r in rows]), "pC": _mean([to_frac(r["pC"]) for r in rows])}


def clamp(p: Fraction | float) -> float:
    return min(max(float(p), EPS), 1 - EPS)


def model_inputs(p: dict, adjusted: bool) -> dict:
    """(i) template values, or (ii) shrink-adjusted ones; h, pR, pC, gap clamped, a not."""
    a, h, pR, pC = p["a"], p["h"] if p["h"] is not None else Fraction(0), p["pR"], p["pC"]
    if adjusted:
        a, h, pR, pC = min(a, SHRINK["a_cap"]), h + SHRINK["h"], pR + SHRINK["pR"], pC + SHRINK["pC"]
    return {"a": float(a), "h": clamp(h), "pR": clamp(pR), "pC": clamp(pC), "gap": clamp(pR - pC),
            "gap_raw": float(pR - pC)}


def rows_from_scores(scores: dict, items: list[dict], covered: dict, families: tuple[str, ...]) -> list[dict]:
    """Power rows of the given families from score_x.score_all output (GEN: pC := B0)."""
    out = []
    for it in items:
        if it["family"] not in families:
            continue
        m = scores["items"][it["id"]]["mean"]
        pc = m["B0"] if it["family"] == "GEN" else m["T-canon"]
        out.append({"id": it["id"], "family": it["family"], "covered": bool(covered[it["id"]]),
                    "nested": bool(it["nested"]), "pG": to_frac(m["G"]), "pR": to_frac(m["T-rows"]),
                    "pC": to_frac(pc)})
    return out


# ---------------------------------------------------------------- report
def _fx(f: Fraction | None):
    return None if f is None else {"frac": str(f), "float": float(f)}


def _subset(rows: list[dict], C_values, m_values, nsim: int, memo: dict) -> dict | None:
    if not rows:
        return None
    p = pooled(rows)
    out = {"pooled": {k: (_fx(v) if isinstance(v, Fraction) else v) for k, v in p.items()},
           "ids": [r["id"] for r in rows], "inputs": {}, "cells": {}, "search": {}, "min_C": {}}

    def run(C: int, m: int, inp: dict) -> dict:
        args = (C, m, inp["a"], inp["h"], inp["pR"], inp["gap"], nsim)
        if args not in memo:
            memo[args] = cell(*args[:6], nsim=nsim)
        return memo[args]

    for s, adjusted in (("i", False), ("ii", True)):
        inp = model_inputs(p, adjusted)
        out["inputs"][s] = inp
        out["cells"][s] = [run(C, m, inp) for C in C_values for m in m_values]
        out["search"][s], out["min_C"][s] = {}, {}
        for m in m_values:
            grid = [run(C, m, inp) for C in C_SEARCH]
            ok = [c["C"] for c in grid if c["pow_H1_and_H2"] >= TARGET]
            out["search"][s][str(m)] = grid
            out["min_C"][s][str(m)] = {"C": ok[0] if ok else None, "note": None if ok else NO_C}
    return out


def power_report(inputs: list[dict], C_values, m_values=M_VALUES, nsim: int = NSIM) -> dict:
    """prereg §7-5 on rows {id, family, covered, nested, pG, pR, pC} of the passing or gray families.
    C_values: 9 (DYN only), 8 (GEN only) or 17 (both); the proposal uses input set (ii) only."""
    memo: dict = {}
    by_fam: dict[str, list[dict]] = {}
    for r in inputs:
        by_fam.setdefault(r["family"], []).append(r)
    check = {}
    for f, rs in by_fam.items():
        k = sum(bool(r["nested"]) for r in rs)
        redefine = k < len(rs) / 2
        check[f] = {"n_items": len(rs), "n_nested": k, "redefine_units": redefine, "note": REDEFINE if redefine else None}
    return {"model": {"source": str(X.POWER_SRC), "sha256": X.POWER_SRC_SHA256, "source_checked": SOURCE_CHECKED,
                      "seed": SEED, "nsim": nsim, "reset_per_cell": True},
            "C_values": list(C_values), "m_values": list(m_values), "C_search": [C_SEARCH[0], C_SEARCH[-1]],
            "target": TARGET, "shrink": {k: float(v) for k, v in SHRINK.items()},
            "subsets": {"all": _subset(list(inputs), C_values, m_values, nsim, memo),
                        "nested": _subset([r for r in inputs if r["nested"]], C_values, m_values, nsim, memo)},
            "nested_check": check}

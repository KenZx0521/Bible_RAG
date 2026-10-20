"""Power, the frozen coverage gate and the false-positive check of the GEN confirmation set (prereg §7).

CPU only, numpy only; nothing here calls Ollama or any LLM. The pool structure (strata, chapters, the 17
begetting edges, persons, homonym ends) comes from store pool.json (sha256 pinned below); tests may pass a
synthetic pool to ``Pool``.

Model M1 (prereg §7.2; calibrated on experiment A's blind per-rep scores, see §7.1):
  baseline latent  Z_B = sqrt(FE_B)·(shared edge part) + sqrt(1 − FE_B)·(slot part), unit variance
  T-rows           p_R = expit(mu_R + S_B·Z_B)
  B0               p_C = expit(mu_C + S_B·(R_RC·Z_B + sqrt(1 − R_RC²)·Z_C))
  G when covered   p_G = expit(mu_G + S_G·(R_GB·Z_B + sqrt(1 − R_GB²)·Z_G)), Z_G with edge share FE_G
  centring         each mu solved so the arm's mean equals its (ii) input
  coverage         logit clustered by person (sd CL over X and Y), homonym ends shifted HS, mean = a
  wrong card       P(wrong | not covered) = w / (1 − a); G scores G_ON_WRONG on it (copies the wrong line)
  abstention       G = T-rows = B0's outputs, so d1 = d2 = 0
  reps             3, binomial; optional chapter effect (sd SCH, sensitivity only)
The test is an exact replica of ``src.ab_stats.sign_flip_p(d, seed=20261018)`` (zeros dropped; exact
enumeration up to 16 non-zero, else 20,000 Monte-Carlo flips with add-one) plus the floor Δ̄ ≥ +0.10, in
the fixed order H1 (G − B0) then H2 (G − T-rows). Differences are carried as integers 3·d so the float32
sums are exact.
"""
from __future__ import annotations

import itertools
import json
import math
import random
import sys
from dataclasses import dataclass, replace
from fractions import Fraction

import numpy as np

import g_common as GC

POOL_SHA256 = GC.POOL_SHA256
STRATA = ("F1c5", "F1c11", "F5c5", "F5c11")
II = dict(a=0.875, h=0.8759259259259259, pR=0.5648148148148148, pC=0.4792592592592593)   # stage-0 (ii)
TARGET, FLOOR3, ALPHA = 0.70, 0.30, 0.05            # power target; floor Δ̄ ≥ 0.10 as 3·d; test level
NSIM, CHUNK = 10000, 2500
A_CAP, W_FLOOR = 0.875, 0.05
NPERM, EXACT_MAX = 20000, 16


@dataclass(frozen=True)
class Model:
    S_B: float = 3.9          # baseline logit sd (A blind T-rows 3.86, B0 4.17)
    FE_B: float = 0.265       # share of the baseline latent shared by begetting edge (0.36 / 1.36)
    R_RC: float = 0.34        # T-rows–B0 item correlation (A blind 0.337)
    S_G: float = 3.9          # G logit sd when covered (A blind G-ref, the gold-seed card: 3.91)
    FE_G: float = 0.25        # share of G's own latent shared by edge
    R_GB: float = 0.06        # G–T-rows item correlation (A blind 0.063)
    CL: float = 1.0           # coverage logit sd per person
    HS: float = -1.0          # coverage shift on homonym-end slots
    G_ON_WRONG: float = 0.05  # G's success on a wrong-seed card
    SCH: float = 0.0          # chapter effect sd on baseline and G logits (sensitivity only)


M1 = Model()
STAGE0_SPREAD = replace(M1, S_B=2.6, R_RC=0.74, S_G=2.6, R_GB=0.26)   # stage-0 GEN fits (sensitivity)


def expit(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


def logit(p):
    return math.log(p / (1 - p))


_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(80)
_GH_W = _GH_W / _GH_W.sum()


def mean_match(target: float, sd: float) -> float:
    """mu such that E[expit(mu + sd·Z)] = target, Z standard normal."""
    lo, hi = -40.0, 40.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if float(expit(mid + sd * _GH_X) @ _GH_W) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


class Pool:
    """Design matrices of a slot pool (list of dicts with stratum, chapter, x, y, edges, homonym)."""

    def __init__(self, slots: list[dict]):
        self.slots = slots
        self.n = len(slots)
        edges = sorted({e for s in slots for e in s["edges"]})
        persons = sorted({p for s in slots for p in (s["x"], s["y"])})
        self.M_EDGE = np.zeros((self.n, len(edges)))
        self.M_PERS = np.zeros((self.n, len(persons)))
        for i, s in enumerate(slots):
            for e in s["edges"]:
                self.M_EDGE[i, edges.index(e)] = 1 / math.sqrt(len(s["edges"]))
            self.M_PERS[i, persons.index(s["x"])] = 0.5
            self.M_PERS[i, persons.index(s["y"])] = 0.5
        self.STRAT = np.array([STRATA.index(s["stratum"]) for s in slots])
        self.CH = np.array([0 if s["chapter"] == 5 else 1 for s in slots])
        self.HOM = np.array([bool(s["homonym"]) for s in slots])

    def allocation(self, n: int) -> list[int]:
        """Proportional stratum counts for n slots (largest remainder, ties by stratum order)."""
        N = np.bincount(self.STRAT, minlength=len(STRATA))
        q = n * N / N.sum()
        fl = np.floor(q).astype(int)
        rem = q - fl
        for k in sorted(range(len(STRATA)), key=lambda k: (-round(rem[k], 9), k))[: n - fl.sum()]:
            fl[k] += 1
        return fl.tolist()

    def draw_sets(self, g, k: int, alloc) -> np.ndarray:
        """(k, n) slot indices: a stratified random subset per world (the whole pool when alloc covers it)."""
        alloc = list(alloc)
        if sum(alloc) >= self.n:
            return np.tile(np.arange(self.n), (k, 1))
        keys = g.random((k, self.n))
        cols = []
        for st, nk in enumerate(alloc):
            idx = np.where(self.STRAT == st)[0]
            cols.append(idx[np.argsort(keys[:, idx], axis=1)[:, :nk]])
        return np.concatenate(cols, 1)


def load_pool(check_sha: bool = True) -> Pool:
    if check_sha and GC.sha256_file(GC.POOL) != POOL_SHA256:
        raise SystemExit(f"{GC.POOL}: sha256 is not {POOL_SHA256[:12]} (prereg §2)")
    return Pool(GC.read_json(GC.POOL)["pool"])


# ---------------------------------------------------------------- the test (replica of ab_stats.sign_flip_p)
_EXACT: dict[int, np.ndarray] = {}
_MC: dict[int, np.ndarray] = {}


def _exact_signs(m: int) -> np.ndarray:
    if m not in _EXACT:
        _EXACT[m] = np.array(list(itertools.product((1, -1), repeat=m)), dtype=np.float32)
    return _EXACT[m]


def _mc_signs(m: int) -> np.ndarray:
    """The 20,000 × m signs ab_stats draws for m non-zero differences: random.Random(seed), perm-major."""
    if m not in _MC:
        u = random.Random(GC.TEST_SEED)
        _MC[m] = np.array([1.0 if u.random() < 0.5 else -1.0 for _ in range(NPERM * m)],
                          dtype=np.float32).reshape(NPERM, m)
    return _MC[m]


def signflip_p(D3: np.ndarray, chunk: int = 400) -> np.ndarray:
    """Two-sided p per row of D3 (k, n), integer-valued 3·d: exactly ab_stats.sign_flip_p(d, seed=20261018)."""
    D3 = np.asarray(D3, dtype=np.float32)
    nz = D3 != 0
    m_row = nz.sum(1)
    p = np.ones(D3.shape[0])
    for m in np.unique(m_row):
        if m == 0:
            continue
        rows = np.where(m_row == m)[0]
        NZ = D3[rows][nz[rows]].reshape(len(rows), m)
        obs = np.abs(NZ.sum(1))
        exact = m <= EXACT_MAX
        S = _exact_signs(m) if exact else _mc_signs(m)
        for c in range(0, len(rows), chunk):
            hits = (np.abs(NZ[c:c + chunk] @ S.T) >= obs[c:c + chunk, None]).sum(1)
            p[rows[c:c + chunk]] = hits / S.shape[0] if exact else (hits + 1) / (NPERM + 1)
    return p


# ---------------------------------------------------------------- the model
def _unit_field(g, P: Pool, k: int, fe: float) -> np.ndarray:
    out = math.sqrt(1 - fe) * g.normal(0, 1, (k, P.n))
    if fe > 0:
        out += math.sqrt(fe) * (g.normal(0, 1, (k, P.M_EDGE.shape[1])) @ P.M_EDGE.T)
    return out


def _coverage(g, P: Pool, k: int, a: float, M: Model, cols=None) -> np.ndarray:
    """Per-slot coverage probabilities whose mean over ``cols`` (default: the whole pool) is a in every world."""
    lin = (g.normal(0, M.CL, (k, P.M_PERS.shape[1])) @ P.M_PERS.T if M.CL > 0 else np.zeros((k, P.n)))
    lin = lin + M.HS * P.HOM[None, :]
    sub_ = lin if cols is None else lin[:, cols]
    lo, hi = np.full(k, -20.0), np.full(k, 20.0)
    for _ in range(60):
        mid = (lo + hi) / 2
        mm = expit(mid[:, None] + sub_).mean(1)
        lo, hi = np.where(mm < a, mid, lo), np.where(mm >= a, mid, hi)
    return expit(((lo + hi) / 2)[:, None] + lin)


def outcomes(g, P: Pool, k: int, sets: np.ndarray, a: float, h: float, pR: float, pC: float, w: float,
             M: Model, cols=None) -> tuple[np.ndarray, np.ndarray]:
    """(D1, D2): 3·d for H1 (G − B0) and H2 (G − T-rows), shape (k, n), on the given slot sets.
    With ``cols`` (a fixed slot set), coverage is centred on those slots, so the coverage and the
    wrong-card mass on the evaluated set are a and w."""
    muR, muC, muG = mean_match(pR, M.S_B), mean_match(pC, M.S_B), mean_match(h, M.S_G)
    ZB = _unit_field(g, P, k, M.FE_B)
    ZC = M.R_RC * ZB + math.sqrt(1 - M.R_RC ** 2) * g.normal(0, 1, (k, P.n))
    ZG = M.R_GB * ZB + math.sqrt(1 - M.R_GB ** 2) * _unit_field(g, P, k, M.FE_G)
    chB = chG = 0.0
    if M.SCH > 0:
        chB = g.normal(0, M.SCH, (k, 2))[:, P.CH]
        chG = g.normal(0, M.SCH, (k, 2))[:, P.CH]
    pr, pc = expit(muR + M.S_B * ZB + chB), expit(muC + M.S_B * ZC + chB)
    pg = expit(muG + M.S_G * ZG + chG)
    ok = g.random((k, P.n)) < _coverage(g, P, k, a, M, cols)
    wrong = (~ok) & (g.random((k, P.n)) < min(w / max(1 - a, 1e-9), 1.0))
    pg_eff = np.where(ok, pg, np.where(wrong, M.G_ON_WRONG, 0.0))
    kG, kR, kC = g.binomial(3, pg_eff), g.binomial(3, pr), g.binomial(3, pc)
    fired = ok | wrong
    D1, D2 = np.where(fired, kG - kC, 0), np.where(fired, kG - kR, 0)
    take = lambda X: np.take_along_axis(X, sets, 1).astype(np.float32)  # noqa: E731
    return take(D1), take(D2)


def power(P: Pool, alloc=None, slot_idx=None, nsim: int = NSIM, seed: int = GC.POWER_SEED, M: Model = M1,
          w: float = W_FLOOR, **inputs) -> dict:
    """pow_H1 and pow_H1_and_H2 at the (ii) inputs overridden by ``inputs`` (a, h, pR, pC).
    The set is either fixed slots (``slot_idx``, sorted ascending as the analysis passes d) or a stratified
    random subset per world (``alloc``)."""
    p = {**II, **inputs}
    if slot_idx is not None:
        raw = np.asarray(slot_idx, dtype=int)
        slot_idx = np.unique(raw)
        if len(slot_idx) != len(raw) or slot_idx.min() < 0 or slot_idx.max() >= P.n:
            raise ValueError("slot_idx must be distinct pool indices")
    g = np.random.default_rng(seed)
    h1s, h2s, m1, m2 = [], [], [], []
    for st in range(0, nsim, CHUNK):
        k = min(CHUNK, nsim - st)
        if slot_idx is not None:
            sets = np.tile(np.asarray(slot_idx), (k, 1))
        else:
            sets = P.draw_sets(g, k, alloc if alloc is not None else P.allocation(P.n))
        D1, D2 = outcomes(g, P, k, sets, p["a"], p["h"], p["pR"], p["pC"], w, M, cols=slot_idx)
        n = D1.shape[1]
        h1 = (signflip_p(D1) < ALPHA) & (D1.sum(1) >= FLOOR3 * n - 3e-9)
        h2 = h1 & (signflip_p(D2) < ALPHA) & (D2.sum(1) >= FLOOR3 * n - 3e-9)
        h1s.append(h1); h2s.append(h2); m1.append(D1.mean(1) / 3); m2.append(D2.mean(1) / 3)  # noqa: E702
    both = np.concatenate(h2s)
    return dict(n=int(n), **{k_: round(v, 4) for k_, v in p.items()}, w=w, nsim=nsim,
                pow_H1=round(float(np.concatenate(h1s).mean()), 4), pow_H1_and_H2=round(float(both.mean()), 4),
                mc_se=round(float(np.sqrt(both.mean() * (1 - both.mean()) / nsim)), 4),
                mean_d1=round(float(np.concatenate(m1).mean()), 3), mean_d2=round(float(np.concatenate(m2).mean()), 3))


def gate(P: Pool, a_meas: float, w_meas: float, alloc=None, slot_idx=None) -> dict:
    """The frozen gate (prereg §5.6, §7.5): M1, nsim 10,000, seed 20261018, a = min(a_meas, 0.875),
    w = max(w_meas, 0.05), the other inputs at (ii). Pass iff pow_H1_and_H2 ≥ 0.70 (hard cutoff)."""
    out = power(P, alloc=alloc, slot_idx=slot_idx, a=min(a_meas, A_CAP), w=max(w_meas, W_FLOOR))
    return {**out, "pass": out["pow_H1_and_H2"] >= TARGET}


def g1(P: Pool, r_card: int, r_wrong: int, n_valid: int, n: int = 53) -> dict:
    """G1 (prereg §5.6) and, with n from ``kp_n``, K-P (§8.1): the gate at the P2 point estimates
    a = R_card / n_valid, w = max(R_wrong / n_valid, 0.05), on a proportional stratified set of n slots."""
    return gate(P, r_card / n_valid, r_wrong / n_valid, alloc=P.allocation(n))


def kp_n(passed: int, opened: int, n_target: int) -> int:
    """K-P's projected frozen n: round-half-up(min(passed / opened, 0.914) × n_target), in exact fractions."""
    r = min(Fraction(passed, opened), Fraction(914, 1000))
    return math.floor(r * n_target + Fraction(1, 2))


# ---------------------------------------------------------------- false-positive check (H2-type null)
def type_one(P: Pool, n: int, kind: str = "sharp", size: float = 0.0, centre: str = "pool", nsim: int = NSIM,
             seed: int = 20261019, M: Model = M1, a: float = II["a"], w: float = W_FLOOR) -> dict:
    """Rejection rate of the H2 step when G and T-rows have equal pool mean on the fired slots.
    kind: sharp (no effect anywhere), edge / edge+slot / person (shared slot effects), hom / F5
    (one group negative); centre="pool" centres every world on the pool, "none" only on average."""
    g = np.random.default_rng(seed)
    muR = mean_match(II["pR"], M.S_B)
    rej, clm = [], []
    for st in range(0, nsim, CHUNK):
        k = min(CHUNK, nsim - st)
        pr = expit(muR + M.S_B * _unit_field(g, P, k, M.FE_B))
        ok = g.random((k, P.n)) < _coverage(g, P, k, a, M)
        fired = ok | ((~ok) & (g.random((k, P.n)) < min(w / (1 - a), 1.0)))
        if kind == "sharp":
            pg = pr
        else:
            if kind == "edge":
                tau = size * (g.normal(0, 1, (k, P.M_EDGE.shape[1])) @ P.M_EDGE.T)
            elif kind == "edge+slot":
                tau = size * _unit_field(g, P, k, 0.5)
            elif kind == "person":
                tau = size * math.sqrt(2) * (g.normal(0, 1, (k, P.M_PERS.shape[1])) @ P.M_PERS.T)
            elif kind == "hom":
                tau = np.broadcast_to(np.where(P.HOM, -size, 0.0), (k, P.n))
            elif kind == "F5":
                tau = np.broadcast_to(np.where(P.STRAT >= 2, -size, 0.0), (k, P.n))
            else:
                raise ValueError(kind)
            f = lambda c: np.clip(pr + tau + c[:, None], 0, 1)  # noqa: E731
            c = np.zeros(k)
            if centre == "pool":
                lo, hi = np.full(k, -2.0), np.full(k, 2.0)
                for _ in range(60):
                    c = (lo + hi) / 2
                    mm = (fired * (f(c) - pr)).sum(1)
                    lo, hi = np.where(mm < 0, c, lo), np.where(mm >= 0, c, hi)
            pg = f(c)
        D = np.where(fired, g.binomial(3, pg) - g.binomial(3, pr), 0).astype(np.float32)
        D = np.take_along_axis(D, P.draw_sets(g, k, P.allocation(n)), 1)
        pv = signflip_p(D)
        rej.append(pv < ALPHA)
        clm.append((pv < ALPHA) & (D.sum(1) >= FLOOR3 * n - 3e-9))
    R, C = np.concatenate(rej), np.concatenate(clm)
    return dict(n=n, kind=kind, size=size, centre=centre, nsim=nsim,
                two_sided=round(float(R.mean()), 4), claim=round(float(C.mean()), 4))


# ---------------------------------------------------------------- tables (prereg §5.6, §7)
N_GRID = (58, 53, 48, 44, 40, 36, 32)
CORNERS = (("ii", {}), ("pR.65", dict(pR=0.65)), ("h.80", dict(h=0.80)), ("a.80", dict(a=0.80)),
           ("pR.65+a.80", dict(pR=0.65, a=0.80)), ("h.80+a.80", dict(h=0.80, a=0.80)),
           ("pR.65+h.80", dict(pR=0.65, h=0.80)), ("all3", dict(pR=0.65, h=0.80, a=0.80)))
A_GRID = tuple(round(0.5 + 0.025 * i, 3) for i in range(16))     # 0.500 … 0.875
P2_POSITIVES, N_PLAN = 50, 53
W_GRID = (0.05, 0.06, 0.07, 0.08, 0.10)


def amin(P: Pool, n: int, w: float) -> float | None:
    for a in A_GRID:
        if gate(P, a, w, alloc=P.allocation(n))["pass"]:
            return a
    return None


def g1_threshold(P: Pool, r_wrong: int, n_valid: int = P2_POSITIVES, n: int = N_PLAN) -> int | None:
    """Smallest R_card (of n_valid P2 positives) that passes g1 at n slots for this R_wrong."""
    for k in range(25, n_valid - r_wrong + 1):
        if g1(P, k, r_wrong, n_valid, n=n)["pass"]:
            return k
    return None


def ka_threshold(P: Pool, n: int, wrong: int) -> int | None:
    """Smallest covered count (of n frozen questions) with ``wrong`` wrong cards that passes K-a, on a
    proportional set of n slots (the real K-a uses the frozen slots themselves)."""
    for c in range(n // 2, n - wrong + 1):
        if gate(P, c / n, wrong / n, alloc=P.allocation(n))["pass"]:
            return c
    return None


def p_g1_pass(thresholds: dict[int, int | None], a: float, w: float, n_valid: int = P2_POSITIVES) -> float:
    """P(count of carded >= thresholds[count of wrong]) when each of n_valid items is carded with prob a and
    wrong with prob w, independently (G1 on P2 positives; also K-a on frozen questions)."""
    tot = 0.0
    for rw in range(n_valid + 1):
        thr = thresholds.get(rw)
        if thr is None:
            continue
        for rc in range(thr, n_valid - rw + 1):
            ra = n_valid - rc - rw
            tot += (math.factorial(n_valid) / (math.factorial(rc) * math.factorial(rw) * math.factorial(ra))
                    * a ** rc * w ** rw * (1 - a - w) ** ra)
    return tot


KP_OPENED, KP_TARGET = GC.PILOT, 58                # pilot slots opened; n_target at full budget


def passing_chance(P: Pool, thr53: dict[int, int | None], a: float, w: float, r_pilot: float,
                   thr_by_n: dict[int, dict[int, int | None]], ka_thr: dict[int, int | None]) -> dict:
    """Descriptive (prereg §7.3): P(G1 and K-P pass), P(K-a passes) and the power at the true w, all at
    n_target 58, treating P2, pilot and frozen-question counts as independent binomials."""
    p_g1_kp = 0.0
    for k in range(KP_OPENED + 1):
        n = kp_n(k, KP_OPENED, KP_TARGET) if k else 0
        pk = math.comb(KP_OPENED, k) * r_pilot ** k * (1 - r_pilot) ** (KP_OPENED - k)
        tn = thr_by_n.get(n, {})
        both = {rw: max(t, tn[rw]) for rw, t in thr53.items() if t is not None and tn.get(rw) is not None}
        p_g1_kp += pk * p_g1_pass(both, a, w)
    p_ka = p_g1_pass(ka_thr, a, w, n_valid=N_PLAN)
    pw = power(P, alloc=P.allocation(N_PLAN), a=a, w=w)["pow_H1_and_H2"]
    return dict(a=a, w=w, r_pilot=r_pilot, p_g1_and_kp=round(p_g1_kp, 4), p_ka=round(p_ka, 4), power_true_w=pw,
                product=round(p_g1_kp * p_ka * pw, 4))


def tables(P: Pool) -> dict:
    out: dict = {"model": M1.__dict__, "ii": II, "numpy": np.__version__, "corners": [], "amin": {}, "g1": {},
                 "p_g1_pass": {}, "variants": [], "smallest_n_ii": None, "break_even": {}, "type_one": []}
    for n in N_GRID:
        for tag, kw in CORNERS:
            out["corners"].append({"tag": tag, **power(P, alloc=P.allocation(n), **kw)})
    for n in range(20, 59):
        if power(P, alloc=P.allocation(n))["pow_H1_and_H2"] >= TARGET:
            out["smallest_n_ii"] = n
            break
    for n in (58, 53):
        out["break_even"][f"h_n{n}"] = next((h for h in np.arange(0.875, 0.70, -0.005).round(3)
                                              if power(P, alloc=P.allocation(n), h=float(h))["pow_H1_and_H2"] < TARGET), None)
        out["break_even"][f"pR_n{n}"] = next((r for r in np.arange(0.565, 0.80, 0.005).round(3)
                                               if power(P, alloc=P.allocation(n), pR=float(r))["pow_H1_and_H2"] < TARGET), None)
    for w in W_GRID:
        out["amin"][f"w{w:.2f}"] = {n: amin(P, n, w) for n in N_GRID}
    thr = {}
    for rw in range(8):
        thr[rw] = g1_threshold(P, rw)
        out["g1"][f"R_wrong={rw}"] = thr[rw]
    for a in (0.875, 0.80):
        for w in (0.0, 0.02, 0.05):
            out["p_g1_pass"][f"a{a}_w{w}"] = round(p_g1_pass(thr, a, w), 4)
    kp_ns = sorted({kp_n(k, KP_OPENED, KP_TARGET) for k in range(1, KP_OPENED + 1)} - {N_PLAN}, reverse=True)
    thr_by_n = {N_PLAN: thr}
    for n in kp_ns:
        thr_by_n[n] = {}
        if not gate(P, A_CAP, W_FLOOR, alloc=P.allocation(n))["pass"]:      # no a <= 0.875 reaches 0.70
            thr_by_n[n] = {rw: None for rw in range(8)}
            continue
        for rw in range(8):
            thr_by_n[n][rw] = g1_threshold(P, rw, n=n) if (rw == 0 or thr_by_n[n][rw - 1] is not None) else None
    out["kp_thresholds"] = {str(n): t for n, t in thr_by_n.items()}
    ka_thr = {}
    for wr in range(8):
        ka_thr[wr] = ka_threshold(P, N_PLAN, wr) if (wr == 0 or ka_thr[wr - 1] is not None) else None
    out["ka_thresholds_n53"] = ka_thr
    out["passing_chance"] = [passing_chance(P, thr, 0.875, w, r, thr_by_n, ka_thr)
                             for w in (0.0, 0.02, 0.05) for r in (1.0, 0.914, 0.80)]
    variants = (("chapter sd 0.25", replace(M1, SCH=0.25), {}), ("chapter sd 0.5", replace(M1, SCH=0.5), {}),
                ("chapter sd 0.5 + h .80", replace(M1, SCH=0.5), dict(h=0.80)),
                ("stage-0 spread (sd 2.6)", STAGE0_SPREAD, {}),
                ("G on wrong 0.25", replace(M1, G_ON_WRONG=0.25), {}),
                ("coverage i.i.d.", replace(M1, CL=0.0, HS=0.0), {}),
                ("G–T-rows corr 0.26", replace(M1, R_GB=0.26), {}),
                ("w 0.10", M1, dict(w=0.10)), ("w 0.15", M1, dict(w=0.15)),
                ("(ii) from F1/F5 dev items only", M1, dict(h=0.855, pR=0.44, pC=0.363)))
    for tag, M, kw in variants:
        for n in (58, 53, 48):
            out["variants"].append({"tag": tag, **power(P, alloc=P.allocation(n), M=M, **kw)})
    for n in (58, 48):
        out["type_one"].append(type_one(P, n))
        for kind, size in (("edge", 0.10), ("edge", 0.20), ("edge+slot", 0.20), ("edge+slot", 0.40),
                           ("person", 0.20), ("hom", 0.60), ("F5", 0.30)):
            out["type_one"].append(type_one(P, n, kind, size))
        for kind, size in (("edge", 0.20), ("edge+slot", 0.30)):
            out["type_one"].append(type_one(P, n, kind, size, centre="none"))
    return out


def main(argv: list[str]) -> int:
    P = load_pool()
    res = tables(P)
    res["power_g_sha256"] = GC.sha256_file(__file__)
    res["pool_sha256"] = POOL_SHA256
    path = GC.write_json(GC.OUT_ROOT / "power/power_g_tables.json", res)
    print("wrote", path, GC.sha256_file(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

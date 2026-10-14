"""Unit-level V1 operating characteristic and procedure power of the GD experiment (prereg §6,
one item of 附錄 A). Pure simulation: no arms, lists, scores or encodings of any set.

prereg.md in this directory is the only spec; § numbers refer to it. §6 quotes the V1
operating characteristic (OC) and the procedure power of the question-level stop rule
(X/x_metrics/recheck.py, R/review_stats/s2_power.py) and asks for the unit-level version
"在附錄 A 以同法重算". This script ports s2_power.py's method:

* a question's GD−C@10 difference d is 0 with probability 1−r, else ±|d| (+ with probability
  pw), |d| drawn from the 14 NEW82 non-zero values of R/review_stats/s1_strata.json;
* OLD31's units are the gold-only union-find units (evaluate.py units; §2 allows it), sizes in
  descending order (s2_power.OLD_SIZES), filled with consecutive draws; a unit's value is the
  mean of its questions' d, integer-scaled by SCALE; HO is N_HO singletons (§5 預期每題自成一群);
* E2 is the two-sided exact sign-flip on the OLD31 ∪ HO unit values.

Two changes, both from the prereg text: V1 stops on units (≥3 discordant units and losses ≥
wins, §6 停損; s2_power stopped on questions), and E2 rejects at p < 0.05 with Σv > 0 (§5 H1;
s2_power used p ≤ 0.05). The unit-level OC is simulated (unit signs depend on |d|); the
question-level OC stays analytic (recheck.py). Before anything is reported the port must
reproduce the archive: with the question-level rule and p ≤ thresholds the procedure
simulation equals s2_power.json exactly, and the question-level OC equals recheck.json at 3
decimals; otherwise IntegrityError.

    v1_power.py [--out v1_power.json]

Writes {"meta", "spec", "inputs", "reproduction", "v1_oc", "procedure"}. Errors exit 2 with
one line.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _eval_report as R  # noqa: E402
import _eval_stats as st  # noqa: E402
import gd_common as gd  # noqa: E402

S1_STRATA = gd.R_STATS / "s1_strata.json"
S2_POWER = gd.R_STATS / "s2_power.json"
RECHECK = gd.X_METRICS / "recheck.json"
PINS = {S1_STRATA: "d252d791cb78aa4bb49fddba213c43b9bd9869054ea2951b3b0c3426b96b0399",
        S2_POWER: "c92142f1b52e9ecde7edcb6ea94d603988569f03d226ce4bc633df3afd54551b",
        RECHECK: "db71ab8cb433d49555f3d1dabe60f7754f6378220bd299e21da1a4e1aba4dd85",
        gd.R_STATS / "s2_power.py": "06e90b5e3146431309eb3b47ad1df94ac9d71e61f1c158481a8dcbca5775fe26",
        gd.X_METRICS / "recheck.py": "20c9e33526f5e8d299d8de69765d692f1c17c22569cfc90de38786ccb07190dc"}
SOURCE_FILES = {"v1_power.py": Path(__file__).resolve(),
                **{n: _HERE / n for n in ("_eval_report.py", "_eval_metrics.py", "_eval_stats.py",
                                          "_score_w.py", "_score_io.py")},
                "src/__init__.py": Path(st._ab_stats.__file__).resolve().parent / "__init__.py",
                "src/ab_stats.py": Path(st._ab_stats.__file__).resolve()}
OUT = _HERE / "v1_power.json"

SCALE = 1080                 # s2_power.SCALE: lcm of hop denominators × unit sizes
N_HO = 120                   # §7 N
ALPHA = 0.05                 # §5 H1
V1_MIN_DISCORDANT = 3        # §6 停損: ≥3 discordant (and losses ≥ wins)
SIM_REPS, SIM_SEED = 4000, 1                 # s2_power.sim defaults
OC_REPS, OC_SEED = 200_000, 20261014         # unit-level OC simulation (§5 seed)
OLD_RATIO = 0.222 / 0.171                    # s2_power: r_old = min(0.9, r_ho · 0.222 / 0.171)
R_OLD_CAP = 0.9
SCENARIOS = ((0.17, 0.5), (0.17, 0.75), (0.17, 0.8), (0.17, 0.85), (0.12, 0.8), (0.12, 0.85),
             (0.22, 0.8))                    # s2_power procedure_sim (r_ho, pw)
OC_R = (0.10, 13 / 82, 14 / 82, 14 / 63, 0.25)   # recheck.py V1_stop_rule_OC_n31
OC_PW = (0.5, 0.7, 0.8, 0.85)
OC_KEYS = ("P_stop(d>=3,l>=w)", "P_d<3_and_l>w(rule silent)")
ARCHIVE_PROC_KEY = "procedure_sim(R=4000)"
ARCHIVE_OC_KEY = "V1_stop_rule_OC_n31"


# ------------------------------------------------------------------ inputs

def _pinned_json(path: Path) -> Any:
    return json.loads(gd.read_pinned(path, PINS[path]).decode("utf-8"))


def magnitudes(strata: Mapping[str, Any]) -> np.ndarray:
    """|d| pool: the NEW82 GD−C@10 non-zero question differences (s2_power.MAG)."""
    return np.array([abs(v) for v in strata["k10"]["d_values_nonzero"].values()])


def old31_sizes(strata: Mapping[str, Any]) -> list[int]:
    """OLD31 unit sizes from the current gold-only unit table, descending; must equal the
    archived table (s1_strata OLD31_clusters, §5: 20 單位、最大 9 題)."""
    table = R.unit_table(R.items_of(gd.load_question_set("old31"), gold_only=True))
    sizes = sorted((len(u) for u in table["units"]), reverse=True)
    gd.expect("OLD31 unit sizes vs s1_strata.json", sizes, strata["OLD31_clusters"]["sizes"])
    return sizes


# ------------------------------------------------------------------ s2_power port

def exact_p_int(vals: Sequence[int]) -> float:
    """Two-sided exact sign-flip p of integer unit values (zeros dropped); s2_power verbatim."""
    v = np.abs(np.asarray([x for x in vals if x != 0], dtype=np.int64))
    if v.size == 0:
        return 1.0
    T = abs(int(np.sum(vals)))
    tot = int(v.sum())
    dist = np.zeros(2 * tot + 1, dtype=np.float64)
    dist[tot] = 1.0
    for a in v:
        nd = np.zeros_like(dist)
        nd[a:] += dist[:-a] if a else dist
        nd[:-a] += dist[a:] if a else dist
        dist = nd * 0.5
    s = np.arange(-tot, tot + 1)
    return float(dist[np.abs(s) >= T].sum())


def draw_q(rng: np.random.Generator, r: float, pw: float, n: int, mag: np.ndarray) -> np.ndarray:
    """n question differences; s2_power.draw_q (same draw order)."""
    disc = rng.random(n) < r
    sign = np.where(rng.random(n) < pw, 1, -1)
    m = rng.choice(mag, n)
    return np.where(disc, sign * m, 0.0)


def scaled_units(dq: np.ndarray, sizes: Sequence[int]) -> list[int]:
    """Consecutive slices of dq as units: round(mean · SCALE)."""
    out, i = [], 0
    for s in sizes:
        out.append(int(round(dq[i:i + s].mean() * SCALE)))
        i += s
    return out


def stops(values: Sequence[float]) -> bool:
    """§6 停損 on these values (questions or units): ≥3 non-zero and losses ≥ wins. Python
    ints and bool, as s2_power (numpy scalars would round counts / reps half-to-even)."""
    w = int(sum(bool(v > 0) for v in values))
    los = int(sum(bool(v < 0) for v in values))
    return bool(w + los >= V1_MIN_DISCORDANT and los >= w)


def r_old_of(r_ho: float) -> float:
    return min(R_OLD_CAP, r_ho * OLD_RATIO)


def simulate(r_ho: float, pw: float, sizes: Sequence[int], mag: np.ndarray,
             tally: Callable[[dict, bool, bool, float, bool], None], keys: Sequence[str],
             reps: int = SIM_REPS, seed: int = SIM_SEED) -> dict[str, float]:
    """s2_power.sim's loop: per rep OLD31 draws, then HO draws; `tally` counts the outcome
    from (counts, question stop, unit stop, p, Σv > 0). Returns each count / reps (3 dp)."""
    rng = np.random.default_rng(seed)
    n_old = sum(sizes)
    counts = dict.fromkeys(keys, 0)
    for _ in range(reps):
        dq = draw_q(rng, r_old_of(r_ho), pw, n_old, mag)
        units = scaled_units(dq, sizes)
        dh = draw_q(rng, r_ho, pw, N_HO, mag)
        units += [int(round(x * SCALE)) for x in dh]
        tally(counts, stops(dq), stops(units[:len(sizes)]), exact_p_int(units), bool(sum(units) > 0))
    return {k: round(v / reps, 3) for k, v in counts.items()}


ARCHIVE_KEYS = ("stop", "rej05_nofut", "rej025_nofut", "rej05", "rej025")
PREREG_KEYS = ("stop", "reject_nofut", "reject", "stop_question_rule", "reject_question_rule")


def archive_tally(c: dict, q_stop: bool, _u_stop: bool, p: float, pos: bool) -> None:
    """s2_power's counts: question-level stop, p ≤ 0.05 / 0.025."""
    c["stop"] += q_stop
    c["rej05_nofut"] += p <= 0.05 and pos
    c["rej025_nofut"] += p <= 0.025 and pos
    c["rej05"] += p <= 0.05 and pos and not q_stop
    c["rej025"] += p <= 0.025 and pos and not q_stop


def prereg_tally(c: dict, q_stop: bool, u_stop: bool, p: float, pos: bool) -> None:
    """The prereg's rules: unit-level V1 stop, E2 p < ALPHA with Σv > 0; the question-level
    stop of the same draws for comparison."""
    rej = p < ALPHA and pos
    c["stop"] += u_stop
    c["reject_nofut"] += rej
    c["reject"] += rej and not u_stop
    c["stop_question_rule"] += q_stop
    c["reject_question_rule"] += rej and not q_stop


def scenario_key(r_ho: float, pw: float) -> str:
    return f"r_ho={r_ho},r_old={r_old_of(r_ho):.3f},pw={pw}"


# ------------------------------------------------------------------ V1 operating characteristic

def _binom(n: int, k: int, p: float) -> float:
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)


def question_oc(n: int, r: float, pw: float) -> dict[str, float]:
    """recheck.py's analytic OC of the question-level rule on n questions."""
    stop = silent = 0.0
    for d in range(n + 1):
        pd = _binom(n, d, r)
        for w in range(d + 1):
            los, pr = d - w, pd * _binom(d, w, pw)
            stop += pr if d >= V1_MIN_DISCORDANT and los >= w else 0.0
            silent += pr if d < V1_MIN_DISCORDANT and los > w else 0.0
    return {OC_KEYS[0]: round(stop, 3), OC_KEYS[1]: round(silent, 3)}


def unit_oc(sizes: Sequence[int], r: float, pw: float, mag: np.ndarray,
            reps: int = OC_REPS, seed: int = OC_SEED) -> dict[str, float]:
    """Simulated OC of the unit-level rule: unit value = mean of its questions' draw_q d."""
    rng = np.random.default_rng(seed)
    n = sum(sizes)
    disc = rng.random((reps, n)) < r
    sign = np.where(rng.random((reps, n)) < pw, 1, -1)
    dq = np.where(disc, sign * rng.choice(mag, (reps, n)), 0.0)
    bounds = np.cumsum([0, *sizes])
    units = np.stack([np.rint(dq[:, a:b].mean(axis=1) * SCALE) for a, b in zip(bounds, bounds[1:])],
                     axis=1)
    w, los = (units > 0).sum(axis=1), (units < 0).sum(axis=1)
    stop = (w + los >= V1_MIN_DISCORDANT) & (los >= w)
    silent = (w + los < V1_MIN_DISCORDANT) & (los > w)
    return {OC_KEYS[0]: round(float(stop.mean()), 3), OC_KEYS[1]: round(float(silent.mean()), 3)}


def oc_key(r: float, pw: float) -> str:
    return f"r={r:.3f},pwin={pw}"


# ------------------------------------------------------------------ run

def reproduce(sizes: Sequence[int], mag: np.ndarray, s2: Mapping[str, Any],
              recheck: Mapping[str, Any]) -> dict[str, Any]:
    """The port against the archive; any difference raises IntegrityError."""
    proc = {scenario_key(r, pw): simulate(r, pw, sizes, mag, archive_tally, ARCHIVE_KEYS)
            for r, pw in SCENARIOS}
    gd.expect("question-rule procedure simulation vs s2_power.json", proc, s2[ARCHIVE_PROC_KEY])
    oc = {oc_key(r, pw): question_oc(sum(sizes), r, pw) for r in OC_R for pw in OC_PW}
    gd.expect("question-rule V1 OC vs recheck.json", oc, recheck[ARCHIVE_OC_KEY])
    return {"procedure_sim_equals_s2_power": True, "question_oc_equals_recheck": True,
            "scenarios": len(proc), "oc_cells": len(oc)}


def run() -> dict[str, Any]:
    strata, s2, recheck = (_pinned_json(p) for p in (S1_STRATA, S2_POWER, RECHECK))
    mag, sizes = magnitudes(strata), old31_sizes(strata)
    reproduction = reproduce(sizes, mag, s2, recheck)
    oc = {oc_key(r, pw): {"unit": unit_oc(sizes, r, pw, mag), "question": question_oc(sum(sizes), r, pw)}
          for r in OC_R for pw in OC_PW}
    proc = {scenario_key(r, pw): simulate(r, pw, sizes, mag, prereg_tally, PREREG_KEYS)
            for r, pw in SCENARIOS}
    return {"meta": gd.collect_meta({**SOURCE_FILES, **{p.name: p for p in PINS}},
                                    script="v1_power.py"),
            "spec": {"stop": "§6: 單位層級不一致 ≥3 且負 ≥勝", "reject": "§5 H1: p<0.05 且 Σv>0",
                     "method": "R/review_stats/s2_power.py (port), X/x_metrics/recheck.py",
                     "scale": SCALE, "n_ho": N_HO, "sim": {"reps": SIM_REPS, "seed": SIM_SEED},
                     "oc": {"reps": OC_REPS, "seed": OC_SEED}, "r_old": "min(0.9, r_ho·0.222/0.171)"},
            "inputs": {"old31_unit_sizes": sizes, "n_old31": sum(sizes),
                       "magnitudes": [float(x) for x in mag]},
            "reproduction": reproduction, "v1_oc": oc, "procedure": proc}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    doc = run()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cell = doc["procedure"][scenario_key(0.17, 0.8)]
    print(f"v1_power: reproduction ok; r_ho=0.17 pw=0.8 stop {cell['stop']} reject {cell['reject']} "
          f"-> {a.out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"v1_power.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)

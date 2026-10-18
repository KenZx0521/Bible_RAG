"""Stage-0 verdict of experiment A (prereg §2 K-S0, 描述; §4 措辭) -> d/report.json, report.md.

作廢 first: store A/k0_status.json missing or any of K0_1–K0_3 not pass=true, a missing seed or arm
job, or run_meta options / prompts that do not match the jobs. Then K-S0-1: mean over the dev items
of G-auto − T-rows < +0.22 stops A. K-S0-2: a, h, pR, pC as prereg §2 defines them, each clamped to
[0.01, 0.99] (powerA_strong's logit is undefined at 0 and 1; appendix A.5), gap = pR' − pC', put
into K/synth/powerA_strong.py cell(C=12, m=3, a, h, pR, gap, nsim=500) (module rng seeded at import,
one call); pow_H1_and_H2 < 0.7 stops A. Descriptives: bootstrap 95% CI (10000, seed 20261018) and
item-level sign-flip p from evaluation/src/ab_stats.py. All numbers are 開發集 (dev set).
"""
from __future__ import annotations

import importlib.util
import sys
import warnings

from a_common import (ARMS_JOBS, ARMS_META, EVAL_DIR, OUT, POWER_A, REPORT_JSON, REPORT_MD, SCORES, SEED, cc,
                      prompts_sha256, read_json)
from arms_a import ARMS

sys.path.insert(0, str(EVAL_DIR))
from src import ab_stats  # noqa: E402

GATE_MEAN, GATE_POWER, EPS = 0.22, 0.7, 0.01
K0_KEYS = ("K0_1", "K0_2", "K0_3")
PAIRS = (("G-auto", "T-rows"), ("G-auto", "T-canon"), ("G-auto", "B0"), ("G-ref", "G-auto"))
SUBSETS = {"all": lambda r: True, "natural": lambda r: r["kind"] == "natural",
           "template": lambda r: r["kind"] != "natural"}
STOP, PASS, VOID = "依事先規則停止，不構成無效證據", "開發集通過，請 Kay 授權確認集", "作廢"


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def clamp(p: float) -> float:
    return min(max(p, EPS), 1 - EPS)


def compare(rows: list[dict], a: str, b: str) -> dict:
    d = [r["mean"][a] - r["mean"][b] for r in rows if r["mean"][a] is not None and r["mean"][b] is not None]
    lo, hi = ab_stats.bootstrap_ci(d, n_boot=10000, seed=SEED) if d else (None, None)
    return {"n": len(d), "mean": mean(d), "ci95": [lo, hi], "p_signflip": ab_stats.sign_flip_p(d, seed=SEED) if d else None,
            "W": sum(x > 0 for x in d), "L": sum(x < 0 for x in d), "T": sum(x == 0 for x in d)}


def gate_inputs(rows: dict, meta: dict) -> dict:
    hit = [i for i in rows if meta[i]["a_hit"]]
    a = len(hit) / len(rows)
    h = mean([rows[i]["mean"]["G-auto"] for i in hit])
    pR = mean([r["mean"]["T-rows"] for r in rows.values()])
    pC = mean([r["mean"]["T-canon"] for r in rows.values()])
    hc, pRc, pCc = clamp(h if h is not None else 0.0), clamp(pR), clamp(pC)
    return {"a": a, "h": h, "h_defined": h is not None, "pR": pR, "pC": pC, "gap_raw": pR - pC, "a_items": hit,
            "clamped": {"h": hc, "pR": pRc, "pC": pCc, "gap": pRc - pCc}}


def power(g: dict) -> dict:
    spec = importlib.util.spec_from_file_location("powerA_strong", POWER_A)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = g["clamped"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return mod.cell(C=12, m=3, a=g["a"], h=c["h"], pR=c["pR"], gap=c["gap"], nsim=500)


def call_rates(rows: dict) -> dict:
    out = {}
    for arm in ARMS:
        recs = [v for r in rows.values() for k, v in r["reps"].items()
                if k.startswith(arm + "|") and v and "substituted_from" not in v]
        n = len(recs)
        ans = [v for v in recs if not v["format_fail"]]
        out[arm] = {"n_calls": n, "format_fail": sum(v["format_fail"] for v in recs),
                    "truncated": sum(v["truncated"] for v in recs), "trap": sum(bool(v["trap"]) for v in recs),
                    "wrong": sum(v["score"] == 0 for v in ans), "partial": sum(0 < v["score"] < 1 for v in ans),
                    "wrong_rate": sum(v["score"] == 0 for v in ans) / n if n else None,
                    "format_fail_rate": sum(v["format_fail"] for v in recs) / n if n else None}
    return out


def aux_chars(meta: dict) -> dict:
    out = {}
    for arm in ARMS:
        xs = [m["aux_chars"][arm] for m in meta.values() if m["aux_chars"][arm] is not None]
        out[arm] = {"n": len(xs), "mean": mean(xs), "max": max(xs) if xs else None}
    return out


def descriptives(rows: dict, meta: dict) -> dict:
    strict = [i for i in rows if meta[i].get("a_strict")]
    cov = [i for i in rows if meta[i]["tcanon_basis_covered"]]
    return {"a_strict": len(strict) / len(rows), "a_strict_items": strict,
            "h_strict": mean([rows[i]["mean"]["G-auto"] for i in strict]),
            "tcanon_basis_covered_items": cov, "tcanon_basis_missing": {i: meta[i]["tcanon_basis_missing"]
                                                                       for i in rows if i not in cov},
            "pC_covered": mean([rows[i]["mean"]["T-canon"] for i in cov]),
            "pR_on_tcanon_covered": mean([rows[i]["mean"]["T-rows"] for i in cov]),
            "seed_truncated": sorted(i for i in rows if meta[i].get("seed_truncated")),
            "seed_no_parse": sorted(i for i in rows if not meta[i]["seeds_parsed"])}


def infra_problems(d, sc: dict, k0: dict | None) -> dict:
    prob = {}
    k0_bad = [k for k in K0_KEYS if ((k0 or {}).get(k) or {}).get("pass") is not True]
    if k0_bad:
        prob["k0_not_passed"] = k0_bad if k0 is not None else ["k0_status.json missing"]
    if sc["missing_jobs"] or sc["seeds"]["missing"]:
        prob["missing_jobs"] = sc["missing_jobs"] + [f"A|{i}|seed|1" for i in sc["seeds"]["missing"]]
    rm_a, rm_s = (read_json(d / f"run_meta_{t}.json") if (d / f"run_meta_{t}.json").exists() else None
                  for t in ("arms", "seeds"))
    if rm_a is None or rm_s is None:
        prob["run_meta_missing"] = [t for t, m in (("arms", rm_a), ("seeds", rm_s)) if m is None]
        return prob
    if rm_a["options"] != rm_s["options"]:
        prob["options_differ"] = [rm_s["options"], rm_a["options"]]
    if rm_a["prompts_sha256"] != prompts_sha256(read_json(d / ARMS_JOBS.name)):
        prob["arms_prompts_differ_from_run_meta"] = True
    return prob


def verdict(gm: float, pw: float, prob: dict) -> dict:
    if prob:
        return {"result": VOID, "why": prob}
    stops = [s for s, bad in (("K-S0-1 G-auto−T-rows < +0.22", gm < GATE_MEAN),
                              ("K-S0-2 pow_H1_and_H2 < 0.7", pw < GATE_POWER)) if bad]
    return {"result": STOP if stops else PASS, "stopped_by": stops}


def analyze(d=OUT) -> dict:
    """Reads d/scores.json, d/arms_meta.json, d/run_meta_*.json; writes d/report.json and d/report.md."""
    sc, meta = read_json(d / SCORES.name), read_json(d / ARMS_META.name)
    rows = sc["items"]
    k0_path = OUT / "k0_status.json"
    k0 = read_json(k0_path) if k0_path.exists() else None
    g = gate_inputs(rows, meta)
    pw = power(g)
    main_cmp = compare(list(rows.values()), "G-auto", "T-rows")
    prob = infra_problems(d, sc, k0)
    rep = {"label": "開發集 stage-0（不構成證據）", "n_items": len(rows), "k0_status": k0,
           "gate": {"mean_G_auto_minus_T_rows": main_cmp["mean"], "threshold": GATE_MEAN, **g,
                    "power_cell": pw, "power_threshold": GATE_POWER},
           "verdict": verdict(main_cmp["mean"], pw["pow_H1_and_H2"], prob),
           "arm_means": {s: {a: mean([r["mean"][a] for r in rows.values() if f(r)]) for a in ARMS}
                         for s, f in SUBSETS.items()},
           "pairs": {s: {f"{a}−{b}": compare([r for r in rows.values() if f(r)], a, b) for a, b in PAIRS}
                     for s, f in SUBSETS.items()},
           "calls": call_rates(rows), "aux_chars": aux_chars(meta), "descriptive": descriptives(rows, meta),
           "g_auto_abstain": sorted(i for i, m in meta.items() if not m["g_auto_fired"]),
           "g_ref_abstain": sorted(i for i, m in meta.items() if not m["g_ref_fired"]),
           "missing_jobs": sc["missing_jobs"], "seeds": sc["seeds"], "num_ctx": sc["num_ctx"]}
    cc.write_json(d / REPORT_JSON.name, rep)
    from report_md import write_md
    write_md(rep, d / REPORT_MD.name)
    return rep

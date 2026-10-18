"""Verdict of the confirmation set (confirm_A.md §6.2–6.6) -> store A_confirm/report.json, report.md.

Unit value v_u = unweighted mean over the unit's items of d_q (item value difference; item value =
mean of the arm's 3 reps, G abstention substituted by score_c). Δ̄ = mean of every unit's v_u, units
with v_u = 0 included. Fixed sequence, FWER 0.05: H1 = G-auto − T-canon; H2 = G-auto − T-rows is tested
(and its p reported) only when H1 passes. A step passes when src.ab_stats.sign_flip_p(v_u, seed
20261018) < 0.05 (two-sided; exact when ≤16 non-zero units) AND Δ̄ ≥ +0.10 (1e-9 float tolerance).
p < 0.05 with 0 < Δ̄ < +0.10 is recorded as 「顯著但未達事先定的最小效果」 and handled as not passed;
p < 0.05 with Δ̄ < 0 at H1 appends 「且 G-auto 顯著劣於正典經文窗」. CI = ab_stats.bootstrap_ci(v_u,
10000, seed 20261018). Order of outcomes: 作廢 (infra, guards_c) → pre-registered stops (K1 from
k1.json, K0-1b from k0_status.json, K-U2 = frozen units < 12) → H1/H2. Every sentence comes from
c_common.WORDING (the confirm_A.md §6 table). K3 only appends 「不談 prod」. Everything else is
descriptive (§6.6); p there is description only, and the H2 pair carries no p anywhere (strata,
trap-rule sensitivities, item level) unless H2 was tested.
"""
from __future__ import annotations

import sys
from pathlib import Path

import guards_c as G
from analyze_a import aux_chars, call_rates, compare, descriptives as st0_descriptives
from c_common import (ALPHA, ARMS, ARMS_JOBS, ITEMS, K0_STATUS, K1_JSON, KAY_K0_1B, K3_MAX, KU_MIN, LAYER_AUTO, LAYER_REF,
                      MANIFEST, MIN_DELTA, N_BOOT, OUT, REPORT_JSON, REPORT_MD, SCORES, SEED, WORDING, ac, cc,
                      read_json)

sys.path.insert(0, str(ac.EVAL_DIR))
from src import ab_stats  # noqa: E402

H1, H2 = ("G-auto", "T-canon"), ("G-auto", "T-rows")
DESC_PAIRS = (("G-auto", "B0"), ("G-ref", "G-auto"))
EPS, EXACT_MAX = 1e-9, 16
VOID = "作廢"


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def name(pair) -> str:
    return f"{pair[0]}−{pair[1]}"


def primary(r: dict) -> dict:
    return r["mean"]


def unit_values(rows: dict, a: str, b: str, get=primary) -> dict:
    """{unit: v_u}: unweighted mean of the unit's item differences (items with both values)."""
    by: dict = {}
    for r in rows.values():
        x, y = get(r)[a], get(r)[b]
        if x is not None and y is not None:
            by.setdefault(r["unit"], []).append(x - y)
    return {u: mean(ds) for u, ds in sorted(by.items())}


def unit_test(v: dict, with_p: bool = True) -> dict:
    xs = list(v.values())
    lo, hi = ab_stats.bootstrap_ci(xs, n_boot=N_BOOT, seed=SEED) if xs else (None, None)
    nonzero = sum(abs(x) > EPS for x in xs)
    out = {"n_units": len(xs), "delta": mean(xs), "ci95": [lo, hi], "units": v, "n_nonzero": nonzero,
           "W": sum(x > EPS for x in xs), "L": sum(x < -EPS for x in xs), "T": sum(abs(x) <= EPS for x in xs)}
    if with_p:
        out.update(p=ab_stats.sign_flip_p(xs, seed=SEED) if xs else None, exact=nonzero <= EXACT_MAX)
    return out


def step(t: dict) -> dict:
    sig = t["p"] is not None and t["p"] < ALPHA
    big = t["delta"] is not None and t["delta"] >= MIN_DELTA - EPS
    return {"pass": sig and big, "significant": sig, "sig_small": sig and not big and t["delta"] > 0,
            "negative": sig and t["delta"] < 0}


def fixed_sequence(rows: dict, get=primary) -> dict:
    h1 = {"pair": name(H1), **unit_test(unit_values(rows, *H1, get))}
    h1.update(step(h1))
    if h1["pass"]:
        h2 = {"pair": name(H2), "tested": True, **unit_test(unit_values(rows, *H2, get))}
        h2.update(step(h2))
    else:  # not tested: no p is computed or reported (FWER fixed sequence)
        h2 = {"pair": name(H2), "tested": False, "pass": False,
              **unit_test(unit_values(rows, *H2, get), with_p=False)}
    return {"H1": {"tested": True, **h1}, "H2": h2}


def ci_text(ci) -> str:
    return "—" if ci[0] is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"


def k_u2_stop(n_units: int) -> str | None:
    if n_units < KU_MIN:
        return WORDING["stop"].format(rule="K-U2", value=f"凍結單位 n＝{n_units}<{KU_MIN}", state="未跑")
    return None


def pre_stops(n_units: int, k1: dict | None, k0: dict | None) -> list[dict]:
    out = []
    if k1 and k1.get("stop"):
        out.append({"rule": "K1", "wording": k1["wording"]})
    w = G.k0_1b_stop(k0)
    if w:
        out.append({"rule": "K0-1b", "wording": w})
    w = k_u2_stop(n_units)
    if w:
        out.append({"rule": "K-U2", "wording": w})
    return out


def verdict(seq: dict, problems: dict, stops: list[dict], k3: dict) -> dict:
    """The frozen §6 sentence for this outcome (plus notes that are records, not verdicts)."""
    if problems:
        return {"result": VOID, "why": problems, "wording": VOID}
    if stops:
        return {"result": "stop", "stopped_by": [s["rule"] for s in stops], "wording": stops[0]["wording"],
                "all_stops": stops}
    h1, h2 = seq["H1"], seq["H2"]
    notes = [f"{h['pair']}：{WORDING['h1_sig_small']}" for h in (h1, h2) if h.get("sig_small")]
    if not h1["pass"]:
        dtext = "—" if h1["delta"] is None else f"{h1['delta']:+.3f}"
        w = WORDING["h1_fail"].format(n=h1["n_units"], d=dtext, ci=ci_text(h1["ci95"]))
        result = "H1 未過"
        if h1["negative"]:
            w, result = f"{w}，{WORDING['h1_negative']}", "H1 顯著為負"
    elif not h2["pass"]:
        w, result = WORDING["h1_only"], "H1 過、H2 未過"
    else:
        w, result = f"{WORDING['h1_h2']}；{WORDING['h1_h2_scope']}", "H1、H2 皆過"
    out = {"result": result, "wording": w, "notes": notes}
    if k3["flag"]:
        out["k3_wording"] = WORDING["k3"]
    return out


def item_level(rows: dict, h2_tested: bool) -> dict:
    """Item-level comparisons (descriptive); the H2 pair has no p_signflip unless H2 was tested."""
    out = {}
    for p in (H1, H2) + DESC_PAIRS:
        c = compare(list(rows.values()), *p)
        if p == H2 and not h2_tested:
            c = {k: v for k, v in c.items() if k != "p_signflip"}
        out[name(p)] = c
    return out


def calls_of(rows: dict, arm: str, substituted: bool = True) -> list[dict]:
    return [v for r in rows.values() for k, v in r["reps"].items()
            if k.startswith(arm + "|") and v and (substituted or "substituted_from" not in v)]


def wrong_rate(recs: list[dict]) -> float | None:
    return sum((not v["format_fail"]) and v["score"] == 0 for v in recs) / len(recs) if recs else None


def k3(rows: dict) -> dict:
    """G-auto (substitutes included) − T-canon wrong-answer rate over calls; unit bootstrap CI."""
    rate = {a: wrong_rate(calls_of(rows, a)) for a in ARMS}
    diff = None if rate["G-auto"] is None or rate["T-canon"] is None else rate["G-auto"] - rate["T-canon"]
    by: dict = {}
    for r in rows.values():
        g = wrong_rate([v for k, v in r["reps"].items() if k.startswith("G-auto|") and v])
        c = wrong_rate([v for k, v in r["reps"].items() if k.startswith("T-canon|") and v])
        if g is not None and c is not None:
            by.setdefault(r["unit"], []).append(g - c)
    t = unit_test({u: mean(x) for u, x in sorted(by.items())}, with_p=False)
    return {"rate": rate, "diff": diff, "threshold": K3_MAX, "flag": diff is not None and diff > K3_MAX + EPS,
            "unit_delta": t["delta"], "unit_ci95": t["ci95"], "n_units": t["n_units"]}


def infra_problems(d: Path, sc: dict, k0_path: Path, manifest: Path, files, k1_path: Path,
                   kay_path: Path = KAY_K0_1B) -> dict:
    prob = {}
    for key, bad in (("k0", G.k0_problems(k0_path, kay_path)), ("frozen", G.frozen_problems(manifest, files))):
        if bad:
            prob[key] = bad
    if not Path(k1_path).is_file():
        prob["k1"] = [f"{k1_path} missing"]
    if sc["missing_jobs"] or sc["seeds"]["missing"]:
        prob["missing_jobs"] = sc["missing_jobs"] + [f"A|{i}|seed|1" for i in sc["seeds"]["missing"]]
    metas = {t: read_json(d / f"run_meta_{t}.json") for t in ("arms", "seeds") if (d / f"run_meta_{t}.json").exists()}
    if len(metas) < 2:
        prob["run_meta_missing"] = [t for t in ("arms", "seeds") if t not in metas]
        return prob
    opt = G.options_problems(metas["arms"]["options"]) + G.options_problems(metas["seeds"]["options"])
    if opt:
        prob["options"] = opt
    if metas["arms"]["prompts_sha256"] != ac.prompts_sha256(read_json(d / ARMS_JOBS.name)):
        prob["arms_prompts_differ_from_run_meta"] = True
    want = G.manifest_frozen(manifest)
    expected = {Path(p).name: want.get(Path(p).name) for p in files}
    drift = [t for t, m in metas.items() if m.get("frozen") != expected]
    if drift:
        prob["run_meta_frozen_differs"] = drift
    return prob


def analyze(d: Path = OUT, items_path: Path = ITEMS, k0_path: Path = K0_STATUS, k1_path: Path = K1_JSON,
            manifest: Path = MANIFEST, files=G.FROZEN_FILES, kay_path: Path = KAY_K0_1B) -> dict:
    """Reads d/scores.json, d/arms_meta.json, d/run_meta_*.json; writes d/report.json and d/report.md."""
    from descriptives_c import describe
    from regnal import load_auto, load_ref
    d = Path(d)
    sc, meta = read_json(d / SCORES.name), read_json(d / "arms_meta.json")
    rows = sc["items"]
    k0 = read_json(k0_path) if Path(k0_path).is_file() else None
    k1 = read_json(k1_path) if Path(k1_path).is_file() else None
    seq, harm = fixed_sequence(rows), k3(rows)
    prob = infra_problems(d, sc, k0_path, manifest, files, k1_path, kay_path)
    stops = pre_stops(sc["n_units"], k1, k0)
    items = {it["id"]: it for it in read_json(items_path)["items"] if it["id"] in rows}
    rep = {"label": "確認集（盲集）", "n_items": len(rows), "n_units": sc["n_units"], "k0_status": k0,
           "k1": {k: (k1 or {}).get(k) for k in ("n_pass", "n_hit", "K1", "stop", "wording")},
           "verdict": verdict(seq, prob, stops, harm), "sequence": seq, "k3": harm,
           "arm_means": {a: mean([r["mean"][a] for r in rows.values() if r["mean"][a] is not None]) for a in ARMS},
           "calls": call_rates(rows), "aux_chars": aux_chars(meta),
           "item_level": item_level(rows, seq["H2"]["tested"]),
           "descriptive": {**st0_descriptives(rows, meta),
                           **describe(rows, meta, items, load_auto(LAYER_AUTO), load_ref(LAYER_REF),
                                      seq["H2"]["tested"])},
           "g_auto_abstain": sorted(i for i, m in meta.items() if not m["g_auto_fired"]),
           "g_ref_abstain": sorted(i for i, m in meta.items() if not m["g_ref_fired"]),
           "missing_jobs": sc["missing_jobs"], "seeds": sc["seeds"], "num_ctx": sc["num_ctx"],
           "code_changes": (read_json(manifest).get("code_changes") or []) if Path(manifest).is_file() else [],
           "power_disclosure": {"C": sc["n_units"], "m_mean": round(len(rows) / sc["n_units"], 3) if sc["n_units"] else None,
                                "fp_table": "C=12／15、m=3"}}
    cc.write_json(d / REPORT_JSON.name, rep)
    from report_c import write_md
    write_md(rep, d / REPORT_MD.name)
    return rep

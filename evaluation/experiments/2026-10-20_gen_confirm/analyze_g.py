"""Verdict, sensitivities and measurements of the GEN confirmation set (prereg §1.3, §1.5, §9) -> report.json, report.md.

Inputs: ``scores`` = score_g.score_all's output; ``items`` and ``meta`` = the build's (arms_g; items in pool sid
order); ``frozen`` = questions_frozen.json (n_target and the attrition lists, arms_g's contract); ``pool`` =
pool.json's slots; keyword-only ``measures`` (f2.json's: a report other than a dry run is refused without them or
when they differ from the build's, §5.5), ``run_meta`` (one segment per session: digest and version before and
after, dry_run), ``p2_near_miss`` = (k, n) false triggers of the P2 near-miss items, ``records`` (generation
records: tokens, seconds), ``gen_dir`` and ``jobs_unrecoverable``.

Test (§1.3, fixed order, FWER 0.05): H1 = G − B0; H2 = G − T-rows only when H1 passes (otherwise H2 has no p
anywhere: not in the sequence, the strata or any sensitivity). d_q = ȳ_G,q − ȳ_k,q (3 reps each, exact
Fractions; a rule abstention's d is 0 by score_g's reuse), in ascending pool sid order for sign_flip_p,
bootstrap_ci and every sensitivity. A step passes iff src.ab_stats.sign_flip_p(d, seed=20261018) (two-sided)
< 0.05 AND Δ̄ ≥ +0.10 − 1e-9; also reported: bootstrap_ci(d, 10000, seed=20261018), W:L:T and the pool-weighted
Δ̄ (weights N_h/N by stratum; a stratum without a frozen question is left out and the weights renormalised).
K3 (§1.3): ``k3`` is analyze_c.k3 copied with its arms renamed (G for G-auto, B0 for T-canon; wrong_rate and
calls_of imported from analyze_c unchanged; a regression test runs it on A's stored rows against A's k3).
Sensitivities (§1.5, description only): X clusters and (X, Y) pair clusters as A-style unit means (clusters in
order of their first sid); leave-one-person-out over every person on some frozen question's path (min Δ̄,
max p); worst-case attrition over the pool (every slot outside P_w, of every cause, at d = −1 and at its
stratum's mean); strata (question type, chapter, stratum, F5 d 2–4 / ≥ 5, the marker, homonym-end, 閃-as-X and
duplicate-gold slots and their complements); score_any (a step it flips adds
「寬鬆計分下 H〈k〉〈過／不過〉」, the verdict stays the strict one); the triggered subset and G-ref − G;
measurements (K3, a_meas, w_meas, R_trig, R_seed, calls over 120 s, truncations).
Verdict (§9): 作廢 (digest, Ollama version, truncation, unrecoverable missing jobs; a check without an answer is
never a cause: the report is refused until the run is resumed and checked again) before the sequence; the
sentences are §9's, verbatim, as fixed templates (SENTENCE); a variant clause, K3's 「不談 prod」 and the release
clause (P2 near-miss false triggers > 1/20) are appended with 「；」; a score_any flip is a separate note; every
verdict carries ``facts``: the population, n_target, unopened, the failed slots, deletions by cause, a_meas, Δ̄ and
CI. The failed slots (arms_g's one cause "failed") are split by why when ``failed_by_why`` is given (freeze_g's
HO_ROOT/freeze.json counts, ``failed_breakdown``): 「3 次都失敗」 is only why attempts, the closes after a dispute or
after Kay's page get their own labels (FAILED_LABEL); without it they are one 「沒寫成」 count.
Stop sentences for the runners that stop before this report: ``stop_sentence``, ``g1_stop_sentence`` and
``ka_stop_sentence``. A void line (void_g's record: prompt parity or a truncated smoke) gets ``void_report``, its
§9 sentence and nothing else. A dry run prefixes every sentence with DRY_RUN. Nothing here calls an LLM;
``write_report`` writes report.json and report.md (store only; ids and numbers, no question, answer, card or
scripture text).
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path
from statistics import median

import arms_g as A
import g_common as GC
import score_g as SG

if str(GC.REPO / "evaluation") not in sys.path:
    sys.path.insert(0, str(GC.REPO / "evaluation"))
from analyze_c import calls_of, wrong_rate  # noqa: E402  (A/confirm is on sys.path through GC.stage0())
from src import ab_stats  # noqa: E402

H1, H2 = ("G", "B0"), ("G", "T-rows")
ALPHA, MIN_DELTA, EPS, N_BOOT, K3_MAX, EXACT_MAX = 0.05, 0.10, 1e-9, 10000, 0.05, 16
SEED = GC.TEST_SEED
RELEASE_MAX = Fraction(1, 20)
DRY_RUN = "【dry run，假 chat，無意義】"
# §9's 〈digest／Ollama 版本／截斷／缺漏 job〉, and f2_g's §8.1-10.7 void (a parity failure only cards_common or prod
# could fix; its label is not one of §9's four)
VOID_WHY = {"digest": "digest", "version": "Ollama 版本", "truncation": "截斷", "missing": "缺漏 job",
            "parity": "prompt 對等"}
RUN_KEYS = ("digest_before", "digest_after", "version_before", "version_after")
STATES = ("未出題", "未凍結", "未跑")
STOP_RULES = ("G1", "K-P", "K-Kay", "K-gold", "K-a")
POP = "58 個題位（依事先抽定的順序寫到第 {n_target} 位）中寫成的 {n} 題"
POP_AGE = "58 個年歲題位（依事先抽定的順序寫到第 {n_target} 位）中寫成的 {n} 題"
SCOPE = ("（X 幾歲時 Y 出生〔相隔 2–4 代〕；X 去世那年 Y 幾歲；盲寫；題目寫出兩人的層名、只在必要時加一個不在路徑上的辨識詞、"
         "不含數字、點名創世記）")
# §9 (and §5.6 for G1 and K-a), verbatim; {pop} is §9's full population wording
SENTENCE = {
    "stop": "依事先規則停止（{rule}＝{value}），不構成無效證據；盲集{state}",
    "stop_g1": "依事先規則停止（G1：R_card＝{r_card}/{n_v}，R_wrong＝{r_wrong}/{n_v}），不構成無效證據；盲集未出題",
    "stop_ka": "依事先規則停止（K-a：a＝{a}，n＝{n}，檢定力＝{power}），不構成無效證據；盲集未跑",
    "void": "作廢（{why}），不構成任何方向的證據",
    "h1_fail": "創世記年歲推導卡（規則觸發、規則種子）在盲集上未達事先登記的門檻（{pop}，規則出卡且含答案的比例 a＝{a}，"
               "Δ̄＝{d}〔規則棄權的題記 0〕，95% CI {ci}），記 null；創世記算術線結案",
    "h1_negative": "且 G 顯著劣於同一段完整經文 context 不給卡",
    "sig_small": "顯著但未達事先定的最小效果",
    "h1_only": "在創世記 5、11 章 stage-0 未用過的 {pop}" + SCOPE + "上，規則觸發的程式推導卡使 gemma4:e4b 的平均答對率顯著高於"
               "同一段完整經文 context 不給卡（a＝{a}，Δ̄＝{d}〔棄權記 0〕，95% CI {ci}）；未證明程式推導優於『同一批層列交給模型"
               "自己算』，不計為圖譜增益；創世記算術線結案，不談 prod",
    "h2_negative": "且 G 顯著劣於給同一批層列、不給推導行",
    "h2_sig_small": "H2 顯著但未達事先定的最小效果",
    "both": "在創世記 5、11 章 stage-0 未用過的 {pop}" + SCOPE + "上，規則觸發、規則取種子的程式多步推導，使 gemma4:e4b 的平均答對率"
            "顯著高於同一段完整經文 context 不給卡（Δ̄＝{d1}，95% CI {ci1}），也高於給同一批層列、不給推導行（Δ̄＝{d2}，95% CI "
            "{ci2}）；Δ̄ 把規則棄權的題記為 0，規則出卡且含答案的比例 a＝{a}（受限寫法下量得，是真實問法下出卡且含答案比例的上限）；"
            "結論只及於這些題、這個出題流程、這個模型與這個 context",
    "k3": "不談 prod",
    "release": "觸發精確度未證明（P2 近似題誤觸發 {k}/{n}），不談 prod 接線",
    "lenient": "寬鬆計分下 H{k}{result}",
}
CAUSE_LABEL = {"unopened": "沒開寫", "failed": "沒寫成", "kay": "Kay 刪", "other_quantity": "問了別的量",
               "dynasty_trigger": "prod 王朝觸發", "cap_stopped": "硬上限停筆"}
# the failed closes by why (state_g.FAILED_WHY); §9's 「3 次都失敗」 is why attempts only, always reported
FAILED_LABEL = {"attempts": "3 次都失敗", "post_kay": "Kay 之後沒過", "kept_dispute": "爭議後沒過",
                "late_dispute": "Kay 之後又起爭議"}


# ---------------------------------------------------------------- stop sentences (the runners that stop early)
def stop_sentence(rule: str, value: str, state: str) -> str:
    if rule not in STOP_RULES or state not in STATES:
        raise ValueError(f"{rule} / {state}: not one of §9's rules {STOP_RULES} or states {STATES}")
    return SENTENCE["stop"].format(rule=rule, value=value, state=state)


def g1_stop_sentence(r_card: int, r_wrong: int, n_v: int) -> str:
    return SENTENCE["stop_g1"].format(r_card=r_card, r_wrong=r_wrong, n_v=n_v)


def ka_stop_sentence(a: float, n: int, power: float) -> str:
    return SENTENCE["stop_ka"].format(a=f"{a:.3f}", n=n, power=f"{power:.3f}")


# ---------------------------------------------------------------- the test
def mean(xs):
    return sum(xs) / len(xs) if xs else None


def d_test(d: list, with_p: bool = True) -> dict:
    """§1.3 on one d vector (in the order given): Δ̄, the bootstrap CI, W:L:T and (with_p) the sign-flip p."""
    xs = [float(x) for x in d]
    exact = sum(d, Fraction(0)) / len(d) if d and all(isinstance(x, (int, Fraction)) for x in d) else mean(xs)
    lo, hi = ab_stats.bootstrap_ci(xs, n_boot=N_BOOT, seed=SEED) if xs else (None, None)
    nz = sum(abs(x) > EPS for x in xs)
    out = {"n": len(xs), "delta": None if exact is None else float(exact), "ci95": [lo, hi], "n_nonzero": nz,
           "W": sum(x > EPS for x in xs), "L": sum(x < -EPS for x in xs), "T": sum(abs(x) <= EPS for x in xs)}
    if with_p:
        out.update(p=ab_stats.sign_flip_p(xs, seed=SEED) if xs else None, exact=nz <= EXACT_MAX)
    return out


def step(t: dict) -> dict:
    sig = t.get("p") is not None and t["p"] < ALPHA
    big = t["delta"] is not None and t["delta"] >= MIN_DELTA - EPS
    return {"pass": sig and big, "significant": sig, "sig_small": sig and not big and t["delta"] > 0,
            "negative": sig and t["delta"] < 0}


def d_by_sid(rows: dict, order: list[str], pair: tuple[str, str], field: str = "mean") -> dict[str, Fraction]:
    """{sid: d} in the given (pool sid) order, items with both arm values only."""
    out = {}
    for sid in order:
        a, b = (SG.frac(rows[sid][field][x]) for x in pair)
        if a is not None and b is not None:
            out[sid] = a - b
    return out


def pool_weighted(items: list[dict], d: dict, pool: list[dict]) -> dict:
    """Δ̄ with stratum weights N_h/N of the pool (a stratum without a frozen question left out, renormalised)."""
    N = {s: sum(p["stratum"] == s for p in pool) for s in dict.fromkeys(p["stratum"] for p in pool)}
    by = {s: [d[it["sid"]] for it in items if it["stratum"] == s and it["sid"] in d] for s in N}
    have = {s: v for s, v in by.items() if v}
    w = sum(N[s] for s in have)
    val = sum((Fraction(N[s], w) * (sum(v, Fraction(0)) / len(v)) for s, v in have.items()), Fraction(0)) if w else None
    return {"delta": None if val is None else float(val), "weights": {s: str(Fraction(n, len(pool))) for s, n in N.items()},
            "strata_missing": sorted(set(N) - set(have)), "by_stratum": {s: float(sum(v, Fraction(0)) / len(v)) for s, v in have.items()}}


def pair_block(items: list[dict], rows: dict, pool: list[dict], pair, with_p: bool, field: str = "mean") -> dict:
    order = [it["sid"] for it in items]
    d = d_by_sid(rows, order, pair, field)
    t = {"pair": f"{pair[0]}−{pair[1]}", "tested": with_p, **d_test(list(d.values()), with_p)}
    return {**t, **(step(t) if with_p else {"pass": False}), "pool_weighted": pool_weighted(items, d, pool)}


def fixed_sequence(items: list[dict], rows: dict, pool: list[dict], field: str = "mean") -> dict:
    h1 = pair_block(items, rows, pool, H1, True, field)
    return {"H1": h1, "H2": pair_block(items, rows, pool, H2, h1["pass"], field)}


# ---------------------------------------------------------------- K3: analyze_c.k3, copied with the arms renamed
def unit_test(v: dict, with_p: bool = True) -> dict:
    """analyze_c.unit_test, copied (k3 calls it with with_p False)."""
    xs = list(v.values())
    lo, hi = ab_stats.bootstrap_ci(xs, n_boot=N_BOOT, seed=SEED) if xs else (None, None)
    nonzero = sum(abs(x) > EPS for x in xs)
    out = {"n_units": len(xs), "delta": mean(xs), "ci95": [lo, hi], "units": v, "n_nonzero": nonzero,
           "W": sum(x > EPS for x in xs), "L": sum(x < -EPS for x in xs), "T": sum(abs(x) <= EPS for x in xs)}
    if with_p:
        out.update(p=ab_stats.sign_flip_p(xs, seed=SEED) if xs else None, exact=nonzero <= EXACT_MAX)
    return out


def k3(rows: dict, arms: tuple[str, ...] = A.ARMS, g: str = "G", base: str = "B0") -> dict:
    """G (substitutes included) − B0 wrong-answer rate over calls; unit bootstrap CI (analyze_c.k3's rule)."""
    rate = {a: wrong_rate(calls_of(rows, a)) for a in arms}
    diff = None if rate[g] is None or rate[base] is None else rate[g] - rate[base]
    by: dict = {}
    for r in rows.values():
        x = wrong_rate([v for k, v in r["reps"].items() if k.startswith(g + "|") and v])
        c = wrong_rate([v for k, v in r["reps"].items() if k.startswith(base + "|") and v])
        if x is not None and c is not None:
            by.setdefault(r["unit"], []).append(x - c)
    t = unit_test({u: mean(x) for u, x in sorted(by.items())}, with_p=False)
    return {"rate": rate, "diff": diff, "threshold": K3_MAX, "flag": diff is not None and diff > K3_MAX + EPS,
            "unit_delta": t["delta"], "unit_ci95": t["ci95"], "n_units": t["n_units"]}


# ---------------------------------------------------------------- §1.5 sensitivities
def cluster_test(items: list[dict], d: dict, key: str, with_p: bool) -> dict:
    groups: dict = {}
    for it in items:
        if it["sid"] in d:
            groups.setdefault(it[key], []).append(d[it["sid"]])
    return {"cluster": key, "n_clusters": len(groups),
            **d_test([sum(v, Fraction(0)) / len(v) for v in groups.values()], with_p)}


def leave_one_person_out(items: list[dict], d: dict, with_p: bool) -> dict:
    res = []
    for person in sorted({p for it in items for p in it["persons"]}):
        ds = [d[it["sid"]] for it in items if person not in it["persons"] and it["sid"] in d]
        if ds:
            res.append({"person": person, "n": len(ds), "delta": float(sum(ds, Fraction(0)) / len(ds)),
                        **({"p": ab_stats.sign_flip_p([float(x) for x in ds], seed=SEED)} if with_p else {})})
    return {"n_persons": len(res), "min_delta": min(res, key=lambda r: r["delta"], default=None),
            "max_p": max(res, key=lambda r: r["p"], default=None) if with_p else None, "by_person": res}


def worst_case(items: list[dict], d: dict, pool: list[dict], frozen: dict, with_p: bool) -> dict:
    """§1.5-4: every pool slot outside P_w (every §1.2 cause) at d = −1, and at its stratum's mean d."""
    got = {it["sid"]: it["stratum"] for it in items if it["sid"] in d}
    by = {s: [d[i] for i, h in got.items() if h == s] for s in set(got.values())}
    overall = sum(d.values(), Fraction(0)) / len(d) if d else Fraction(0)
    st_mean = {s: sum(v, Fraction(0)) / len(v) for s, v in by.items()}
    full = {"minus_one": [], "stratum_mean": []}
    for p in pool:
        if p["sid"] in d:
            full["minus_one"].append(d[p["sid"]])
            full["stratum_mean"].append(d[p["sid"]])
        else:
            full["minus_one"].append(Fraction(-1))
            full["stratum_mean"].append(st_mean.get(p["stratum"], overall))
    return {"n_pool": len(pool), "n_outside": len(pool) - len(d),
            "by_cause": {c: len(frozen["attrition"][c]) for c in A.ATTRITION},
            "strata_without_mean": sorted({p["stratum"] for p in pool} - set(st_mean)),
            **{k: d_test(v, with_p) for k, v in full.items()}}


def strata_groups(items: list[dict]) -> dict[str, list[str]]:
    sel = {
        "F1": lambda it: it["qtype"] == "F1", "F5": lambda it: it["qtype"] == "F5",
        "chapter_5": lambda it: it["chapter"] == 5, "chapter_11": lambda it: it["chapter"] == 11,
        **{s: (lambda it, s=s: it["stratum"] == s) for s in ("F1c5", "F1c11", "F5c5", "F5c11")},
        "F5_d2_4": lambda it: it["qtype"] == "F5" and 2 <= it["d"] <= 4, "F5_d5_up": lambda it: it["qtype"] == "F5" and it["d"] >= 5,
        **{f"{flag}": (lambda it, f=flag: bool(it[f])) for flag in ("marker_required", "homonym", "shem_x", "dup_gold")},
        **{f"not_{flag}": (lambda it, f=flag: not it[f]) for flag in ("marker_required", "homonym", "shem_x", "dup_gold")},
    }
    return {name: [it["sid"] for it in items if f(it)] for name, f in sel.items()}


def subset_test(d: dict, sids: list[str], with_p: bool) -> dict:
    return {"sids": sids, **d_test([d[s] for s in sids if s in d], with_p)}


def sensitivities(items: list[dict], rows: dict, meta: dict, pool: list[dict], frozen: dict, seq: dict) -> dict:
    order = [it["sid"] for it in items]
    out = {}
    for name, pair in (("H1", H1), ("H2", H2)):
        with_p, d = seq[name]["tested"], d_by_sid(rows, order, pair)
        fired = [it["sid"] for it in items if meta[it["id"]]["rule"]["fired"]]
        out[name] = {"pair": seq[name]["pair"], "with_p": with_p,
                     "cluster_x": cluster_test(items, d, "x", with_p), "cluster_pair": cluster_test(items, d, "pair", with_p),
                     "leave_one_person_out": leave_one_person_out(items, d, with_p),
                     "worst_case": worst_case(items, d, pool, frozen, with_p),
                     "strata": {k: subset_test(d, v, with_p) for k, v in strata_groups(items).items()},
                     "triggered": subset_test(d, fired, with_p)}
    ref = d_by_sid(rows, order, ("G-ref", "G"))
    ran = [it["sid"] for it in items if meta[it["id"]]["gref_job"]]
    out["G-ref−G"] = {"all": d_test(list(ref.values()), False), "gref_ran": subset_test(ref, ran, False)}
    return out


def lenient(strict: dict, items: list[dict], rows: dict, pool: list[dict]) -> dict:
    """§6: the fixed sequence on score_any; a step it flips gets 「寬鬆計分下 H〈k〉〈過／不過〉」."""
    seq = fixed_sequence(items, rows, pool, "mean_any")
    notes = [SENTENCE["lenient"].format(k=k, result="過" if seq[f"H{k}"]["pass"] else "不過")
             for k in (1, 2) if seq[f"H{k}"]["pass"] != strict[f"H{k}"]["pass"]]
    return {"sequence": seq, "notes": notes}


# ---------------------------------------------------------------- 作廢 and refusals
def _metas(run_meta) -> list[dict]:
    return [run_meta] if isinstance(run_meta, dict) else list(run_meta or [])


def run_problems(run_meta, known_only: bool = False) -> list[str]:
    """§4.5: every check the pinned digest and Ollama version (all segments); known_only leaves out no-answers."""
    ms = _metas(run_meta)
    if not ms:
        return ["run_meta"]
    vals = lambda keys: [m.get(k) for m in ms for k in keys]  # noqa: E731
    out = []
    if any(x != GC.EXPECTED_DIGEST for x in vals(("digest_before", "digest_after")) if not (known_only and x is None)):
        out.append("digest")
    if any(x != GC.OLLAMA_VERSION for x in vals(("version_before", "version_after")) if not (known_only and x is None)):
        out.append("version")
    return out


def run_unknown(run_meta) -> list[str]:
    return [f"{i}|{k}" for i, m in enumerate(_metas(run_meta), 1) for k in RUN_KEYS if m.get(k) is None]


def refusals(scores: dict, run_meta, gen_dir, jobs_unrecoverable: bool) -> list[str]:
    """Why no report is made yet (score again, or resume the run); [] = go on. A known digest or version mismatch
    is a void, never a refusal; a check without an answer is refused with or without jobs_unrecoverable."""
    out = [] if _metas(run_meta) else ["no run_meta: the run's checks are unknown"]
    if gen_dir is not None and scores.get("gen_sha256") != SG.gen_sha256(gen_dir):
        out.append("scores are not of the current generation file: run score again")
    if out or run_problems(run_meta, known_only=True):
        return out
    unknown = run_unknown(run_meta)
    if unknown:
        out.append(f"checks without an answer ({'、'.join(unknown)}): resume the run to check again")
    if scores.get("missing_jobs") and not jobs_unrecoverable:
        out.append(f"{len(scores['missing_jobs'])} jobs missing: fix and resume the run; only if they cannot be done "
                   "pass jobs_unrecoverable (the report is then 作廢)")
    return out


def void_reasons(scores: dict, run_meta) -> list[str]:
    out = [VOID_WHY[p] for p in run_problems(run_meta, known_only=True) if p in VOID_WHY]
    if scores.get("truncation_problems"):
        out.append(VOID_WHY["truncation"])
    if scores.get("missing_jobs"):
        out.append(VOID_WHY["missing"])
    return out


# ---------------------------------------------------------------- the verdict
def a_text(m: dict) -> str:
    a = m["a_meas"]
    return f"{a['float']:.3f}（{a['k']}/{a['n']}）"


def d_text(t: dict) -> str:
    return "—" if t["delta"] is None else f"{t['delta']:+.3f}"


def ci_text(t: dict) -> str:
    lo, hi = t["ci95"]
    return "—" if lo is None else f"[{lo:+.3f}, {hi:+.3f}]"


def failed_breakdown(frozen_sha256: str | None, path: Path | str) -> dict[str, int] | None:
    """freeze.json's failed closes by why (freeze_g's HO_ROOT/freeze.json at ``path``: run_g.freeze_file) when it
    exists; None without it. A freeze.json of other questions than ``frozen_sha256`` refuses the report."""
    p = Path(path)
    if not p.is_file():
        return None
    doc = GC.read_json(p)
    if doc.get("questions_frozen_sha256") != frozen_sha256:
        raise SystemExit(f"analyze refused: {p.name} is of other questions than the build's questions_frozen.json")
    return {str(k): int(v) for k, v in doc["counts"]["failed_by_why"].items()}


def attrition_parts(att: dict, failed_by_why: dict | None) -> list[str]:
    """§9's counts by cause; the failed slots split by why when known (「3 次都失敗」 always, the others when > 0)."""
    if failed_by_why is not None:
        if set(failed_by_why) - set(FAILED_LABEL) or sum(failed_by_why.values()) != att["failed"]:
            raise ValueError(f"failed_by_why {sorted(failed_by_why.items())} is not a split of the "
                             f"{att['failed']} failed slots")
    out = []
    for c in A.ATTRITION:
        if c == "failed" and failed_by_why is not None:
            out += [f"{lab} {failed_by_why.get(w, 0)}" for w, lab in FAILED_LABEL.items()
                    if w == "attempts" or failed_by_why.get(w)]
        else:
            out.append(f"{CAUSE_LABEL[c]} {att[c]}")
    return out


def facts(frozen: dict, n: int, measures: dict, seq: dict | None, failed_by_why: dict | None = None) -> dict:
    att = {c: len(frozen["attrition"][c]) for c in A.ATTRITION}
    pop = POP.format(n_target=frozen["n_target"], n=n)
    tail = "" if seq is None else (f"；H1（G−B0）Δ̄＝{d_text(seq['H1'])}、95% CI {ci_text(seq['H1'])}；H2（G−T-rows）Δ̄＝"
                                   f"{d_text(seq['H2'])}、95% CI {ci_text(seq['H2'])}（Δ̄ 把規則棄權的題記為 0）")
    text = (f"母體：{pop}；n_target＝{frozen['n_target']}；" + "、".join(attrition_parts(att, failed_by_why))
            + f"；a＝{a_text(measures)}" + tail)
    return {"population": pop, "n": n, "n_target": frozen["n_target"], "attrition": att,
            "failed_by_why": None if failed_by_why is None else dict(failed_by_why), "a_meas": measures["a_meas"],
            "text": text}


def release_due(p2: tuple[int, int]) -> bool:
    return Fraction(*p2) > RELEASE_MAX


def verdict(seq: dict, voids: list[str], harm: dict, fct: dict, p2: tuple[int, int], notes: list[str]) -> dict:
    """§9's sentence for this outcome, its appended clauses, the score_any notes and the facts line."""
    if voids:
        return {"result": "作廢", "sentence": SENTENCE["void"].format(why="、".join(voids)), "notes": [],
                "facts": fct["text"], "void": voids}
    h1, h2, a = seq["H1"], seq["H2"], a_text({"a_meas": fct["a_meas"]})
    pop = POP.format(n_target=fct["n_target"], n=fct["n"])
    pop_age = POP_AGE.format(n_target=fct["n_target"], n=fct["n"])
    if not h1["pass"]:
        s, result = SENTENCE["h1_fail"].format(pop=pop, a=a, d=d_text(h1), ci=ci_text(h1)), "H1 不過"
        extra = [SENTENCE["h1_negative"]] if h1["negative"] else [SENTENCE["sig_small"]] if h1["sig_small"] else []
    elif not h2["pass"]:
        s, result = SENTENCE["h1_only"].format(pop=pop_age, a=a, d=d_text(h1), ci=ci_text(h1)), "H1 過、H2 不過"
        extra = [SENTENCE["h2_negative"]] if h2["negative"] else [SENTENCE["h2_sig_small"]] if h2["sig_small"] else []
    else:
        s, result = SENTENCE["both"].format(pop=pop_age, a=a, d1=d_text(h1), ci1=ci_text(h1), d2=d_text(h2),
                                            ci2=ci_text(h2)), "H1、H2 皆過"
        extra = []
    if harm["flag"] and SENTENCE["k3"] not in s:
        extra.append(SENTENCE["k3"])
    if release_due(p2):
        extra.append(SENTENCE["release"].format(k=p2[0], n=p2[1]))
    return {"result": result, "sentence": "；".join([s, *extra]), "notes": list(notes), "facts": fct["text"],
            "k3_flag": harm["flag"], "release_clause": release_due(p2)}


def mark_dry_run(v: dict) -> dict:
    return {**v, "result": f"dry_run:{v['result']}", "sentence": DRY_RUN + v["sentence"],
            "notes": [DRY_RUN + n for n in v["notes"]]}


# ---------------------------------------------------------------- measurements
def call_stats(rows: dict, records: dict | None) -> dict | None:
    if records is None:
        return None
    out = {}
    for arm in A.ARMS:
        recs = [records[v["job_id"]] for v in SG.calls(rows, arm) if v["job_id"] in records]
        secs = [r["elapsed_s"] for r in recs if r.get("elapsed_s") is not None]
        toks = [r["prompt_eval_count"] for r in recs if r.get("prompt_eval_count") is not None]
        out[arm] = {"calls": len(recs), "seconds_mean": mean(secs), "seconds_median": median(secs) if secs else None,
                    "seconds_max": max(secs, default=None), "prompt_tokens_max": max(toks, default=None)}
    return out


MEASURE_KEYS = ("n", "a_meas", "w_meas", "R_trig", "R_seed", "abstentions")


def f2_agrees(meta: dict, measures: dict | None) -> bool | None:
    mine = A.rule_measures(meta)
    return None if measures is None else all(mine[k] == measures.get(k) for k in MEASURE_KEYS)


def measurements(scores: dict, meta: dict, measures: dict | None, harm: dict, records: dict | None) -> dict:
    mine = A.rule_measures(meta)
    return {"rule": mine, "f2_agrees": f2_agrees(meta, measures),
            "k3": harm, "truncation": scores["truncation"], "over_120s": {a: c["over_120s"] for a, c in scores["counts"].items()},
            "counts": scores["counts"], "calls": call_stats(scores["items"], records)}


# ---------------------------------------------------------------- the report
def check_inputs(scores: dict, items: list[dict], meta: dict, frozen: dict, pool: list[dict]) -> None:
    order = [it["sid"] for it in items]
    index = {p["sid"]: i for i, p in enumerate(pool)}
    if [index[s] for s in order] != sorted(index[s] for s in order) or len(set(order)) != len(order):
        raise ValueError("items are not in ascending pool sid order")
    if order != [q["sid"] for q in frozen["questions"]] or set(scores["items"]) != set(order) or set(meta) != set(order):
        raise ValueError("items, scores, meta and questions_frozen.json are not the same questions")


def analyze(scores: dict, items: list[dict], meta: dict, frozen: dict, pool: list[dict], *, measures: dict | None = None,
            run_meta=None, p2_near_miss: tuple[int, int] | None = None, records: dict | None = None,
            gen_dir: Path | str | None = None, jobs_unrecoverable: bool = False,
            failed_by_why: dict | None = None) -> dict:
    """The confirmation-set report (§1.3, §1.5, §9) as a JSON-ready dict; writes nothing."""
    check_inputs(scores, items, meta, frozen, pool)
    dry = any(m.get("dry_run") for m in _metas(run_meta))
    if p2_near_miss is None:
        if not dry:
            raise SystemExit("analyze refused: the P2 near-miss false-trigger count (k, n) is needed for §9's release clause")
        p2_near_miss = (0, 20)
    refused = refusals(scores, run_meta, gen_dir, jobs_unrecoverable)
    if not dry and measures is None:
        refused.append("f2.json's measures are needed (§5.5: F2's a_meas, w_meas, R_trig, R_seed)")
    elif not dry and not f2_agrees(meta, measures):
        refused.append("f2.json's measures differ from the build's: the rule is not the one F2 measured (§5.5)")
    if refused:
        raise SystemExit("analyze refused, no report: " + "; ".join(refused))
    rows = scores["items"]
    seq, harm, voids = fixed_sequence(items, rows, pool), k3(rows), void_reasons(scores, run_meta)
    lax = lenient(seq, items, rows, pool)
    meas = measurements(scores, meta, measures, harm, records)
    fct = facts(frozen, len(items), meas["rule"], seq, failed_by_why)
    v = verdict(seq, voids, harm, fct, tuple(p2_near_miss), lax["notes"])
    if dry:
        v = mark_dry_run(v)
    return {"schema": "gen_confirm.report.v1", "label": "確認集（盲集）", "dry_run": dry, "n": len(items),
            "verdict": v, "sequence": seq, "score_any": lax, "sensitivities": sensitivities(items, rows, meta, pool, frozen, seq),
            "measurements": meas, "facts": fct, "p2_near_miss": list(p2_near_miss), "arm_means": scores["arm_means"],
            "inputs": {"gen_sha256": scores.get("gen_sha256"), "gen_checked": gen_dir is not None, "run_meta": run_meta,
                       "jobs_unrecoverable": bool(jobs_unrecoverable), "f2_measures": measures is not None},
            "thresholds": {"alpha": ALPHA, "min_delta": MIN_DELTA, "eps": EPS, "k3_max": K3_MAX, "n_boot": N_BOOT,
                           "seed": SEED, "release_max": str(RELEASE_MAX)},
            "code_sha256": {p: GC.sha256_file(GC.HERE / p) for p in ("analyze_g.py", "score_g.py", "arms_g.py")}}


def _t(t: dict) -> str:
    p = "—" if t.get("p") is None else f"{t['p']:.4f}"
    return f"n {t['n']}｜Δ̄ {d_text(t)}｜CI {ci_text(t)}｜p {p}｜W:L:T {t['W']}:{t['L']}:{t['T']}"


def render_md(rep: dict) -> str:
    v, seq, m = rep["verdict"], rep["sequence"], rep["measurements"]
    lines = [f"# GEN 確認集報告（{rep['label']}{'，dry run' if rep['dry_run'] else ''}）", "", "## 判定（§9）", "",
             f"- {v['sentence']}", *[f"- {n}" for n in v["notes"]], f"- {v['facts']}", "", "## 檢定（§1.3，固定順序）", ""]
    for k in ("H1", "H2"):
        t = seq[k]
        lines.append(f"- {k}（{t['pair']}）：{_t(t)}；{'通過' if t['pass'] else '不過'}"
                     + ("" if t["tested"] else "（未檢定，不報 p）") + f"；題位池加權 Δ̄ {t['pool_weighted']['delta']}")
    k = m["k3"]
    lines += ["", "## 量測（§1.5-8）", "", f"- K3：G 答錯率 − B0 答錯率＝{k['diff']}（門檻 +{K3_MAX}）；{'不談 prod' if k['flag'] else '未觸發'}",
              f"- a_meas {m['rule']['a_meas']['frac']}、w_meas {m['rule']['w_meas']['frac']}、R_trig "
              f"{m['rule']['R_trig']['frac']}、R_seed {m['rule']['R_seed']['frac']}；棄權理由 {m['rule']['abstentions']}",
              f"- 截斷 {m['truncation']}；超過 120 秒 {m['over_120s']}", "", "## 敏感度（§1.5，只描述）", ""]
    for k in ("H1", "H2"):
        s = rep["sensitivities"][k]
        lines += [f"### {k}（{s['pair']}）", "", f"- X 群集：{_t(s['cluster_x'])}", f"- (X, Y) 群集：{_t(s['cluster_pair'])}",
                  f"- 留一人：最低 Δ̄ {s['leave_one_person_out']['min_delta']}；最高 p {s['leave_one_person_out']['max_p']}",
                  f"- 最壞情況（d＝−1）：{_t(s['worst_case']['minus_one'])}", f"- 最壞情況（層平均）：{_t(s['worst_case']['stratum_mean'])}",
                  f"- 只看觸發：{_t(s['triggered'])}", *[f"- 分層 {g}：{_t(t)}" for g, t in s["strata"].items()], ""]
    lines += [f"- G-ref − G：{_t(rep['sensitivities']['G-ref−G']['all'])}", ""]
    return "\n".join(lines)


def write_text(path: Path | str, text: str) -> Path:
    p = GC.writable(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)
    return p


def void_report(record: dict) -> dict:
    """The report of a void line (void_g's record): §9's void sentence only, nothing measured or tested."""
    sentence = record.get("sentence") or SENTENCE["void"].format(why="?")
    return {"schema": "gen_confirm.report.v1", "label": "確認集（盲集）", "dry_run": False, "void_only": True,
            "verdict": {"result": "作廢", "sentence": sentence, "notes": [], "void": [record.get("label")]},
            "void": {k: record.get(k) for k in ("why", "label", "anchor", "t")}}


def render_void_md(rep: dict) -> str:
    return "\n".join([f"# GEN 確認集報告（{rep['label']}）", "", "## 判定（§9）", "", f"- {rep['verdict']['sentence']}", ""])


def write_report(rep: dict, out_dir: Path | str) -> tuple[Path, Path]:
    json.dumps(rep, ensure_ascii=False)
    md = render_void_md(rep) if rep.get("void_only") else render_md(rep)
    return (GC.write_json(Path(out_dir) / GC.RUN_REPORT, rep), write_text(Path(out_dir) / GC.RUN_REPORT_MD, md))

"""Experiment B stage-0 analysis: K-S0 exactly as prereg §3, descriptives, report (開發集).

Item score per arm = mean of its reps. G abstained -> in every comparison G takes the compared
arm's own score (difference 0). K-S0 power: FP verify_C1_power_cost/power_c1_v2.gen(32, 4, pT, a,
adh, r, prec, 3) and its pflip; IUT = H1 (G-TLLM) and H2 (G-T1C) each p < 0.05 and mean >= +0.05,
300 simulations.
"""
from __future__ import annotations

import importlib.util
import statistics

import b_lib as L
import report_b
from b_lib import cc

ARMS = ("G", "T1C", "TLLM", "B0", "GO")
RETRIEVAL_COEF = 0.82
FRAME_ITEM_PERICOPES, FRAME_SIZE = 92, 169
PT_STOP, GAP, POWER_STOP, NSIM = 0.65, 0.05, 0.7, 300
C_SIM, M_SIM, R_SIM = 32, 4, 3
N_BOOT, N_PERM = 10000, 20000
VERDICTS = ("依事先規則停止，不構成無效證據", "開發集通過，請 Kay 授權確認集", "作廢")


def _load(name: str, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ab_stats():
    return _load("ab_stats", L.HERE.parents[2] / "src/ab_stats.py")


def item_means(scores: dict) -> dict:
    out = {}
    for iid, s in scores["items"].items():
        out[iid] = {a: statistics.fmean(r["ok"] for r in reps.values())
                    for a, reps in s["arms"].items() if reps}
    return out


def eff(m: dict, s: dict, arm: str, other: str) -> float:
    """arm's item score, or the compared arm's own score when arm did not run (abstained)."""
    fired = s["fired"] if arm == "G" else s["oracle_fired"] if arm == "GO" else True
    return m[arm] if fired and arm in m else m[other]


def ratio(num_items, m: dict, arm: str) -> tuple[float, dict]:
    """clip((mean arm - mean TLLM) / (1 - mean TLLM), 0, 1) over num_items (item-level means)."""
    if not num_items:
        return 0.0, dict(n=0, rule="no items -> 0")
    x = statistics.fmean(m[i][arm] for i in num_items)
    t = statistics.fmean(m[i]["TLLM"] for i in num_items)
    if 1 - t < 1e-9:
        return (1.0 if x >= 1 - 1e-9 else 0.0), dict(n=len(num_items), arm=x, tllm=t, rule="TLLM=1")
    return min(1.0, max(0.0, (x - t) / (1 - t))), dict(n=len(num_items), arm=x, tllm=t)


def iut_power(pT, a, adh, r, prec) -> float:
    P = _load("power_c1_v2", L.POWER_DIR / "power_c1_v2.py")
    hits = 0
    for _ in range(NSIM):
        _, _, T, G, T1 = P.gen(C_SIM, M_SIM, pT, a, adh, r, prec, R_SIM)
        d1, d2 = (G - T).mean(1), (G - T1).mean(1)
        h1 = P.pflip(d1) < 0.05 and d1.mean() >= 0.05
        h2 = P.pflip(d2) < 0.05 and d2.mean() >= 0.05
        hits += bool(h1 and h2)
    return hits / NSIM


def ks0(scores: dict, m: dict) -> dict:
    S = scores["items"]
    ids = sorted(S)
    fired = [i for i in ids if S[i]["fired"]]
    card_ok = [i for i in fired if S[i]["card_ok"]]
    disp = [i for i in ids if S[i]["dispersed"]]
    pT = statistics.fmean(m[i]["TLLM"] for i in ids)
    t1c_d = statistics.fmean(m[i]["T1C"] for i in disp) if disp else None
    card_d = statistics.fmean(S[i]["card_ok"] for i in disp) if disp else None
    g_b0 = statistics.fmean(eff(m[i], S[i], "G", "B0") for i in ids)
    b0 = statistics.fmean(m[i]["B0"] for i in ids)
    prec = len(card_ok) / len(fired) if fired else 0.0
    fire_rate = len(fired) / len(ids)
    a = fire_rate * RETRIEVAL_COEF * (FRAME_ITEM_PERICOPES / FRAME_SIZE)
    adh, adh_meta = ratio(card_ok, m, "G")
    r, r_meta = ratio(fired, m, "T1C")
    power = iut_power(pT, a, adh, r, prec)
    rules = {
        "1_pT_ge_0.65": pT >= PT_STOP,
        "2_dispersed_T1C_ge_card_minus_0.05": (t1c_d >= card_d - GAP) if disp else True,
        "3_G_le_B0": g_b0 <= b0,
        "4_power_lt_0.7": power < POWER_STOP,
    }
    return dict(pT=pT, n_dispersed=len(disp), T1C_dispersed=t1c_d, card_rate_dispersed=card_d,
                G_vs_B0=g_b0, B0=b0, n_fired=len(fired), fire_rate=fire_rate, prec=prec, a=a,
                adh=adh, adh_meta=adh_meta, r=r, r_meta=r_meta, power_iut=power,
                power_args=dict(C=C_SIM, m=M_SIM, pT=pT, a=a, adh=adh, r=r, prec=prec, R=R_SIM, nsim=NSIM),
                rules=rules, stop=[k for k, v in rules.items() if v],
                note_rule2_empty="no dispersed item -> rule 2 counts as met" if not disp else "")


def compare(S: dict, m: dict, arm: str, other: str, ids: list[str]) -> dict:
    st = ab_stats()
    d = [eff(m[i], S[i], arm, other) - m[i][other] for i in ids]
    by_p = {}
    for i, x in zip(ids, d):
        by_p.setdefault(S[i]["pericope"], []).append(x)
    dc = [statistics.fmean(v) for v in by_p.values()]
    out = dict(n=len(ids), mean=statistics.fmean(d) if d else None, n_clusters=len(dc))
    if d:
        out.update(ci_item=st.bootstrap_ci(d, N_BOOT, L.SEED), p_item=st.sign_flip_p(d, N_PERM, L.SEED),
                   ci_cluster=st.bootstrap_ci(dc, N_BOOT, L.SEED), p_cluster=st.sign_flip_p(dc, N_PERM, L.SEED),
                   wins=sum(x > 0 for x in d), losses=sum(x < 0 for x in d))
    return out


def dispersed_variants(S: dict, m: dict, ids: list[str]) -> dict:
    """Rule 2 under other readings of 分散題 (descriptive): T1C mean vs card-correct rate."""
    sets = {"dispersed_rule": [i for i in ids if S[i]["dispersed"]],
            "dispersed_or_unlocated": [i for i in ids if S[i]["dispersed"] or S[i]["layout"] == "unlocated"],
            "scattered_only": [i for i in ids if S[i]["layout"] == "scattered"],
            "unlocated_only": [i for i in ids if S[i]["layout"] == "unlocated"]}
    return {k: dict(n=len(v), T1C=_mean(m, v, "T1C")["mean"],
                    card_ok=statistics.fmean(S[i]["card_ok"] for i in v) if v else None) for k, v in sets.items()}


def chain_dedup(S: dict, ids: list[str]) -> list[str]:
    """One item per gold chain (lowest id), for the duplicate-chain description."""
    seen, out = set(), []
    for i in ids:
        c = tuple(S[i]["chain"])
        if c not in seen:
            seen.add(c); out.append(i)
    return out


def variant_rates(S: dict, ids: list[str]) -> dict:
    """Per arm: mean of the first-clause-trap score and the share of hits found only in brackets."""
    out = {}
    for a in ARMS:
        rs = [r for i in ids for r in S[i]["arms"].get(a, {}).values() if not r.get("missing")]
        out[a] = dict(n=len(rs), ok=statistics.fmean(r["ok"] for r in rs) if rs else None,
                      ok_first_clause=statistics.fmean(r.get("ok_first_clause", 0) for r in rs) if rs else None,
                      ok_only_in_parens=sum(bool(r.get("accept_only_in_parens")) and r["ok"] == 1 for r in rs))
    return out


def slot_summary(slots: list[dict]) -> dict:
    out = {}
    for a in ("T1C", "TLLM"):
        xs = [x for x in slots if x["arm"] == a]
        out[a] = dict(n=len(xs), lines_mean=statistics.fmean(x["n_lines"] for x in xs) if xs else None,
                      chars_mean=statistics.fmean(x["chars"] for x in xs) if xs else None,
                      cut_lines=sum(x["cut_lines"] for x in xs), cut_chars=sum(x["cut_chars"] for x in xs))
    return out


def describe(scores: dict, m: dict) -> dict:
    S = scores["items"]
    ids = sorted(S)
    fired = [i for i in ids if S[i]["fired"]]
    both = [i for i in fired if S[i]["oracle_fired"]]
    dedup = chain_dedup(S, ids)
    pairs = (("G", "TLLM"), ("G", "T1C"), ("G", "B0"))
    out = dict(all={f"{a}-{b}": compare(S, m, a, b, ids) for a, b in pairs},
               fired={f"{a}-{b}": compare(S, m, a, b, fired) for a, b in pairs},
               chain_dedup={f"{a}-{b}": compare(S, m, a, b, dedup) for a, b in pairs},
               oracle_minus_G_both_fired=compare(S, m, "GO", "G", both))
    out["n_clusters"] = len({S[i]["pericope"] for i in ids})
    out["dispersed_variants"] = dispersed_variants(S, m, ids)
    out["score_variants"] = variant_rates(S, ids)
    out["slots"] = slot_summary(scores.get("slots", []))
    out["arm_means_all"] = {a: _mean(m, ids, a) for a in ("T1C", "TLLM", "B0")}
    out["arm_means_fired"] = {a: _mean(m, fired, a) for a in ARMS}
    strata = sorted({S[i]["stratum"] for i in ids})
    out["by_stratum"] = {s: dict(n=sum(S[i]["stratum"] == s for i in ids),
                                 **{a: _mean(m, [i for i in ids if S[i]["stratum"] == s], a) for a in ARMS})
                         for s in strata}
    out["lookup_layer_items"] = [i for i in fired if S[i]["lookup_layer"]]
    out["abstain_reasons"] = _count(S[i]["card_reason"] for i in ids if not S[i]["fired"])
    out["layout"] = _count(S[i]["layout"] for i in ids)
    out["fail_why"] = {a: _count(r["why"] for i in ids for r in S[i]["arms"].get(a, {}).values()) for a in ARMS}
    out["aux_chars"] = aux_chars(S)
    return out


def _mean(m, ids, arm):
    xs = [m[i][arm] for i in ids if arm in m[i]]
    return dict(n=len(xs), mean=statistics.fmean(xs) if xs else None)


def _count(xs) -> dict:
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def aux_chars(S: dict) -> dict:
    """user prompt chars minus the item's B0 prompt chars, per arm (answers' user_chars)."""
    out = {}
    for a in ARMS:
        xs = [r["user_chars"] - S[i]["arms"]["B0"]["1"]["user_chars"] for i in S
              for r in S[i]["arms"].get(a, {}).values()
              if r.get("user_chars") is not None and S[i]["arms"].get("B0", {}).get("1", {}).get("user_chars")]
        out[a] = dict(n=len(xs), mean=statistics.fmean(xs) if xs else None, max=max(xs) if xs else None)
    return out


def verdict(k: dict, scores: dict, k0: dict | None) -> tuple[str, str]:
    if k0 is None:
        return "未判定", "K0（40 張卡人工核對、20 題 gold、截斷檢查）結果檔 k0_result.json 不存在"
    if not scores.get("ctx_len"):
        return "未判定", "scores.json 沒有 context_length（截斷判定不完整）；用 --ctx-len 或 smoke/ps.json 重跑 score"
    if k0.get("cards_precision", 0) < 0.85 or not k0.get("truncation_ok", False):
        return VERDICTS[2], "K0 未過"
    if scores["n_missing"]:
        return VERDICTS[2], f"基礎設施：{scores['n_missing']} 個 job 沒有結果"
    if k["stop"]:
        return VERDICTS[0], "停在 " + "、".join(k["stop"])
    return VERDICTS[1], ""


def run() -> dict:
    scores = L.load_json(L.OUT / "scores.json")
    k0_path = L.OUT / "k0_result.json"
    k0 = L.load_json(k0_path) if k0_path.exists() else None
    m = item_means(scores)
    k = ks0(scores, m)
    v, why = verdict(k, scores, k0)
    rep = dict(label="開發集（stage-0），不構成證據", verdict=v, verdict_detail=why, ks0=k, k0=k0,
               describe=describe(scores, m), n_missing=scores["n_missing"], ctx_len=scores["ctx_len"])
    cc.write_json(L.OUT / "report.json", rep)
    (L.OUT / "report.md").write_text(report_b.render(rep), encoding="utf-8")
    return rep

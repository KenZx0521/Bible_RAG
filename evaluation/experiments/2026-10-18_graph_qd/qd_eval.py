"""Step 1 evaluation of plan.md §3–§4 (reads gold; its own process, after lanes are frozen).

usage: /home/kenzx0521/Bible_RAG/evaluation/.venv/bin/python -B qd_eval.py
  -> OUT/report.json and OUT/report.md

f(q)@6 = GD prereg §4 on C5 + the appended passage; a QD-family arm's f(q) is the mean of
its 3 reps (exact Fractions). Pairs use GD _eval_report.compare (40 union-find units,
bootstrap CI, exact two-sided sign-flip p). The verdicts G, O, M, K apply plan.md §4 as
written (a verdict whose arms fail K is void, not pass / fail); I reads new82_ans
retrieval_iter.json (IT-GD−IT-D @7) when it exists and is void if its metric self-check or
its decompositions fail K.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import qd_common as Q

gd = Q.gd
M = Q._import_pinned("_eval_metrics", Q.GD_DIR, None)
R = Q._import_pinned("_eval_report", Q.GD_DIR, None)

OUT = Q.OUT
LANES, SHAFILE = OUT / "lanes.json", OUT / "lanes.sha256"
IT_REPORT = Q.NEW82_ANS / "retrieval_iter.json"
REPORT_JSON, REPORT_MD = OUT / "report.json", OUT / "report.md"
FALLBACK_MAX = Fraction(5, 100)
M_P_TWO_SIDED = Fraction(20, 100)        # one-sided p < 0.10
PAIRS = {"G1": ("QD+G", "QD+N"), "G2": ("QD+G", "DEEP"), "G3": ("QD+G", "QD"),
         "O": ("QD+ORACLE", "QD"), "M": ("QD", "DEEP")}
ARMS_OF = {"G": ("QD+G", "QD+N", "QD"), "O": ("QD+ORACLE", "QD"), "M": ("QD",)}
REFPAIRS_STEP1 = ("refpairs_before.jsonl", "refpairs_mid.jsonl")
DESCRIPTIVE = (("QD+N", "QD"), ("QD+N", "DEEP"), ("QD+ORACLE", "DEEP"),
               ("DEEP", "C6"), ("QD", "C6"), ("DEEP", "C5"))


def check_frozen() -> dict[str, str]:
    want = {}
    for line in SHAFILE.read_text(encoding="utf-8").splitlines():
        sha, name = line.split(maxsplit=1)
        want[name] = sha
    for name, sha in want.items():
        gd.expect(f"frozen {name}", gd.file_sha256(OUT / name), sha)
    return want


def tops(lanes: dict, c6: dict) -> dict[str, dict[str, list[tuple[str, ...]]]]:
    """arm -> qid -> list of top lists (one per rep; DEEP / C5 / C6 have one)."""
    out: dict[str, dict] = {"C5": {}, "C6": {}, "DEEP": {}, **{a: {} for a in Q.LLM_ARMS}}
    for qid, e in lanes.items():
        c5 = tuple(e["C5"])
        out["C5"][qid] = [c5]
        out["C6"][qid] = [c6[qid]]
        out["DEEP"][qid] = [c5 + (e["DEEP"]["pid"],)]
        for a in Q.LLM_ARMS:
            out[a][qid] = [c5 + (r["pid"],) for r in sorted(e[a], key=lambda r: r["rep"])]
    return out


def mean_cov(gold, lists) -> Fraction:
    return sum((M.coverage(gold, t) for t in lists), Fraction(0)) / len(lists)


def arm_summary(items, arm_tops) -> dict:
    reps = len(next(iter(arm_tops.values())))
    hits = [sum(M.hop_hits(it.gold, arm_tops[it.qid][r])[h] for it in items for h in it.missing)
            for r in range(reps)]
    cov = [float(sum(M.coverage(it.gold, arm_tops[it.qid][r]) for it in items) / len(items))
           for r in range(reps)]
    return {"reps": reps, "missing_hops_hit_per_rep": hits,
            "missing_hops_hit_mean": sum(hits) / reps, "mean_coverage_per_rep": cov}


def m_pass(cmp: dict) -> bool:
    return (Fraction(cmp["sum_v"]) > 0 and Fraction(cmp["p_exact"]) < M_P_TWO_SIDED
            and cmp["unit_W"] >= 2 * cmp["unit_L"] and cmp["unit_W"] > 0)


def it_decompositions() -> dict:
    """K for the IT arms (frozen build_it keeps the first dec line per key, errors included)."""
    first: dict[str, dict] = {}
    for name in ("dec_t1", "dec_t2"):
        path = Q.NEW82_ANS / "stages" / f"{name}.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line) if line.strip() else {}
                if rec.get("type") == "dec":
                    first.setdefault(rec["key"], rec)
    fallbacks = sum(r["fallback"] for r in first.values())
    infra = sorted(k for k, r in first.items() if not Q.dec_is_result(r))
    return {"n": len(first), "fallbacks": fallbacks, "ollama_failure_fallbacks": infra,
            "ok": bool(first) and not infra and Fraction(fallbacks, len(first)) <= FALLBACK_MAX}


def it_verdict() -> dict:
    if not IT_REPORT.exists():
        return {"available": False, "close_e4_it_gd": None}
    doc = json.loads(IT_REPORT.read_text(encoding="utf-8"))
    c = doc["comparisons"]["IT-GD−IT-D"]
    w, l = (int(x) for x in c["unit_W:L"].split(":"))
    repro = all(v["ok"] for v in doc["reference_reproduction"].values())
    k = it_decompositions()
    close = (c["mean_unit_diff"] <= 0 or w <= l) if repro and k["ok"] else None
    return {"available": True, "IT-GD−IT-D@7": c, "close_e4_it_gd": close,
            "reference_reproduction_ok": repro, "K": k, "report_sha256": gd.file_sha256(IT_REPORT)}


def refpairs() -> dict:
    out = {}
    for name in REFPAIRS_STEP1:
        path = OUT / "logs" / name
        recs = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()] \
            if path.exists() else []
        chk = [r for r in recs if r.get("type") == "refcheck"]
        out[name] = {"max_abs_diff": chk[-1]["max_abs_diff"], "pass": chk[-1]["pass"]} if chk else None
    return out


def identical_reps(lanes: dict) -> dict:
    """Questions whose 3 sub-queries are identical, per arm (decomposer non-determinism)."""
    return {a: sum(len({r["subquery"] for r in e[a]}) == 1 for e in lanes.values()) for a in Q.LLM_ARMS}


def weak_win(cmp: dict) -> bool:
    """G3 (QD+G − QD): mean unit difference > 0 and W > L."""
    return cmp["mean_unit_diff"] > 0 and cmp["unit_W"] > cmp["unit_L"]


def main() -> int:
    frozen = check_frozen()
    lanes = json.loads(LANES.read_text(encoding="utf-8"))
    qs = gd.load_new82()
    items = R.items_of(qs)
    gd.expect("lanes question ids", sorted(lanes), sorted(it.qid for it in items))
    lists = Q.H.load_lists()
    c_scores = Q.H.load_c_scores(lists, list(lanes))
    c6 = {q: tuple(Q.H.c_top(lists, c_scores, q, 6)) for q in lanes}
    for q in lanes:
        gd.expect(f"{q} C5", tuple(lanes[q]["C5"]), c6[q][:5])
    t = tops(lanes, c6)
    cov = {a: {it.qid: mean_cov(it.gold, t[a][it.qid]) for it in items} for a in t}

    comps = {}
    for name, (x, y) in PAIRS.items():
        comps[name], _ = R.compare(items, cov[x], cov[y], with_p=True)
        comps[name]["pair"] = f"{x}−{y}@6"
    desc = {}
    for x, y in DESCRIPTIVE:
        desc[f"{x}−{y}"], _ = R.compare(items, cov[x], cov[y], with_p=True)

    fallbacks = {a: sum(r["fallback"] for e in lanes.values() for r in e[a]) for a in Q.LLM_ARMS}
    n_dec = len(lanes) * Q.N_REPS
    void = {a: Fraction(n, n_dec) > FALLBACK_MAX for a, n in fallbacks.items()}
    ref = refpairs()
    ref_ok = all(v and v["pass"] for v in ref.values())
    valid = {v: ref_ok and not any(void[a] for a in arms) for v, arms in ARMS_OF.items()}
    oracle_n = sum(bool(e["QD+ORACLE"]) for e in json.loads((OUT / "names.json").read_text(encoding="utf-8")).values())
    VOID = "作廢（K）：相關臂 fallback 超過 5% 或 refpairs 不合格，只准重跑一次，不判"

    g_pass = Q.gate_pass(comps["G1"]) and Q.gate_pass(comps["G2"]) and weak_win(comps["G3"])
    o_pass = Q.gate_pass(comps["O"])
    verdicts = {
        "K": {"fallbacks": fallbacks, "n_per_arm": n_dec, "void_arms": [a for a, v in void.items() if v],
              "refpairs": ref, "refpairs_ok": ref_ok, "identical_reps": identical_reps(lanes)},
        "G": {"pass": g_pass if valid["G"] else None, "G1_pass": Q.gate_pass(comps["G1"]),
              "G2_pass": Q.gate_pass(comps["G2"]), "G3_pass": weak_win(comps["G3"]),
              "reading": (VOID if not valid["G"] else "開發集探索性陽性：盲集確認另議（要 Kay）" if g_pass else
                          "依事先規則停止，不構成無效證據；結案現況圖譜層上的所有檢索變體（§0-2）")},
        "O": {"pass": o_pass if valid["O"] else None, "n_questions_with_oracle_names": oracle_n,
              "reading": (VOID if not valid["O"] else
                          f"依事先規則未過，不構成無效證據：合格的 gold 橋接名（{oracle_n} 題有名稱）寫進查詢也沒過門檻"
                          if not o_pass else
                          "現況 KG 挑不出名字（合格的 gold 橋接名有效，圖譜挑的名字沒過）" if not g_pass
                          else "ORACLE 與 G 都過")},
        "M": {"pass": m_pass(comps["M"]) if valid["M"] else None,
              "reading": VOID if not valid["M"] else "QD 列為盲集候選" if m_pass(comps["M"]) else "QD 不列入"},
        "I": it_verdict(),
    }
    doc = {"meta": {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "frozen": frozen, "qd_eval_sha256": gd.file_sha256(Path(__file__)),
                    "plan_sha256": gd.file_sha256(Q.HERE / "plan.md"),
                    "n_questions": len(items), "n_hops": qs.n_hops,
                    "n_missing_hops": sum(len(it.missing) for it in items),
                    "note": "exploratory (NEW82 = development set); p values descriptive"},
           "arms": {a: {**arm_summary(items, t[a]),
                        "mean_f": float(sum(cov[a].values()) / len(items))} for a in t},
           "primary": comps, "descriptive": desc, "verdicts": verdicts,
           "per_question": {it.qid: {a: str(cov[a][it.qid]) for a in t} for it in items}}
    REPORT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render(doc), encoding="utf-8")
    print(render(doc))
    return 0


def verdict_word(x) -> str:
    return "作廢" if x is None else "過" if x else "未過"


def render(doc: dict) -> str:
    v, p = doc["verdicts"], doc["primary"]
    rows = ["| 臂 | 平均 f(q) | 缺跳命中 /102（各次） |", "|---|---|---|"]
    for a, s in doc["arms"].items():
        rows.append(f"| {a} | {s['mean_f']:.3f} | {s['missing_hops_hit_per_rep']} |")
    cmp_rows = ["| 比較 | 單位 W:L | Δ̄ [95% CI] | 雙尾 p | 題 W:L |", "|---|---|---|---|---|"]
    for name, c in list(p.items()) + list(doc["descriptive"].items()):
        label = c.get("pair", name)
        cmp_rows.append(f"| {name} {label} | {c['unit_W:L']} | {c['mean_unit_diff']:+.3f} "
                        f"[{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] | {c.get('p', float('nan')):.3g} "
                        f"| {c['question_W:L']} |")
    it = v["I"]
    it_close = it.get("close_e4_it_gd")
    it_line = (f"IT-GD−IT-D @7：{it['IT-GD−IT-D@7']['unit_W:L']}，Δ̄ {it['IT-GD−IT-D@7']['mean_unit_diff']:+.3f}"
               f" → {'作廢（指標自檢或 K 未過）' if it_close is None else '結案 E4／IT-GD' if it_close else '不結案'}"
               if it["available"] else "IT 報告未產生")
    return "\n".join([
        "# 圖譜最後一夜：步驟 1 結果（NEW82，探索性）", "",
        f"- G（圖譜主規則）：{verdict_word(v['G']['pass'])}（G1 {v['G']['G1_pass']}、G2 {v['G']['G2_pass']}、G3 {v['G']['G3_pass']}）→ {v['G']['reading']}",
        f"- O（歸因診斷）：{verdict_word(v['O']['pass'])} → {v['O']['reading']}",
        f"- M（多跳 QD）：{v['M']['reading']}",
        f"- I：{it_line}",
        f"- K：fallback {v['K']['fallbacks']}／每臂 {v['K']['n_per_arm']}，作廢臂 {v['K']['void_arms']}，refpairs {v['K']['refpairs_ok']}，3 次子查詢全同的題數 {v['K']['identical_reps']}",
        "", *rows, "", *cmp_rows, ""])


if __name__ == "__main__":
    sys.exit(main())

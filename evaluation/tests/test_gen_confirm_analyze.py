"""GEN confirmation set: the verdict and its sensitivities (analyze_g; prereg §1.3, §1.5, §9).

Synthetic rows only (made-up sids, layer ids and arm values; no question, card or answer text): the d vectors in
ascending pool sid order, both branches of the sign-flip test (exact up to 16 non-zero d, Monte Carlo beyond),
the +0.10 floor and its 1e-9 tolerance, H2 tested only after H1 passes, every §9 sentence verbatim against the
prereg and every branch of the verdict (stop, void, H1 fail and its two variants, H1 pass H2 fail and its two
variants, both pass, K3, the release clause, the score_any note), the sensitivities on hand-computed values,
the refusals (an unanswered check is never a void cause; f2.json's measures must agree), and K3: its boundary and
the copy of analyze_c.k3 equal to A's on A's stored rows (skipped when the store is not mounted). Every negative case
is one prereg rule (named by its section, or the review id it closes). Nothing calls Ollama or any LLM.
"""
from __future__ import annotations

import re
import sys
from fractions import Fraction
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import analyze_g as AG  # noqa: E402
import arms_g as A  # noqa: E402
import g_common as GC  # noqa: E402
import score_g as SG  # noqa: E402
from src import ab_stats  # noqa: E402
from test_gen_confirm_run import later_store_files_in_tmp  # noqa: E402,F401 (autouse: later store files in tmp)

A_SCORES = GC.STORE / "reports/kg_cards_20261018/A_confirm/scores.json"
STRATA = ("F1c5", "F1c11", "F5c5", "F5c11")
OK_RUN = [{"digest_before": GC.EXPECTED_DIGEST, "digest_after": GC.EXPECTED_DIGEST, "version_before": GC.OLLAMA_VERSION,
           "version_after": GC.OLLAMA_VERSION, "dry_run": False}]


def slot(i: int) -> dict:
    st = STRATA[i % 4]
    x, y = f"P{i % 5}", f"P{i % 5 + 2 + i % 3}"
    return {"sid": f"S{i:02d}", "stratum": st, "qtype": st[:2], "chapter": int(st[3:]), "d": 2 + i % 6, "x": x, "y": y,
            "pair": f"{x}>{y}", "persons": [x, f"P{i % 5 + 1}", y], "marker_required": i % 7 == 0,
            "homonym": i % 4 == 1, "shem_x": i % 13 == 0, "dup_gold": i % 9 == 0}


def rep(sid: str, arm: str, r: int, ok: bool, ok_any: bool | None = None, ff: bool = False) -> dict:
    return {"score": int(ok), "score_any": int(ok if ok_any is None else ok_any), "format_fail": ff, "trap": [],
            "flags": [], "truncated": False, "job_id": f"GC|{sid}|{arm}|{r}", "elapsed_s": 1.0}


def dataset(spec: list[dict], n_pool: int | None = None, cause: str = "failed") -> dict:
    """spec: per item {arm: correct reps of 3} (+ "fired", "any": {arm: lenient correct}); every pool slot after the
    items is attrition of ``cause``."""
    n_pool = n_pool or len(spec)
    pool = [slot(i) for i in range(n_pool)]
    rows, meta = {}, {}
    for i, sp in enumerate(spec):
        s = pool[i]
        sid = s["sid"]
        lenient = sp.get("any", {})
        reps = {f"{a}|{r}": rep(sid, a, r, r <= sp[a], r <= lenient.get(a, sp[a])) for a in A.ARMS for r in (1, 2, 3)}
        rows[sid] = {**s, "unit": sid, "reps": reps,
                     "mean": {a: SG.fx(Fraction(sp[a], 3)) for a in A.ARMS},
                     "mean_any": {a: SG.fx(Fraction(lenient.get(a, sp[a]), 3)) for a in A.ARMS}}
        fired = sp.get("fired", True)
        meta[sid] = {"item": sid, "sid": sid, "rule": {"fired": fired, "reason": "ok" if fired else "沒有年歲線索"},
                     "covered": fired, "wrong": False, "seeds_ok": fired, "carded": fired, "gref_job": not fired}
    counts = SG.arm_counts(rows)
    scores = {"items": rows, "missing_jobs": [], "counts": counts, "truncation": {a: c["truncated"] for a, c in counts.items()},
              "truncation_problems": [], "arm_means": {}, "gen_sha256": None}
    att = {c: [] for c in A.ATTRITION}
    att[cause] = [p["sid"] for p in pool[len(spec):]]
    frozen = {"n_target": n_pool, "attrition": att, "questions": [{"sid": p["sid"]} for p in pool[:len(spec)]]}
    items = [{**p, "id": p["sid"]} for p in pool[:len(spec)]]
    return {"scores": scores, "items": items, "meta": meta, "frozen": frozen, "pool": pool}


def run(ds: dict, **kw) -> dict:
    kw = {"run_meta": OK_RUN, "p2_near_miss": (0, 20), "measures": A.rule_measures(ds["meta"]), **kw}
    return AG.analyze(ds["scores"], ds["items"], ds["meta"], ds["frozen"], ds["pool"], **kw)


def arms(g: int, t: int, b: int, gref: int | None = None, **kw) -> dict:
    return {"G": g, "T-rows": t, "B0": b, "G-ref": g if gref is None else gref, **kw}


# ---------------------------------------------------------------- the d order and the test's two branches
def test_d_vectors_follow_the_pool_sid_order_and_the_items_must_too():
    ds = dataset([arms(3, 1, 0), arms(1, 1, 2), arms(2, 0, 0)])
    d = AG.d_by_sid(ds["scores"]["items"], [it["sid"] for it in ds["items"]], AG.H1)
    assert list(d) == ["S00", "S01", "S02"] and list(d.values()) == [1, Fraction(-1, 3), Fraction(2, 3)]
    with pytest.raises(ValueError, match="ascending"):
        AG.analyze(ds["scores"], ds["items"][::-1], ds["meta"], ds["frozen"], ds["pool"], run_meta=OK_RUN, p2_near_miss=(0, 20))
    with pytest.raises(ValueError, match="same questions"):
        AG.analyze(ds["scores"], ds["items"][:2], ds["meta"], ds["frozen"], ds["pool"], run_meta=OK_RUN, p2_near_miss=(0, 20))


def test_items_scores_meta_and_the_frozen_file_must_be_the_same_questions():
    """RUN-3 N19: the frozen file's questions, in its order, are the items, the scored rows and the meta."""
    ds = dataset([arms(3, 1, 0), arms(1, 1, 2), arms(2, 0, 0)])
    qs = ds["frozen"]["questions"]
    for frozen in ({**ds["frozen"], "questions": qs[:2]}, {**ds["frozen"], "questions": [qs[0], qs[2], qs[1]]}):
        with pytest.raises(ValueError, match="same questions"):
            run({**ds, "frozen": frozen})
    with pytest.raises(ValueError, match="same questions"):
        run({**ds, "meta": {k: v for k, v in ds["meta"].items() if k != "S01"}})


@pytest.mark.parametrize("n_nonzero", [9, 16, 17, 30])
def test_sign_flip_p_on_the_sid_ordered_d_in_both_branches(n_nonzero):
    spec = [arms(3 if i % 4 else 0, 1, 1 if i % 3 else 2) for i in range(n_nonzero)] + [arms(1, 1, 1)] * 5
    ds = dataset(spec)
    seq = AG.fixed_sequence(ds["items"], ds["scores"]["items"], ds["pool"])
    d = [float(x) for x in AG.d_by_sid(ds["scores"]["items"], [it["sid"] for it in ds["items"]], AG.H1).values()]
    assert seq["H1"]["p"] == ab_stats.sign_flip_p(d, seed=20261018) and seq["H1"]["exact"] == (n_nonzero <= 16)
    assert seq["H1"]["ci95"] == list(ab_stats.bootstrap_ci(d, 10000, seed=20261018))
    assert (seq["H1"]["W"] + seq["H1"]["L"], seq["H1"]["T"]) == (n_nonzero, 5) and seq["H1"]["n"] == len(spec)


def test_the_floor_and_its_tolerance():
    hit = dataset([arms(1, 1, 0)] * 9 + [arms(1, 1, 1)] * 21)            # Δ̄ = 9 × (1/3) / 30 = 0.10 exactly
    h1 = AG.fixed_sequence(hit["items"], hit["scores"]["items"], hit["pool"])["H1"]
    assert h1["delta"] == pytest.approx(0.1) and h1["p"] == 2 / 512 and h1["pass"]
    small = dataset([arms(1, 1, 0)] * 8 + [arms(1, 1, 1)] * 22)          # Δ̄ = 8/90 < 0.10, p = 2/256
    h1 = AG.fixed_sequence(small["items"], small["scores"]["items"], small["pool"])["H1"]
    assert not h1["pass"] and h1["sig_small"] and not h1["negative"] and h1["significant"]
    for delta, ok in ((0.1 - 5e-10, True), (0.1 - 2e-9, False)):
        assert AG.step({"p": 0.01, "delta": delta})["pass"] is ok
    assert AG.step({"p": 0.05, "delta": 0.5})["pass"] is False and AG.step({"p": None, "delta": 0.5})["pass"] is False


def test_h2_is_tested_only_after_h1_passes():
    fail = dataset([arms(1, 0, 1)] * 20)
    seq = AG.fixed_sequence(fail["items"], fail["scores"]["items"], fail["pool"])
    assert not seq["H1"]["pass"] and not seq["H2"]["tested"] and "p" not in seq["H2"] and seq["H2"]["delta"] > 0.3
    ok = dataset([arms(3, 0, 0)] * 20)
    seq = AG.fixed_sequence(ok["items"], ok["scores"]["items"], ok["pool"])
    assert seq["H1"]["pass"] and seq["H2"]["tested"] and seq["H2"]["pass"] and seq["H2"]["p"] < 0.05


def test_the_pool_weighted_mean():
    ds = dataset([arms(3, 0, 0), arms(0, 0, 0), arms(3, 0, 0), arms(3, 0, 3)], n_pool=8)
    pw = AG.fixed_sequence(ds["items"], ds["scores"]["items"], ds["pool"])["H1"]["pool_weighted"]
    assert pw["weights"] == {s: "1/4" for s in STRATA} and pw["strata_missing"] == []
    assert pw["delta"] == pytest.approx((1 + 0 + 1 + 0) / 4)
    ds = dataset([arms(3, 0, 0), arms(0, 0, 0), arms(3, 0, 0)], n_pool=8)
    pw = AG.fixed_sequence(ds["items"], ds["scores"]["items"], ds["pool"])["H1"]["pool_weighted"]
    assert pw["strata_missing"] == ["F5c11"] and pw["delta"] == pytest.approx(2 / 3)


def test_the_pool_weights_follow_unequal_stratum_sizes():
    """§1.3, §1.5-3 (RUN-3 N14): weights N_h/N with strata of 3, 3, 2, 2 slots."""
    ds = dataset([arms(3, 0, 0) if i % 4 == 0 else arms(0, 0, 0) for i in range(10)])
    pw = AG.fixed_sequence(ds["items"], ds["scores"]["items"], ds["pool"])["H1"]["pool_weighted"]
    assert pw["weights"] == {"F1c5": "3/10", "F1c11": "3/10", "F5c5": "1/5", "F5c11": "1/5"}
    assert pw["delta"] == pytest.approx(0.3) and pw["by_stratum"] == {"F1c5": 1.0, "F1c11": 0.0, "F5c5": 0.0, "F5c11": 0.0}


# ---------------------------------------------------------------- the sentences, verbatim
def test_every_sentence_template_is_the_prereg_text():
    text = (H / "prereg.md").read_text(encoding="utf-8")
    dots = {k: "…" for k in ("a", "d", "ci", "d1", "ci1", "d2", "ci2", "n", "power")}
    fill = {"stop": dict(rule="〈條目〉", value="〈值〉", state="〈未出題／未凍結／未跑〉"),
            "stop_g1": dict(r_card="k", r_wrong="m", n_v="n_v"), "stop_ka": dots,
            "void": dict(why="〈digest／Ollama 版本／截斷／缺漏 job〉"), "release": dict(k="k", n="20"),
            "lenient": dict(k="〈k〉", result="〈過／不過〉"),
            "h1_fail": {**dots, "pop": "58 個題位中寫成的 n 題"}, "h1_only": {**dots, "pop": "58 個年歲題位中寫成的 n 題"},
            "both": {**dots, "pop": "58 個年歲題位中寫成的 n 題"}}
    for key, tpl in AG.SENTENCE.items():
        s = tpl.format(**fill.get(key, {}))
        assert s in text, key
    assert AG.POP.format(n_target="n_target", n="n") in text                 # §9's full population wording


def test_no_file_of_this_track_writes_the_two_forbidden_phrases():
    files = [H / f for f in ("arms_g.py", "run_g.py", "score_g.py", "analyze_g.py", "f1_g.py", "f2_g.py")]
    files += [Path(__file__), *(Path(__file__).with_name(f"test_gen_confirm_{n}.py") for n in ("run", "gates", "smoke"))]
    bad = ("圖譜" + "有效", "圖譜" + "無效")
    assert not [f.name for f in files if any(b in f.read_text(encoding="utf-8") for b in bad)]


def test_stop_sentences():
    assert AG.stop_sentence("K-P", "預估 n＝40 的檢定力 0.65", "未出題") == \
        "依事先規則停止（K-P＝預估 n＝40 的檢定力 0.65），不構成無效證據；盲集未出題"
    assert AG.stop_sentence("K-Kay", "10 題刪 3 題", "未凍結").endswith("盲集未凍結")
    with pytest.raises(ValueError):
        AG.stop_sentence("K9", "x", "未跑")
    with pytest.raises(ValueError):
        AG.stop_sentence("K-a", "x", "沒跑")
    assert AG.g1_stop_sentence(35, 2, 50) == "依事先規則停止（G1：R_card＝35/50，R_wrong＝2/50），不構成無效證據；盲集未出題"
    assert AG.ka_stop_sentence(0.7, 48, 0.6512) == "依事先規則停止（K-a：a＝0.700，n＝48，檢定力＝0.651），不構成無效證據；盲集未跑"


# ---------------------------------------------------------------- the verdict's branches
FROZEN = {"n_target": 58, "attrition": {"unopened": [], "failed": ["S50", "S51"], "kay": ["S52"], "other_quantity": [],
                                        "dynasty_trigger": ["S53"], "cap_stopped": []},
          "questions": [{"sid": f"S{i:02d}"} for i in range(54)]}
MEAS = {"a_meas": {"k": 45, "n": 54, "frac": "5/6", "float": 45 / 54}}
NO_HARM = {"flag": False}


def h(p: float | None, delta: float, tested: bool = True) -> dict:
    t = {"tested": tested, "delta": delta, "ci95": [delta - 0.1, delta + 0.1], **({"p": p} if tested else {})}
    return {**t, **(AG.step(t) if tested else {"pass": False})}


def seq(h1: dict, h2: dict) -> dict:
    return {"H1": h1, "H2": h2}


def sentence(s: dict, harm: dict = NO_HARM, p2=(0, 20), notes=()) -> dict:
    return AG.verdict(s, [], harm, AG.facts(FROZEN, 54, MEAS, s), p2, list(notes))


def test_h1_fail_and_its_two_variants():
    pop = "58 個題位（依事先抽定的順序寫到第 58 位）中寫成的 54 題"
    base = (f"創世記年歲推導卡（規則觸發、規則種子）在盲集上未達事先登記的門檻（{pop}，規則出卡且含答案的比例 a＝0.833（45/54），"
            "Δ̄＝{d}〔規則棄權的題記 0〕，95% CI {ci}），記 null；創世記算術線結案")
    v = sentence(seq(h(0.30, 0.20), h(None, 0.1, False)))
    assert v["result"] == "H1 不過" and v["sentence"] == base.format(d="+0.200", ci="[+0.100, +0.300]")
    v = sentence(seq(h(0.01, -0.15), h(None, 0.1, False)))
    assert v["sentence"] == base.format(d="-0.150", ci="[-0.250, -0.050]") + "；且 G 顯著劣於同一段完整經文 context 不給卡"
    v = sentence(seq(h(0.01, 0.08), h(None, 0.1, False)))
    assert v["sentence"] == base.format(d="+0.080", ci="[-0.020, +0.180]") + "；顯著但未達事先定的最小效果"
    assert "母體：58 個題位（依事先抽定的順序寫到第 58 位）中寫成的 54 題" in v["facts"]
    for part in ("n_target＝58", "沒開寫 0", "沒寫成 2", "Kay 刪 1", "問了別的量 0", "prod 王朝觸發 1", "硬上限停筆 0",
                 "a＝0.833（45/54）", "H1（G−B0）Δ̄＝+0.080、95% CI [-0.020, +0.180]"):
        assert part in v["facts"], part
    assert "3 次都失敗" not in v["facts"]                  # D24: without freeze.json's whys, one 「沒寫成」 count


def test_failed_slots_are_split_by_why_and_only_attempts_is_three_failures():
    """§9 (D24): 「3 次都失敗」 is why attempts only; the closes after a dispute or Kay's page get their own labels."""
    import state_g as S
    assert set(AG.FAILED_LABEL) == set(S.FAILED_WHY) and AG.FAILED_LABEL["attempts"] == "3 次都失敗"
    f = AG.facts(FROZEN, 54, MEAS, None, {"attempts": 1, "kept_dispute": 1})
    assert "3 次都失敗 1、爭議後沒過 1、Kay 刪 1" in f["text"] and "沒寫成" not in f["text"]
    assert "Kay 之後沒過" not in f["text"] and f["failed_by_why"] == {"attempts": 1, "kept_dispute": 1}
    f = AG.facts(FROZEN, 54, MEAS, None, {"post_kay": 1, "late_dispute": 1})
    assert "沒開寫 0、3 次都失敗 0、Kay 之後沒過 1、Kay 之後又起爭議 1、Kay 刪 1" in f["text"]
    assert f["attrition"] == {"unopened": 0, "failed": 2, "kay": 1, "other_quantity": 0, "dynasty_trigger": 1,
                              "cap_stopped": 0}                                   # arms_g's six keys, unchanged
    for bad in ({"attempts": 1}, {"attempts": 2, "other": 0}, {"attempts": 3}):
        with pytest.raises(ValueError, match="not a split"):
            AG.facts(FROZEN, 54, MEAS, None, bad)


def test_failed_breakdown_reads_freeze_json_of_these_questions_only(tmp_path):
    p = tmp_path / "freeze.json"
    assert AG.failed_breakdown("q" * 64, p) is None
    GC.write_json(p, {"questions_frozen_sha256": "q" * 64, "counts": {"failed_by_why": {"attempts": 2, "post_kay": 1}}})
    assert AG.failed_breakdown("q" * 64, p) == {"attempts": 2, "post_kay": 1}
    with pytest.raises(SystemExit, match="other questions"):
        AG.failed_breakdown("r" * 64, p)


def test_a_void_line_reports_its_sentence_only(tmp_path):
    """§9 (D5, D6): a void record (void_g) gives a report with the void sentence and nothing measured."""
    for why, s in (("parity", "作廢（prompt 對等），不構成任何方向的證據"), ("truncation", "作廢（截斷），不構成任何方向的證據")):
        rec = {"why": why, "label": AG.VOID_WHY[why], "anchor": "某行", "sentence": AG.SENTENCE["void"].format(
            why=AG.VOID_WHY[why]), "t": "t"}
        rep = AG.void_report(rec)
        assert rep["verdict"] == {"result": "作廢", "sentence": s, "notes": [], "void": [AG.VOID_WHY[why]]}
        assert rep["void_only"] and "sequence" not in rep and "facts" not in rep
        js, md = AG.write_report(rep, tmp_path / why)
        assert GC.read_json(js) == rep and md.read_text(encoding="utf-8").count("- ") == 1 and s in md.read_text("utf-8")


def test_h1_pass_h2_fail_and_its_two_variants_and_k3_not_twice():
    v = sentence(seq(h(0.001, 0.30), h(0.40, 0.05)))
    s = v["sentence"]
    assert v["result"] == "H1 過、H2 不過" and s.startswith(
        "在創世記 5、11 章 stage-0 未用過的 58 個年歲題位（依事先抽定的順序寫到第 58 位）中寫成的 54 題（X 幾歲時 Y 出生")
    assert "顯著高於同一段完整經文 context 不給卡（a＝0.833（45/54），Δ̄＝+0.300〔棄權記 0〕，95% CI [+0.200, +0.400]）" in s
    assert s.endswith("不計為圖譜增益；創世記算術線結案，不談 prod")
    assert sentence(seq(h(0.001, 0.30), h(0.01, -0.2)))["sentence"].endswith("不談 prod；且 G 顯著劣於給同一批層列、不給推導行")
    assert sentence(seq(h(0.001, 0.30), h(0.01, 0.05)))["sentence"].endswith("不談 prod；H2 顯著但未達事先定的最小效果")
    assert sentence(seq(h(0.001, 0.30), h(0.40, 0.05)), harm={"flag": True})["sentence"].count("不談 prod") == 1


def test_both_pass_k3_release_and_lenient_notes():
    v = sentence(seq(h(0.001, 0.30), h(0.002, 0.25)))
    assert v["result"] == "H1、H2 皆過" and "（Δ̄＝+0.300，95% CI [+0.200, +0.400]），也高於給同一批層列、不給推導行（Δ̄＝+0.250，" \
        "95% CI [+0.150, +0.350]）；Δ̄ 把規則棄權的題記為 0，規則出卡且含答案的比例 a＝0.833（45/54）（受限寫法下量得" in v["sentence"]
    assert v["sentence"].endswith("結論只及於這些題、這個出題流程、這個模型與這個 context")
    v = sentence(seq(h(0.001, 0.30), h(0.002, 0.25)), harm={"flag": True}, p2=(2, 20), notes=["寬鬆計分下 H2不過"])
    assert v["sentence"].endswith("context；不談 prod；觸發精確度未證明（P2 近似題誤觸發 2/20），不談 prod 接線")
    assert v["notes"] == ["寬鬆計分下 H2不過"] and v["k3_flag"] and v["release_clause"]
    assert not sentence(seq(h(0.001, 0.30), h(0.002, 0.25)), p2=(1, 20))["release_clause"]
    assert AG.release_due((2, 20)) and not AG.release_due((1, 20)) and AG.release_due((1, 19))


def test_void_comes_before_the_sequence():
    v = AG.verdict(seq(h(0.001, 0.30), h(0.002, 0.25)), ["digest", "截斷"], {"flag": True}, AG.facts(FROZEN, 54, MEAS, None),
                   (5, 20), [])
    assert v["result"] == "作廢" and v["sentence"] == "作廢（digest、截斷），不構成任何方向的證據" and "a＝0.833" in v["facts"]


def test_dry_run_marks_every_sentence():
    v = AG.mark_dry_run(sentence(seq(h(0.30, 0.2), h(None, 0.1, False)), notes=["寬鬆計分下 H1過"]))
    assert v["sentence"].startswith(AG.DRY_RUN) and v["notes"][0].startswith(AG.DRY_RUN) and v["result"].startswith("dry_run:")


# ---------------------------------------------------------------- the report end to end, sensitivities, refusals
@pytest.fixture(scope="module")
def report():
    spec = [arms(3, 2 if i % 2 else 3, 0, gref=3) for i in range(14)] + [arms(1, 1, 1, gref=3, fired=False)] * 2 + \
           [arms(0, 0, 3, any={"G": 3})] * 2
    ds = dataset(spec, n_pool=20)
    return ds, run(ds)


def test_report_end_to_end_h1_passes_and_h2_is_tested(report, tmp_path):
    ds, rep = report
    assert rep["sequence"]["H1"]["pass"] and rep["sequence"]["H2"]["tested"] and rep["n"] == 18
    assert rep["verdict"]["result"] in ("H1 過、H2 不過", "H1、H2 皆過") and not rep["dry_run"]
    m = rep["measurements"]
    assert m["rule"]["abstained"] == ["S14", "S15"] and m["f2_agrees"] is True and m["over_120s"]["G"] == 0
    assert AG.render_md(rep).startswith("# GEN 確認集報告")
    js, md = AG.write_report(rep, tmp_path)                               # review m06: not the void-only page
    text = md.read_text(encoding="utf-8")
    assert GC.read_json(js) == rep and text == AG.render_md(rep) and f"- {rep['verdict']['facts']}\n" in text
    assert "## 檢定（§1.3，固定順序）" in text and "## 敏感度（§1.5，只描述）" in text


def test_sensitivities_on_hand_values(report):
    ds, rep = report
    s1 = rep["sensitivities"]["H1"]
    d = {it["sid"]: x for it, x in zip(ds["items"], [1] * 14 + [0, 0] + [-1, -1])}
    assert s1["worst_case"]["n_outside"] == 2 and s1["worst_case"]["by_cause"]["failed"] == 2
    assert s1["worst_case"]["minus_one"]["delta"] == pytest.approx((sum(d.values()) - 2) / 20)
    strat = {st: [d[it["sid"]] for it in ds["items"] if it["stratum"] == st] for st in STRATA}
    missing = [p["stratum"] for p in ds["pool"][18:]]
    want = (sum(d.values()) + sum(sum(strat[st]) / len(strat[st]) for st in missing)) / 20
    assert s1["worst_case"]["stratum_mean"]["delta"] == pytest.approx(want)
    xs = {}
    for it in ds["items"]:
        xs.setdefault(it["x"], []).append(d[it["sid"]])
    assert s1["cluster_x"]["n_clusters"] == len(xs) and s1["cluster_x"]["delta"] == pytest.approx(
        sum(sum(v) / len(v) for v in xs.values()) / len(xs))
    assert s1["cluster_pair"]["n_clusters"] == len({it["pair"] for it in ds["items"]})
    loo = s1["leave_one_person_out"]
    persons = sorted({p for it in ds["items"] for p in it["persons"]})
    assert loo["n_persons"] == len(persons) and loo["min_delta"]["delta"] == min(r["delta"] for r in loo["by_person"])
    assert loo["max_p"]["p"] == max(r["p"] for r in loo["by_person"])
    assert s1["triggered"]["n"] == 16 and s1["triggered"]["delta"] == pytest.approx(12 / 16)
    assert s1["strata"]["F1"]["n"] + s1["strata"]["F5"]["n"] == 18 and s1["strata"]["F5_d2_4"]["n"] + \
        s1["strata"]["F5_d5_up"]["n"] == s1["strata"]["F5"]["n"]
    assert s1["strata"]["marker_required"]["n"] + s1["strata"]["not_marker_required"]["n"] == 18
    flags = ("marker_required", "homonym", "shem_x", "dup_gold")                      # §1.5-5 (RUN-3 N21)
    assert set(s1["strata"]) == {"F1", "F5", "chapter_5", "chapter_11", *STRATA, "F5_d2_4", "F5_d5_up",
                                 *flags, *(f"not_{f}" for f in flags)}
    for f in flags:
        assert s1["strata"][f]["sids"] == [it["sid"] for it in ds["items"] if it[f]]
    gref = rep["sensitivities"]["G-ref−G"]
    assert gref["all"]["delta"] == pytest.approx(2 * (2 / 3) / 18) and gref["gref_ran"]["n"] == 2
    assert gref["gref_ran"]["delta"] == pytest.approx(2 / 3)


def test_leave_one_person_out_drops_every_question_through_the_person():
    """§1.5-2 (RUN-3 N15) by hand: paths P0-P1-P2, P1-P2-P4, P2-P3-P6; d = 1, 0, −1/3."""
    ds = dataset([arms(3, 0, 0), arms(1, 0, 1), arms(0, 0, 1)])
    assert [it["persons"] for it in ds["items"]] == [["P0", "P1", "P2"], ["P1", "P2", "P4"], ["P2", "P3", "P6"]]
    d = AG.d_by_sid(ds["scores"]["items"], [it["sid"] for it in ds["items"]], AG.H1)
    loo = AG.leave_one_person_out(ds["items"], d, True)
    assert {r["person"]: r["delta"] for r in loo["by_person"]} == pytest.approx(
        {"P0": -1 / 6, "P1": -1 / 3, "P3": 1 / 2, "P4": 1 / 3, "P6": 1 / 2})
    assert {r["person"]: r["n"] for r in loo["by_person"]} == {"P0": 2, "P1": 1, "P3": 2, "P4": 2, "P6": 2}
    assert loo["min_delta"]["person"] == "P1" and loo["n_persons"] == 5


def test_h2_sensitivities_carry_no_p_when_h2_was_not_tested():
    ds = dataset([arms(1, 0, 1)] * 6 + [arms(2, 0, 2)] * 6)
    rep = run(ds)
    s2 = rep["sensitivities"]["H2"]
    assert not rep["sequence"]["H2"]["tested"] and not s2["with_p"]
    for t in (s2["cluster_x"], s2["worst_case"]["minus_one"], s2["triggered"], *s2["strata"].values()):
        assert "p" not in t
    assert s2["leave_one_person_out"]["max_p"] is None and "p" in rep["sensitivities"]["H1"]["cluster_x"]


def test_score_any_flips_a_step_into_a_note(report):
    ds = dataset([arms(0, 0, 0, any={"G": 3})] * 12)
    rep = run(ds)
    assert rep["verdict"]["result"] == "H1 不過" and rep["verdict"]["notes"] == ["寬鬆計分下 H1過", "寬鬆計分下 H2過"]
    assert rep["score_any"]["sequence"]["H1"]["pass"]


def test_void_reasons_and_refusals():
    ds = dataset([arms(3, 0, 0)] * 6)
    bad_digest = [dict(OK_RUN[0], digest_after="0" * 64)]
    assert run(ds, run_meta=bad_digest)["verdict"]["sentence"] == "作廢（digest），不構成任何方向的證據"
    assert run(ds, run_meta=[dict(OK_RUN[0], version_after="0.33.0")])["verdict"]["sentence"].startswith("作廢（Ollama 版本）")
    ds["scores"]["truncation_problems"] = ["G truncated 2 times"]
    assert run(ds)["verdict"]["sentence"].startswith("作廢（截斷）")
    ds["scores"]["truncation_problems"], ds["scores"]["missing_jobs"] = [], ["GC|S00|G|1"]
    with pytest.raises(SystemExit, match="jobs missing"):
        run(ds)
    assert run(ds, jobs_unrecoverable=True)["verdict"]["sentence"] == "作廢（缺漏 job），不構成任何方向的證據"
    ds["scores"]["missing_jobs"] = []
    with pytest.raises(SystemExit, match="run_meta"):
        run(ds, run_meta=None)
    with pytest.raises(SystemExit, match="checks without an answer"):
        run(ds, run_meta=[dict(OK_RUN[0], version_after=None)])
    with pytest.raises(SystemExit, match="P2 near-miss"):
        run(ds, p2_near_miss=None)
    dry = run(ds, run_meta=[dict(OK_RUN[0], dry_run=True)], p2_near_miss=None)
    assert dry["dry_run"] and dry["p2_near_miss"] == [0, 20] and dry["verdict"]["sentence"].startswith(AG.DRY_RUN)


def test_an_unanswered_check_is_never_a_void_cause():
    """§4.5 (RUN-11): a check without an answer is refused (resume to check again), with or without
    jobs_unrecoverable; only a known mismatch voids."""
    ds = dataset([arms(3, 0, 0)] * 6)
    ds["scores"]["missing_jobs"] = ["GC|S00|G|1"]
    unanswered = [dict(OK_RUN[0], digest_after=None, version_after=None)]
    with pytest.raises(SystemExit, match="checks without an answer"):
        run(ds, run_meta=unanswered, jobs_unrecoverable=True)
    assert AG.void_reasons(ds["scores"], unanswered) == ["缺漏 job"]
    mixed = [dict(OK_RUN[0], digest_after=None, version_after="0.33.0")]
    assert run(ds, run_meta=mixed, jobs_unrecoverable=True)["verdict"]["sentence"] == \
        "作廢（Ollama 版本、缺漏 job），不構成任何方向的證據"


def test_scores_of_another_generation_file_are_refused(tmp_path):
    """RUN-3 N12: a report is made only from the scored state of the generation file."""
    ds = dataset([arms(3, 0, 0)] * 6)
    (tmp_path / SG.GEN).write_text('{"job_id": "x"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="current generation file"):
        run(ds, gen_dir=tmp_path)
    ds["scores"]["gen_sha256"] = SG.gen_sha256(tmp_path)
    assert run(ds, gen_dir=tmp_path)["inputs"]["gen_checked"]


def test_measures_from_f2_must_agree_with_the_build():
    """§5.5 (RUN-9c): a formal report needs f2.json's measures, equal to the build's; a dry run may go without."""
    ds = dataset([arms(3, 0, 0)] * 6)
    mine = A.rule_measures(ds["meta"])
    assert run(ds, measures=mine)["measurements"]["f2_agrees"] is True
    with pytest.raises(SystemExit, match="f2.json's measures differ"):
        run(ds, measures={**mine, "a_meas": {"k": 0}})
    with pytest.raises(SystemExit, match="f2.json's measures are needed"):
        run(ds, measures=None)
    dry = run(ds, measures=None, run_meta=[dict(OK_RUN[0], dry_run=True)])
    assert dry["measurements"]["f2_agrees"] is None


# ---------------------------------------------------------------- K3
def test_k3_flags_g_wrong_rate_above_b0s_by_more_than_five_points():
    ds = dataset([arms(0, 3, 2)] * 6)
    harm = AG.k3(ds["scores"]["items"])
    assert harm["rate"]["G"] == 1.0 and harm["rate"]["B0"] == pytest.approx(1 / 3) and harm["flag"]
    assert harm["unit_delta"] == pytest.approx(2 / 3) and harm["n_units"] == 6
    ds = dataset([arms(3, 0, 3)] * 6)
    assert not AG.k3(ds["scores"]["items"])["flag"]
    rep = run(dataset([arms(0, 3, 2)] * 6))
    assert rep["verdict"]["k3_flag"] and rep["verdict"]["sentence"].endswith("；不談 prod")


def test_k3_flags_only_strictly_above_five_points():
    """§1.3 K3 (RUN-3 N5): > +0.05, so exactly +0.05 (3 wrong G calls of 60) is no flag; 4 of 60 is."""
    edge = dataset([arms(0, 3, 3)] + [arms(3, 3, 3)] * 19)
    k = AG.k3(edge["scores"]["items"])
    assert k["rate"]["B0"] == 0 and k["diff"] == 0.05 and not k["flag"]
    over = dataset([arms(0, 3, 3), arms(2, 3, 3)] + [arms(3, 3, 3)] * 18)
    assert AG.k3(over["scores"]["items"])["flag"]


def test_k3_counts_format_failures_as_not_wrong_and_substitutes_as_g():
    ds = dataset([arms(0, 0, 0)] * 2)
    rows = ds["scores"]["items"]
    for r in rows.values():
        for k, v in r["reps"].items():
            if k.startswith("G|"):
                r["reps"][k] = dict(v, format_fail=True)
    assert AG.k3(rows)["rate"]["G"] == 0.0
    sid = next(iter(rows))
    rows[sid]["reps"]["G|1"] = dict(rows[sid]["reps"]["B0|1"], substituted_from="B0")
    assert AG.k3(rows)["rate"]["G"] == pytest.approx(1 / 6)


@pytest.mark.skipif(not A_SCORES.is_file(), reason=f"experiment A's store not mounted ({A_SCORES})")
def test_the_k3_copy_equals_analyze_c_k3_on_as_stored_rows():
    import analyze_c
    from c_common import ARMS as A_ARMS
    rows = GC.read_json(A_SCORES)["items"]
    assert AG.k3(rows, arms=A_ARMS, g="G-auto", base="T-canon") == analyze_c.k3(rows)
    assert AG.unit_test({"u1": 0.5, "u2": -0.25, "u3": 0.0}) == analyze_c.unit_test({"u1": 0.5, "u2": -0.25, "u3": 0.0})


def test_the_numbers_render_as_the_prereg_writes_them():
    t = {"delta": 0.1234, "ci95": [-0.01, 0.2]}
    assert (AG.d_text(t), AG.ci_text(t)) == ("+0.123", "[-0.010, +0.200]")
    assert AG.ci_text({"ci95": [None, None]}) == "—" and re.fullmatch(r"\d\.\d{3}（\d+/\d+）", AG.a_text(MEAS))

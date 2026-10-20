"""Ordered-chain arithmetic stage-0 verdict and report (analyze_x.py; prereg §7 K-S0, §8 描述, §1 截斷).

The verdict grid uses exact Fractions only. The synthetic runs are made-up items with arithmetic keys (no
question text, no scripture), made-up generations written to tmp_path and scored by score_x; SYNC uses the toy
two-kingdom View of test_arith_stage0_keys. The store-backed tests build the 52 items in memory (nothing is
written) and skip without the store. Ollama is never called.
"""

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import x_common as X  # noqa: E402
import analyze_x as A  # noqa: E402
import power_x as P  # noqa: E402
import score_x as S  # noqa: E402
from test_arith_stage0_keys import sync_item, toy_view  # noqa: E402

NUM_CTX = 131072
K0_OK = {k: {"pass": True} for k in A.K0_KEYS}
RUN_OK = {"digest_before": X.EXPECTED_DIGEST, "digest_after": X.EXPECTED_DIGEST,
          "version_before": "0.0.test", "version_after": "0.0.test"}
Fr = Fraction


# ---------------------------------------------------------------- synthetic runs
def item(iid, family, qtype, gold=50, **extra):
    classes = ["Y"] if qtype in ("S5", "F3") else ["A", "Y"]
    base = {"id": iid, "family": family, "qtype": qtype, "question": "QSENTINEL",
            "keys": [{"type": "arith", "value": gold, "classes": classes, "ordinal": qtype == "F3"}],
            "distractors": [{"value": gold - 1, "kind": "off_by_one"}], "nested": False,
            "tcanon_complete": None if family == "GEN" else True}
    return {**base, **extra}


def answers_of(it, spec, reps):
    """spec: number of correct reps (the first ones) or the reps' answers (None = no answer line)."""
    if isinstance(spec, list):
        return spec
    unit = "年" if it["keys"][0]["classes"][0] == "Y" else "歲"
    g = it["keys"][0]["value"]
    return [f"共{g}{unit}整" if r < spec else f"{g - 1}{unit}" for r in range(reps)]


PROMPT = {"G": 1000, "T-rows": 700, "T-canon": 900, "B0": 500, "B0p": 100}


def run(tmp_path, spec, trunc=(), skip=(), VR=None):
    """spec: [(item, {arm: hits or answers})]; returns (items, scores, records)."""
    jobs, recs, items = [], [], []
    for it, arms in spec:
        items.append(it)
        for arm in A.expected_arms(it["family"]):
            reps = X.REPS_BY_ARM[arm]
            for rep, ans in enumerate(answers_of(it, arms.get(arm, 0), reps), 1):
                jid = f"X|{it['id']}|{arm}|{rep}"
                jobs.append({"job_id": jid, "item": it["id"], "arm": arm, "rep": rep})
                if (it["id"], arm, rep) in skip:
                    continue
                recs.append({"type": "answer", "job_id": jid, "item": it["id"], "arm": arm, "rep": rep,
                             "content": "沒有答案行" if ans is None else f"推理略。\n答案：{ans}",
                             "prompt_eval_count": PROMPT[arm], "eval_count": 300, "elapsed_s": 2.0,
                             "done_reason": "length" if (it["id"], arm, rep) in trunc else "stop"})
    tmp_path.mkdir(parents=True, exist_ok=True)
    with (tmp_path / "gen_arms.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    scores = S.score_all(tmp_path, items, jobs, num_ctx=NUM_CTX, VR=VR)
    return items, scores, {r["job_id"]: r for r in recs}


def meta(items, covered=True):
    return {it["id"]: {"covered": covered, "dropped_rows": 0, "dropped_lines": 0,
                       "block_chars": {"G": 500, "T-rows": 150, "B0": 0,
                                       **({} if it["family"] == "GEN" else {"T-canon": 880}),
                                       **({"B0p": 0} if it["family"] == "GEN" else {})}} for it in items}


def go(items, scores, records=None, **kw):
    kw = {"k0": K0_OK, "run_meta": RUN_OK, "nsim": 4, **kw}
    return A.analyze(scores, items, meta(items), records=records, **kw)


DYN2 = [(item("S5_01", "DYN", "S5", L=3, nested=True), {"G": 3}),
        (item("S5_02", "DYN", "S5", L=4, tcanon_complete=False), {"G": 3})]          # pG 1, pR 0, pC 0: pass
S6_1 = [(item("S6_01", "S6", "S6"), {"G": 3, "T-rows": 1})]
GEN5 = [(item("F1_01", "GEN", "F1", chapter=5), {"G": 3, "T-rows": 1, "B0p": 1}),
        (item("F1_02", "GEN", "F1", chapter=11), {"G": 3, "T-rows": 1}),
        (item("F3_01", "GEN", "F3", chapter=11), {"G": 2, "T-rows": 1, "B0p": 1}),
        (item("F3_02", "GEN", "F3", chapter=11), {"G": 2, "T-rows": 1}),
        (item("F5_01", "GEN", "F5", chapter=5), {"G": 2})]     # pG 12/15, pR 4/15, pB 0: gap2 8/15, gray


@pytest.fixture
def base(tmp_path):
    return run(tmp_path, DYN2 + S6_1 + GEN5)


# ---------------------------------------------------------------- §7-1..3 on exact Fractions
def oracle(g2, g1, pr):
    """prereg §7 as written: exactly one of rules 1–3 holds."""
    stop = g2 < Fr("0.45") or g1 < Fr("0.45") or pr >= Fr("0.40")
    passed = g2 >= Fr("0.60") and g1 >= Fr("0.45") and pr < Fr("0.40")
    gray = Fr("0.45") <= g2 < Fr("0.60") and g1 >= Fr("0.45") and pr < Fr("0.40")
    assert stop + passed + gray == 1
    return "stop" if stop else "pass" if passed else "gray"


E = Fr(1, 1000)
GAP2 = [Fr(-1), Fr(0), Fr("0.44"), Fr("0.45") - E, Fr("0.45"), Fr("0.45") + E, Fr("0.5"), Fr("0.6") - E, Fr("0.6"),
        Fr("0.6") + E, Fr(1)]
GAP1 = [Fr("-0.2"), Fr("0.44"), Fr("0.45") - E, Fr("0.45"), Fr("0.45") + E, Fr(1)]
PR = [Fr(0), Fr("0.39"), Fr("0.40") - E, Fr("0.40"), Fr("0.40") + E, Fr("0.65"), Fr(1)]


@pytest.mark.parametrize("g2", GAP2)
def test_verdict_grid_with_boundaries(g2):
    for g1 in GAP1:
        for pr in PR:
            assert A.judge(g2, g1, pr)["category"] == oracle(g2, g1, pr), (g2, g1, pr)


def test_verdict_grid_on_the_values_a_14_item_family_can_take():
    """DYN: 14 items × 3 calls, every value is k/42."""
    for a in range(-42, 43):
        for b in (17, 18, 19, 20, 42):
            for c in range(0, 43):
                g2, g1, pr = Fr(a, 42), Fr(b, 42), Fr(c, 42)
                assert A.judge(g2, g1, pr)["category"] == oracle(g2, g1, pr)


@pytest.mark.parametrize("g2,g1,pr,want,clauses", [
    ("0.45", "0.45", "0.39", "gray", []),            # +0.45 is not < +0.45 (stop) and is ≥ +0.45 (gray)
    ("0.60", "0.45", "0.39", "pass", []),            # +0.60 is ≥ +0.60: pass
    ("0.5999", "0.9", "0", "gray", []),
    ("0.4499", "0.9", "0", "stop", ["gap2"]),
    ("0.9", "0.4499", "0", "stop", ["gap1"]),
    ("0.9", "0.9", "0.40", "stop", ["pR"]),          # pR 0.40 is ≥ 0.40: stop
    ("0.9", "0.9", "0.3999", "pass", []),
    ("0.1", "0.1", "0.5", "stop", ["gap2", "gap1", "pR"]),
])
def test_exact_boundaries(g2, g1, pr, want, clauses):
    r = A.judge(Fr(g2), Fr(g1), Fr(pr))
    assert (r["category"], r["clauses"]) == (want, clauses)


def test_fractions_are_exact_where_floats_are_not():
    g2 = Fr(19, 20) - Fr(1, 2)
    assert g2 == Fr(9, 20) and 0.95 - 0.5 < 0.45                  # the float would stop
    assert A.judge(g2, Fr(9, 20), Fr(0))["category"] == "gray"


def test_floats_are_refused():
    with pytest.raises(TypeError):
        A.judge(0.5, Fr(1), Fr(0))
    with pytest.raises(TypeError):
        A.frac(0.5)
    with pytest.raises(TypeError):
        A.frac(True)
    assert A.frac({"frac": "7/12", "float": 0.58}) == Fr(7, 12) and A.frac("1/3") == Fr(1, 3) and A.frac(None) is None


def test_undefined_values_have_no_category():
    assert A.judge(None, Fr(1), Fr(0))["category"] is None


# ---------------------------------------------------------------- §7-6 sentences
def prereg_sentences():
    text = X.PREREG.read_text(encoding="utf-8")
    sec = text[text.index("6. **結果措辭**"):text.index("## 8.")]
    return re.findall(r"^\s*- 「(.+?)」", sec, re.M)


def test_outcome_sentences_are_the_preregs_verbatim():
    s = A.SENTENCE
    mine = [s["stop"].format(why="…"), s["pass"], s["gray"], s["gray_not_authorized"],
            s["pilot_stop"].format(pR="…", gap="…"), s["pilot_pass"], s["void"].format(family="〈族〉", why="K0-〈n〉")]
    assert prereg_sentences() == mine


def test_stop_sentence_names_the_clauses_with_exact_values():
    v = A.family_values({"G": Fr(2, 3), "T-rows": Fr(2, 9), "T-canon": Fr(0), "B0": Fr(0)}, "DYN")
    o = A.outcome("DYN", "stop", v, A.judge(v["gap2"], v["gap1"], v["pR"])["clauses"], [], None, None)
    assert o == {"status": "stop", "sentence": "依事先規則停止（第 1 條：gap2＝+0.444（4/9）<+0.45），不構成無效證據"}
    v = A.family_values({"G": Fr(1), "T-rows": Fr(1, 2), "T-canon": Fr(0)}, "DYN")
    o = A.outcome("DYN", "stop", v, ["pR"], [], None, None)
    assert o["sentence"] == "依事先規則停止（第 1 條：pR＝0.500（1/2）≥0.40），不構成無效證據"


# ---------------------------------------------------------------- a whole run
def test_pass_gray_and_described_families(base):
    items, scores, recs = base
    rep = go(items, scores, recs)
    d, g = rep["verdicts"]["DYN"], rep["verdicts"]["GEN"]
    assert (d["status"], d["sentence"]) == ("pass", A.SENTENCE["pass"])
    assert d["values"]["gap2"]["frac"] == "1" and d["values"]["pC_arm"] == "T-canon"
    assert (g["status"], g["sentence"]) == ("gray", A.SENTENCE["gray"])
    assert {k: g["values"][k]["frac"] for k in ("pG", "pR", "pC", "pB", "gap2", "gap1")} == {
        "pG": "4/5", "pR": "4/15", "pC": "0", "pB": "0", "gap2": "8/15", "gap1": "4/5"}   # GEN: pC := pB
    assert g["values"]["pC_arm"] == "B0"
    assert set(rep["sentences"]) == {"DYN", "GEN"} and rep["described"] == {"S6": {"sentence": None, "void": []}}
    assert rep["calls"]["expected"] == 3 * 4 * 3 + 5 * 3 * 3 + 5 and rep["calls"]["missing_calls"] == []
    json.dumps(rep, ensure_ascii=False)


def test_gen_stop_when_gap1_against_b0_is_small(tmp_path):
    spec = [(it, {**arms, "B0": 3}) for it, arms in GEN5]          # pB 1: gap1 = pG − pB < 0
    items, scores, _ = run(tmp_path, DYN2 + spec)
    g = go(items, scores)["verdicts"]["GEN"]
    assert g["status"] == "stop" and g["rule"]["clauses"] == ["gap1"]


def test_exactly_045_over_20_items_is_gray(tmp_path):
    g_hits = [3] * 10 + [2] * 10                 # pG 50/60
    r_hits = [2] * 3 + [1] * 17                  # pR 23/60 < 0.40; gap2 27/60 = 0.45 exactly
    spec = [(item(f"S5_{i:02d}", "DYN", "S5", L=3), {"G": g, "T-rows": r}) for i, (g, r) in enumerate(zip(g_hits, r_hits))]
    items, scores, _ = run(tmp_path, spec)
    v = go(items, scores)["verdicts"]["DYN"]
    assert A.frac(v["values"]["gap2"]) == Fr(9, 20) and v["status"] == "gray"


def test_exactly_060_is_pass(tmp_path):
    spec = [(item(f"S5_{i:02d}", "DYN", "S5", L=3), {"G": g, "T-rows": r})
            for i, (g, r) in enumerate(zip([3, 3, 2, 2, 2], [1, 1, 1, 0, 0]))]   # pG 12/15, pR 3/15
    items, scores, _ = run(tmp_path, spec)
    v = go(items, scores)["verdicts"]["DYN"]
    assert A.frac(v["values"]["gap2"]) == Fr(3, 5) and v["status"] == "pass"


# ---------------------------------------------------------------- gray: Kay's blind-pilot decision (§7-3)
@pytest.mark.parametrize("auth,status,sentence", [
    (None, "gray", "gray"), (False, "gray_not_authorized", "gray_not_authorized"),
    ({"GEN": False}, "gray_not_authorized", "gray_not_authorized"), ({"DYN": True}, "gray", "gray"),
    (True, "gray_pilot_pending", "gray"), ({"GEN": True}, "gray_pilot_pending", "gray"),
])
def test_gray_with_and_without_pilot_authorization(base, auth, status, sentence):
    items, scores, _ = base
    g = go(items, scores, pilot_authorized=auth)["verdicts"]["GEN"]
    assert (g["status"], g["sentence"]) == (status, A.SENTENCE[sentence])


@pytest.mark.parametrize("pr,gap,status,sentence", [
    ("13/20", "1/2", "pilot_stop", "盲 pilot 依事先規則停止（pR＝0.650／gap＝+0.500），不構成無效證據"),
    ("16/25", "6/25", "pilot_stop", "盲 pilot 依事先規則停止（pR＝0.640／gap＝+0.240），不構成無效證據"),
    ("16/25", "1/4", "pilot_pass", "盲 pilot 通過，可以請 Kay 授權確認集"),       # 0.64 < 0.65, 0.25 not < 0.25
])
def test_blind_pilot_rules(base, pr, gap, status, sentence):
    items, scores, _ = base
    g = go(items, scores, pilot_authorized=True, pilot={"GEN": {"pR": pr, "gap": gap}})["verdicts"]["GEN"]
    assert (g["status"], g["sentence"]) == (status, sentence)


@pytest.mark.parametrize("auth,pilot", [(None, {"GEN": {"pR": "0", "gap": "1"}}), (False, {"GEN": {"pR": "0", "gap": "1"}}),
                                        (True, {"DYN": {"pR": "0", "gap": "1"}}), (True, {"S6": {"pR": "0", "gap": "1"}})])
def test_pilot_results_need_a_gray_family_and_authorization(base, auth, pilot):
    items, scores, _ = base
    with pytest.raises(ValueError):
        go(items, scores, pilot_authorized=auth, pilot=pilot)


def test_pilot_values_must_be_exact(base):
    items, scores, _ = base
    with pytest.raises(TypeError):
        go(items, scores, pilot_authorized=True, pilot={"GEN": {"pR": 0.3, "gap": 0.5}})


# ---------------------------------------------------------------- 作廢 (§7-6)
def k0_with(**bad):
    return {**K0_OK, **{k.replace("_", "-"): v for k, v in bad.items()}}


@pytest.mark.parametrize("k0,want", [
    (k0_with(K0_1={"pass": False}), {"DYN": ["K0-1"], "S6": ["K0-1"], "SYNC": ["K0-1"], "GEN": []}),
    (k0_with(K0_2={"pass": False}), {"DYN": [], "S6": [], "SYNC": [], "GEN": ["K0-2"]}),
    (k0_with(K0_3={"pass": True, "dyn": False, "gen": True}), {"DYN": ["K0-3"], "S6": ["K0-3"], "SYNC": ["K0-3"], "GEN": []}),
    (k0_with(K0_3={"pass": True, "dyn": True, "gen": False}), {"DYN": [], "S6": [], "SYNC": [], "GEN": ["K0-3"]}),
    (k0_with(K0_3={"pass": False}), {"DYN": ["K0-3"], "S6": ["K0-3"], "SYNC": ["K0-3"], "GEN": ["K0-3"]}),
    (k0_with(K0_3={"pass": False, "dyn": True, "gen": True}), {f: ["K0-3"] for f in A.FAMILIES}),
    (k0_with(K0_4=False), {f: ["K0-4"] for f in A.FAMILIES}),
    (k0_with(K0_5={"pass": False}), {f: ["K0-5"] for f in A.FAMILIES}),
    (k0_with(K0_6={"pass": False}), {f: ["K0-6"] for f in A.FAMILIES}),
    ({k: True for k in A.K0_KEYS}, {f: [] for f in A.FAMILIES}),
])
def test_k0_voids_by_family(k0, want):
    assert A.k0_voids(k0) == want


def test_missing_k0_status_voids_everything():
    assert A.k0_voids(None) == {"DYN": ["K0-1", "K0-3", "K0-4", "K0-5", "K0-6"], "S6": ["K0-1", "K0-3", "K0-4", "K0-5", "K0-6"],
                                "SYNC": ["K0-1", "K0-3", "K0-4", "K0-5", "K0-6"], "GEN": ["K0-2", "K0-3", "K0-4", "K0-5", "K0-6"]}
    assert A.k0_voids({k: v for k, v in K0_OK.items() if k != "K0-2"})["GEN"] == ["K0-2"]


@pytest.mark.parametrize("run_meta,want", [
    (RUN_OK, []), ([RUN_OK, RUN_OK], []), (None, ["run_meta"]), ([], ["run_meta"]),
    ({**RUN_OK, "digest_after": "f" * 64}, ["digest"]), ({**RUN_OK, "digest_before": None}, ["digest"]),
    ({**RUN_OK, "version_after": "0.0.other"}, ["version"]), ({**RUN_OK, "version_before": None}, ["version"]),
    ([RUN_OK, {**RUN_OK, "version_before": "0.0.other", "version_after": "0.0.other"}], ["version"]),
])
def test_run_meta_digest_and_version(run_meta, want):
    assert A.run_problems(run_meta) == want


def test_k0_1_voids_dyn_and_marks_s6_but_not_gen(base):
    items, scores, _ = base
    rep = go(items, scores, k0=k0_with(K0_1={"pass": False}))
    assert rep["verdicts"]["DYN"]["sentence"] == "作廢（DYN，K0-1）" and rep["verdicts"]["DYN"]["status"] == "void"
    assert rep["verdicts"]["GEN"]["status"] == "gray" and rep["described"]["S6"]["void"] == ["K0-1"]


def test_digest_or_version_change_voids_every_family(base):
    items, scores, _ = base
    rep = go(items, scores, run_meta={**RUN_OK, "version_after": "0.0.other"})
    assert rep["sentences"] == {"DYN": "作廢（DYN，Ollama 版本）", "GEN": "作廢（GEN，Ollama 版本）"}
    rep = go(items, scores, run_meta={**RUN_OK, "digest_after": "0" * 64}, k0=k0_with(K0_2={"pass": False}))
    assert rep["sentences"] == {"DYN": "作廢（DYN，digest）", "GEN": "作廢（GEN，K0-2、digest）"}
    assert rep["power"]["report"] is None


def test_a_missing_job_is_refused_until_it_is_declared_unrecoverable(tmp_path):
    """§1: fix and resume first; only jobs that cannot be done make the report 作廢 (run_x --jobs-unrecoverable)."""
    items, scores, _ = run(tmp_path, DYN2 + S6_1 + GEN5, skip={("F5_01", "B0p", 1)})
    with pytest.raises(SystemExit, match="jobs_unrecoverable"):
        go(items, scores)
    rep = go(items, scores, jobs_unrecoverable=True)
    assert rep["calls"]["missing_calls"] == ["F5_01|B0p|1"] and scores["missing_jobs"] == ["X|F5_01|B0p|1"]
    assert rep["sentences"] == {"DYN": "作廢（DYN，缺漏 job）", "GEN": "作廢（GEN，缺漏 job）"}
    assert rep["described"]["S6"]["void"] == ["缺漏 job"] and rep["inputs"]["jobs_unrecoverable"] is True


def test_a_call_absent_from_the_job_list_is_refused_or_voids(tmp_path):
    items, scores, _ = run(tmp_path, DYN2 + GEN5)
    scores["items"]["S5_02"]["reps"].pop("B0|3")         # the job list itself lacked a prereg call
    with pytest.raises(SystemExit, match="1 prereg calls without a scored record, 0 jobs missing"):
        go(items, scores)
    rep = go(items, scores, jobs_unrecoverable=True)
    assert rep["calls"]["missing_calls"] == ["S5_02|B0|3"] and rep["verdicts"]["GEN"]["status"] == "void"


UNKNOWN = {**RUN_OK, "digest_after": None, "version_after": None}


def test_a_run_whose_last_check_got_no_answer_is_refused(base):
    """run_x state "unknown": resume to check again; the flag makes it 作廢 (digest／version unknown)."""
    items, scores, _ = base
    assert A.run_unknown([RUN_OK, UNKNOWN]) == ["2|digest_after", "2|version_after"] and A.run_unknown(RUN_OK) == []
    with pytest.raises(SystemExit, match="checks without an answer"):
        go(items, scores, run_meta=[RUN_OK, UNKNOWN])
    rep = go(items, scores, run_meta=[RUN_OK, UNKNOWN], jobs_unrecoverable=True)
    assert rep["sentences"] == {"DYN": "作廢（DYN，digest、Ollama 版本）", "GEN": "作廢（GEN，digest、Ollama 版本）"}


def test_a_run_void_anyway_is_reported_not_refused(tmp_path):
    """A version change voids the run, which can never be resumed: missing jobs or unknown checks do not hold it up."""
    items, scores, _ = run(tmp_path, DYN2 + GEN5, skip={("F5_01", "B0p", 1)})
    changed = [RUN_OK, {**UNKNOWN, "version_before": "0.0.other"}]
    rep = go(items, scores, run_meta=changed)
    assert rep["sentences"]["DYN"] == "作廢（DYN，digest、Ollama 版本、缺漏 job）"
    assert A.run_problems(changed, known_only=True) == ["version"]
    assert A.run_problems(UNKNOWN, known_only=True) == [] and A.run_problems(UNKNOWN) == ["digest", "version"]


def test_scores_of_other_generation_files_are_refused(tmp_path):
    items, scores, recs = run(tmp_path, DYN2 + GEN5)
    assert go(items, scores, gen_dir=tmp_path)["inputs"]["gen_checked"] is True
    assert go(items, scores)["inputs"]["gen_checked"] is False                      # no gen_dir: not checked
    with (tmp_path / "gen_arms.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "error", "job_id": "X|S5_01|G|1", "round": 0, "error": "x"}) + "\n")
    with pytest.raises(SystemExit, match="run score again"):
        go(items, scores, gen_dir=tmp_path)
    with pytest.raises(SystemExit, match="run score again"):                         # the flag does not bypass it
        go(items, scores, gen_dir=tmp_path, jobs_unrecoverable=True)
    old = {k: v for k, v in scores.items() if k != "gen_sha256"}
    with pytest.raises(SystemExit, match="no gen_sha256"):
        go(items, old, gen_dir=tmp_path)


# ---------------------------------------------------------------- truncation (§1)
def test_truncation_limit_voids_only_that_family(tmp_path):
    items, scores, _ = run(tmp_path, DYN2 + GEN5, trunc={("S5_01", "G", 1), ("S5_02", "G", 2)})
    rep = go(items, scores)
    assert rep["verdicts"]["DYN"]["sentence"] == "作廢（DYN，截斷超限）" and rep["verdicts"]["GEN"]["status"] == "gray"


def test_one_truncation_per_arm_does_not_void_and_b0p_never_counts(tmp_path):
    trunc = {("S5_01", "T-rows", 1), ("F1_01", "B0p", 1), ("F3_01", "B0p", 1), ("F1_01", "G", 3)}
    items, scores, _ = run(tmp_path, DYN2 + GEN5, trunc=trunc)
    rep = go(items, scores)
    assert rep["verdicts"]["DYN"]["void"] == [] and rep["verdicts"]["GEN"]["void"] == []
    assert rep["descriptive"]["truncated_calls"] == ["F1_01|B0p|1", "F1_01|G|3", "F3_01|B0p|1", "S5_01|T-rows|1"]


def test_t_rows_and_g_truncations_differing_by_two_void(tmp_path):
    items, scores, _ = run(tmp_path, DYN2 + GEN5, trunc={("F1_01", "T-rows", 1), ("F3_01", "T-rows", 2)})
    assert go(items, scores)["verdicts"]["GEN"]["sentence"] == "作廢（GEN，截斷超限）"


THREE = ("S5_01", "S5_02", "S5_03")


def three(g, r):
    return [(item(i, "DYN", "S5", L=3), {"G": gg, "T-rows": rr}) for i, gg, rr in zip(THREE, g, r)]


def test_truncation_rejudgement_flips_stop_to_gray(tmp_path):
    # full: pG 2/3, pR 2/9, gap2 4/9 < 0.45 stop; without S5_03: gap2 2/3, pR 1/3 pass -> gray
    items, scores, _ = run(tmp_path, three([3, 3, 0], [1, 1, 0]), trunc={("S5_03", "G", 1)})
    v = go(items, scores)["verdicts"]["DYN"]
    assert v["rule"]["category"] == "stop" and v["excl_truncated"]["category"] == "pass"
    assert v["excl_truncated"]["changed"] and v["gray_by_truncation"]
    assert (v["category"], v["status"], v["sentence"]) == ("gray", "gray", A.SENTENCE["gray"])


def test_truncation_rejudgement_flips_pass_to_gray(tmp_path):
    # full: pR 1/3, gap2 2/3 pass; without S5_01 (truncated T-rows call): pR 1/2 stop -> gray
    items, scores, _ = run(tmp_path, three([3, 3, 3], [0, 2, 1]), trunc={("S5_01", "T-rows", 1)})
    v = go(items, scores, pilot_authorized=False)["verdicts"]["DYN"]
    assert (v["rule"]["category"], v["excl_truncated"]["category"]) == ("pass", "stop")
    assert (v["status"], v["sentence"]) == ("gray_not_authorized", A.SENTENCE["gray_not_authorized"])


def test_truncation_rejudgement_without_change_keeps_the_verdict(tmp_path):
    items, scores, _ = run(tmp_path, three([3, 3, 2], [0, 0, 0]), trunc={("S5_03", "G", 1)})
    v = go(items, scores)["verdicts"]["DYN"]
    assert v["excl_truncated"]["items_dropped"] == ["S5_03"] and not v["excl_truncated"]["changed"]
    assert v["status"] == "pass" and not v["gray_by_truncation"]


def test_no_truncation_no_rejudgement(base):
    items, scores, _ = base
    assert go(items, scores)["verdicts"]["DYN"]["excl_truncated"] is None


# ---------------------------------------------------------------- scoring sensitivity: score_any (execution log)
LENIENT = "50年,甲朗在位41年,乙朗在位9年"           # strict: the last value 9 (0); lenient: the gold 50 is written (1)


def test_score_any_rejudgement_flips_pass_to_gray_with_a_note(tmp_path):
    # strict: pG 1, pR 0 pass; lenient: T-rows 2 of 3 reps written with the gold → pR 2/3, gap2 1/3: stop -> gray
    spec = [(it, {"G": 3, "T-rows": [LENIENT, LENIENT, "49年"]}) for it, _ in DYN2]
    items, scores, _ = run(tmp_path, spec)
    rep = go(items, scores)
    v = rep["verdicts"]["DYN"]
    md = A.render_md(rep)
    assert "寬鬆計分 score_any" in md and v["note"] in md and "判定改變，改判灰區" in md
    assert (v["rule"]["category"], v["score_any"]["category"]) == ("pass", "stop")
    assert v["score_any"]["clauses"] == ["gap2", "pR"]
    assert v["score_any"]["changed"] and v["gray_by_score_any"] and not v["gray_by_truncation"]
    assert (v["category"], v["status"], v["sentence"]) == ("gray", "gray", A.SENTENCE["gray"])
    assert v["note"] == A.any_note("pass", "stop") and v["values"]["pR"]["frac"] == "0"
    assert v["score_any"]["values"]["pR"]["frac"] == "2/3"


def test_score_any_rejudgement_flips_stop_to_gray(tmp_path):
    # strict: G 1 of 3 correct → gap2 1/3 stop; lenient: the other two G reps write the gold → gap2 1 pass -> gray
    spec = [(it, {"G": ["共50年整", LENIENT, LENIENT]}) for it, _ in DYN2]
    items, scores, _ = run(tmp_path, spec)
    v = go(items, scores, pilot_authorized=True)["verdicts"]["DYN"]
    assert (v["rule"]["category"], v["score_any"]["category"]) == ("stop", "pass")
    assert (v["status"], v["sentence"]) == ("gray_pilot_pending", A.SENTENCE["gray"])
    assert v["note"] == "Kay 已授權盲 pilot，等 pilot 結果（另立事前登記）；" + A.any_note("stop", "pass")


def test_score_any_rejudgement_without_change_keeps_the_verdict(base):
    items, scores, _ = base
    rep = go(items, scores)
    for f in ("DYN", "GEN"):
        v = rep["verdicts"][f]
        assert not v["score_any"]["changed"] and not v["gray_by_score_any"] and "note" not in v
        assert v["score_any"]["values"] == v["values"]                 # these answers score alike either way
    assert (rep["verdicts"]["DYN"]["status"], rep["verdicts"]["GEN"]["status"]) == ("pass", "gray")
    assert rep["descriptive"]["families_any"]["DYN"]["means"] == scores["families_any"]["DYN"]


def test_a_void_family_gets_no_sensitivity_note(tmp_path):
    spec = [(it, {"G": 3, "T-rows": [LENIENT, LENIENT, "49年"]}) for it, _ in DYN2]
    items, scores, _ = run(tmp_path, spec)
    v = go(items, scores, k0=k0_with(K0_1={"pass": False}))["verdicts"]["DYN"]
    assert v["status"] == "void" and v["gray_by_score_any"] and "note" not in v


def test_scores_without_lenient_tables_are_refused(base):
    items, scores, _ = base
    with pytest.raises(ValueError, match="families_any"):
        go(items, {k: v for k, v in scores.items() if k != "families_any"})


# ---------------------------------------------------------------- dry run (假 chat)
def test_a_dry_run_marks_every_sentence_and_status(base):
    items, scores, _ = base
    rep = go(items, scores, run_meta={**RUN_OK, "dry_run": True})
    assert rep["dry_run"] is True
    assert rep["sentences"] == {"DYN": A.DRY_RUN + A.SENTENCE["pass"], "GEN": A.DRY_RUN + A.SENTENCE["gray"]}
    assert {f: v["status"] for f, v in rep["verdicts"].items()} == {"DYN": "dry_run:pass", "GEN": "dry_run:gray"}
    assert rep["power"]["families"] == ["DYN", "GEN"] and rep["power"]["C"] == 17      # chosen before the marking
    md = A.render_md(rep)
    assert all(s in md for s in rep["sentences"].values()) and "dry_run:pass" in md
    formal = go(items, scores)
    assert not any(A.DRY_RUN in s for s in formal["sentences"].values()) and formal["dry_run"] is False


# ---------------------------------------------------------------- §7-4 B0′
def test_b0_bare_per_gen_type_and_the_half_rule(base):
    items, scores, _ = base
    b = go(items, scores)["b0_bare"]
    t = b["types"]
    assert list(t) == ["F1_5", "F1_11", "F3", "F5"]
    assert {k: (v["B0p"]["frac"], v["non_named"], v["note"]) for k, v in t.items()} == {
        "F1_5": ("1", True, A.NON_NAMED), "F1_11": ("0", False, None),
        "F3": ("1/2", True, A.NON_NAMED), "F5": ("0", False, None)}               # 1/2 is ≥ 0.5
    assert t["F3"]["n_items"] == 2 and b["family"]["B0p"]["frac"] == "2/5"


# ---------------------------------------------------------------- §7-5 power
@pytest.fixture
def capture(monkeypatch):
    calls = []

    def fake(rows, C_values, m_values=P.M_VALUES, nsim=P.NSIM):
        calls.append({"families": sorted({r["family"] for r in rows}), "C": tuple(C_values), "m": tuple(m_values),
                      "n": len(rows)})
        return {"nested_check": {}, "subsets": {"all": None, "nested": None}}
    monkeypatch.setattr(P, "power_report", fake)
    return calls


@pytest.mark.parametrize("dyn_t,gen_t,k0,want", [
    (0, 1, K0_OK, (["DYN", "GEN"], (17,))),           # DYN pass, GEN gray
    (0, 3, K0_OK, (["DYN"], (9,))),                   # GEN stopped (pR 1)
    (3, 1, K0_OK, (["GEN"], (8,))),                   # DYN stopped (pR 1)
    (0, 1, k0_with(K0_1={"pass": False}), (["GEN"], (8,))),
    (3, 3, K0_OK, None),
])
def test_power_c_follows_the_passing_or_gray_families(tmp_path, capture, dyn_t, gen_t, k0, want):
    spec = [(it, {**a, "T-rows": dyn_t}) for it, a in DYN2] + [(it, {**a, "T-rows": gen_t}) for it, a in GEN5]
    items, scores, _ = run(tmp_path, spec)
    rep = go(items, scores, k0=k0)
    if want is None:
        assert capture == [] and rep["power"]["report"] is None and rep["power"]["C"] is None
    else:
        assert (capture[0]["families"], capture[0]["C"], capture[0]["m"]) == (*want, (2, 3, 4))
        assert rep["power"]["C"] == want[1][0] and rep["power"]["proposal_set"] == "ii"


@pytest.mark.parametrize("auth,pilot,gen_status,want", [
    (None, None, "gray", (["DYN", "GEN"], (17,))),
    (True, None, "gray_pilot_pending", (["DYN", "GEN"], (17,))),
    (False, None, "gray_not_authorized", (["DYN"], (9,))),
    (True, {"GEN": {"pR": "0", "gap": "1/2"}}, "pilot_pass", (["DYN", "GEN"], (17,))),
    (True, {"GEN": {"pR": "13/20", "gap": "1/2"}}, "pilot_stop", (["DYN"], (9,))),
])
def test_power_pools_only_families_whose_final_status_is_not_stopped(base, capture, auth, pilot, gen_status, want):
    """§7-5: a gray family Kay did not authorize, or whose blind pilot stopped, is stopped (C = 9 for DYN alone)."""
    items, scores, _ = base
    rep = go(items, scores, pilot_authorized={"GEN": auth} if auth is not None else None, pilot=pilot)
    assert rep["verdicts"]["GEN"]["status"] == gen_status and rep["verdicts"]["DYN"]["status"] == "pass"
    assert (capture[0]["families"], capture[0]["C"]) == want and rep["power"]["C"] == want[1][0]


def test_power_report_runs_on_both_input_sets_and_notes_nested(base):
    items, scores, _ = base
    pw = go(items, scores, nsim=3)["power"]
    r = pw["report"]
    assert pw["families"] == ["DYN", "GEN"] and r["C_values"] == [17] and r["m_values"] == [2, 3, 4]
    assert set(r["subsets"]["all"]["cells"]) == {"i", "ii"} and len(r["subsets"]["all"]["cells"]["ii"]) == 3
    assert r["subsets"]["all"]["pooled"]["n_items"] == 7 and r["subsets"]["nested"]["ids"] == ["S5_01"]
    assert r["nested_check"]["GEN"]["redefine_units"] and r["nested_check"]["DYN"]["n_nested"] == 1
    assert any(P.REDEFINE in n and n.startswith("GEN") for n in pw["notes"])
    assert not any(n.startswith("DYN：") for n in pw["notes"])               # 1 of 2 nested is not < half


# ---------------------------------------------------------------- §8 descriptives
def test_descriptives_subtypes_subsets_and_calls(tmp_path):
    spec = [(DYN2[0][0], {"G": 3, "T-canon": 2, "T-rows": ["49或50年", None, "共50年整"]}), DYN2[1]] + GEN5
    items, scores, recs = run(tmp_path, spec)
    d = go(items, scores, recs)["descriptive"]
    assert list(d["subtypes"]) == ["S5_L3", "S5_L4", "F1_5", "F1_11", "F3", "F5"]
    assert d["subtypes"]["S5_L3"]["gap2"]["frac"] == "2/3" and d["subtypes"]["F3"]["gap1"]["frac"] == "2/3"
    assert d["subtypes"]["F3"]["pC_arm"] == "B0"
    tc = d["tcanon_complete"]["DYN"]
    assert (tc["n_items"], tc["n_family"], tc["means"]["T-canon"]["frac"], tc["gap1"]["frac"]) == (1, 2, "2/3", "1/3")
    assert d["nested"]["DYN"]["ids"] == ["S5_01"] and d["nested"]["GEN"]["n_items"] == 0
    c = d["counts"]["DYN"]["T-rows"]
    assert (c["hedge"], c["format_fail"], c["correct"]) == (1, 1, 1)
    assert d["counts"]["DYN"]["B0"]["distractor"] == {"off_by_one": 6}
    calls = d["calls"]
    assert calls["by_family"]["DYN"]["G"]["prompt_tokens"]["mean"] == 1000
    assert calls["by_family"]["GEN"]["B0p"]["prompt_tokens"]["n"] == 5
    assert calls["seconds_per_call"] == 2.0 and calls["seconds_total"] == 2.0 * (2 * 4 * 3 + 5 * 3 * 3 + 5)
    assert d["block_chars"]["by_family"]["DYN"]["T-canon"]["max"] == 880 and d["block_chars"]["over_cap_items"] == []
    assert d["covered"]["a"]["frac"] == "1"


def test_sync_both_keys_z_only_and_a_s1_comparison(tmp_path):
    it = dict(sync_item("J01", 2, "J", "丙雅", "乙朗", "I"), id="SYNC2_01", nested=False, tcanon_complete=False)
    spec = [(it, {"G": ["丙雅;以色列王乙朗"] * 3, "T-rows": ["以色列王乙朗"] * 3, "T-canon": ["不知道"] * 3,
                  "B0": ["不知道"] * 3})] + DYN2
    items, scores, _ = run(tmp_path, spec, VR=toy_view())
    rep = go(items, scores)
    s = rep["descriptive"]["sync"]
    assert s["both_keys"]["gap2"]["frac"] == "1" and s["z_only"]["gap2"]["frac"] == "0"
    assert s["by_k"]["SYNC2"]["z_only"]["means"]["T-rows"]["frac"] == "1"
    assert s["A_S1_template_gap2"]["frac"] == "11/18" and round(s["A_S1_template_gap2"]["float"], 3) == 0.611
    assert "SYNC" not in rep["sentences"] and rep["described"]["SYNC"]["sentence"] is None
    assert rep["descriptive"]["tcanon_complete"]["SYNC"]["n_items"] == 0


def test_inputs_are_checked(base):
    items, scores, _ = base
    with pytest.raises(ValueError):
        A.analyze(scores, items, {}, k0=K0_OK, run_meta=RUN_OK)
    with pytest.raises(ValueError):
        A.analyze(scores, items[:2], meta(items), k0=K0_OK, run_meta=RUN_OK)


# ---------------------------------------------------------------- report files (store only)
def test_report_files_hold_no_question_or_answer_text(base, tmp_path):
    items, scores, recs = base
    rep = go(items, scores, recs)
    jp, mp = A.write_report(rep, tmp_path / "out")
    assert json.loads(jp.read_text(encoding="utf-8"))["sentences"] == rep["sentences"]
    md = mp.read_text(encoding="utf-8")
    for s in rep["sentences"].values():
        assert s in md
    for banned in ("QSENTINEL", "共50年整", "推理略", "圖譜有效", "圖譜無效"):
        assert banned not in md
    assert "開發集" in md and "|" in md


def test_report_is_never_written_inside_the_repository(base):
    items, scores, _ = base
    rep = go(items, scores)
    with pytest.raises(SystemExit):
        A.write_report(rep, H / "report_out")
    assert not (H / "report_out").exists()


# ---------------------------------------------------------------- store-backed
KG_A = X.STORE / "reports/kg_cards_20261018/A"
needs_a = pytest.mark.skipif(not (KG_A / "scores.json").is_file(), reason=f"store not mounted ({KG_A})")
needs_store = pytest.mark.skipif(not (X.REF_V2.is_file() and X.TEXT.is_dir() and X.R4_LAYER.is_file()),
                                 reason="store not mounted")


@needs_a
def test_a_s1_template_figure_is_experiment_as_stored_value():
    sc, its = X.read_json(KG_A / "scores.json"), {it["id"]: it for it in X.read_json(KG_A / "items.json")["items"]}
    s1 = [i for i in sc["items"] if its[i].get("kind") == "S1"]
    g = sum(Fr(sc["items"][i]["mean"]["G-auto"]).limit_denominator(3) for i in s1) / len(s1)
    t = sum(Fr(sc["items"][i]["mean"]["T-rows"]).limit_denominator(3) for i in s1) / len(s1)
    assert len(s1) == 18 and g - t == A.A_S1_TEMPLATE_GAP2


@needs_store
def test_the_52_items_end_to_end_with_made_up_answers(tmp_path):
    """G answers gold, every other arm a wrong value: both families pass, 588 calls, C = 17 (nothing written)."""
    import engine_x
    import gen_layer
    import items_x
    gen = gen_layer.build()
    items = items_x.build_items(gen=gen)["items"]
    kn = X.ac.KNAME
    spec = []
    for it in items:
        if it["family"] == "SYNC":
            okd = "J" if it["kingdom"] == "I" else "I"
            right = f"{it['gold']['Y']}；{kn[okd]}王{it['gold']['Z']}"
            spec.append((it, {a: ([right] * 3 if a == "G" else ["不知道"] * 3) for a in X.ARMS["SYNC"]}))
        else:
            spec.append((it, {"G": 3}))
    out, scores, recs = run(tmp_path, spec)
    cards = {it["id"]: engine_x.card(it, gen=gen) for it in items}
    cm = {i: {"covered": c["covered"], "block_chars": {"G": c["chars_g"], "T-rows": c["chars_t"]},
              "dropped_rows": c["dropped_rows"], "dropped_lines": c["dropped_lines"]} for i, c in cards.items()}
    rep = A.analyze(scores, out, cm, k0=K0_OK, run_meta=RUN_OK, records=recs, nsim=3)
    assert rep["calls"]["expected"] == rep["calls"]["scored"] == 588 and rep["n_items"] == 52
    assert {f: v["status"] for f, v in rep["verdicts"].items()} == {"DYN": "pass", "GEN": "pass"}
    assert rep["power"]["C"] == 17 and rep["descriptive"]["covered"]["a"]["frac"] == "1"
    assert set(rep["described"]) == {"S6", "SYNC"} and rep["descriptive"]["sync"]["both_keys"]["gap2"]["frac"] == "1"
    assert list(rep["b0_bare"]["types"]) == list(A.GEN_TYPES)
    assert list(rep["descriptive"]["subtypes"]) == list(A.SUBTYPE_ORDER)
    nc = rep["power"]["report"]["nested_check"]
    assert nc["DYN"]["redefine_units"] and nc["GEN"]["redefine_units"]      # §10: most items cross segments
    md = A.render_md(rep)
    for it in items:
        assert it["question"] not in md

"""Ordered-chain arithmetic stage-0 scorer (score_x.py; prereg §1 截斷, §5 題值與族值, K0-4 store regression).

Synthetic runs are written to tmp_path: made-up items (no question text), made-up generations and the
toy two-kingdom View of test_arith_stage0_keys. The store regression rescores experiment A's stored
A and A_confirm records and skips when the store is not mounted. Ollama is never called.
"""

import json
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
import score_x as S  # noqa: E402
from test_arith_stage0_keys import sync_item, toy_view  # noqa: E402

NUM_CTX = 131072


def arith(iid, family, qtype, value, classes=("Y",), ordinal=False, distractors=(), **extra):
    return {"id": iid, "family": family, "qtype": qtype, "keys": [
        {"type": "arith", "value": value, "classes": list(classes), "ordinal": ordinal}],
        "distractors": [{"value": v, "kind": k} for v, k in distractors], **extra}


def job(item, arm, rep):
    return {"job_id": f"X|{item}|{arm}|{rep}", "item": item, "arm": arm, "rep": rep}


def gen(item, arm, rep, answer, done="stop", prompt=900, ev=800):
    content = None if answer is None else f"推理略。\n答案：{answer}"
    return {"type": "answer", "job_id": f"X|{item}|{arm}|{rep}", "item": item, "arm": arm, "rep": rep,
            "content": content or "沒有答案行", "prompt_eval_count": prompt, "eval_count": ev, "done_reason": done}


def write_run(d: Path, recs: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with (d / "gen_arms.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.write(json.dumps({"type": "error", "job_id": recs[0]["job_id"], "round": 0, "error": "x"}) + "\n")


ITEMS = [arith("S5_01", "DYN", "S5", 76, distractors=[(75, "off_by_one"), (41, "component")], L=3),
         arith("S5_02", "DYN", "S5", 61, L=4),
         arith("F1_01", "GEN", "F1", 235, classes=("A", "Y"), chapter=5),
         arith("F3_01", "GEN", "F3", 37, ordinal=True, chapter=11)]
ANSWERS = {  # (item, arm): answers of reps 1..3
    ("S5_01", "G"): ["共76年", "76年", "76"], ("S5_01", "T-rows"): ["共75年", "76年", "41年"],
    ("S5_01", "T-canon"): ["40或41年", None, "99年"], ("S5_01", "B0"): ["0年", "0年", "0年"],
    ("S5_02", "G"): ["61年", "61年", "60年"], ("S5_02", "T-rows"): ["60年", "60年", "60年"],
    ("S5_02", "T-canon"): ["61年", "60年", "60年"], ("S5_02", "B0"): ["61年", "60年", "60年"],
    ("F1_01", "G"): ["235歲", "235歲", "235歲"], ("F1_01", "T-rows"): ["235歲", "130歲", "130歲"],
    ("F1_01", "B0"): ["130歲", "130歲", "130歲"],
    ("F3_01", "G"): ["第37年", "37年", "37"], ("F3_01", "T-rows"): ["35年", "37年", "2年"],
    ("F3_01", "B0"): ["35年", "35年", "35年"],
}
B0P = {"F1_01": "235歲", "F3_01": "36年"}


def jobs_and_recs(skip=(), trunc=()):
    jobs, recs = [], []
    for (iid, arm), answers in ANSWERS.items():
        for rep, a in enumerate(answers, 1):
            jobs.append(job(iid, arm, rep))
            if (iid, arm, rep) in skip:
                continue
            recs.append(gen(iid, arm, rep, a, done="length" if (iid, arm, rep) in trunc else "stop"))
    for iid, a in B0P.items():
        jobs.append(job(iid, "B0p", 1))
        recs.append(gen(iid, "B0p", 1, a))
    return jobs, recs


@pytest.fixture
def run(tmp_path):
    jobs, recs = jobs_and_recs()
    write_run(tmp_path, recs)
    return S.score_all(tmp_path, ITEMS, jobs, num_ctx=NUM_CTX)


def F(s):
    return Fraction(s["frac"])


# ---------------------------------------------------------------- one record
def test_score_record_truncation_is_a_format_failure():
    it = ITEMS[0]
    r = S.score_record_x(it, gen("S5_01", "G", 1, "共76年", done="length"), NUM_CTX)
    assert (r["score"], r["truncated"], r["format_fail"], r["answer_line"]) == (0, True, True, None)
    r = S.score_record_x(it, gen("S5_01", "G", 1, "共76年", prompt=NUM_CTX - 10, ev=10), NUM_CTX)
    assert (r["score"], r["truncated"]) == (0, True)
    r = S.score_record_x(it, gen("S5_01", "G", 1, "共76年"), NUM_CTX)
    assert (r["score"], r["truncated"], r["answer_line"], r["job_id"]) == (1, False, "共76年", "X|S5_01|G|1")
    r = S.score_record_x(it, gen("S5_01", "G", 1, None), NUM_CTX)
    assert (r["score"], r["format_fail"], r["truncated"]) == (0, True, False)


def test_score_record_carries_the_lenient_score():
    it = ITEMS[0]
    r = S.score_record_x(it, gen("S5_01", "T-rows", 1, "76年,甲朗在位41年,乙朗在位25年,丙朗在位10年"), NUM_CTX)
    assert (r["score"], r["score_any"], r["value"]) == (0, 1, 10)
    r = S.score_record_x(it, gen("S5_01", "G", 1, "共76年", done="length"), NUM_CTX)
    assert (r["score"], r["score_any"]) == (0, 0)                       # a truncated call is 0 in both


# ---------------------------------------------------------------- item and family values
def test_item_values_are_exact_fractions_of_correct_calls(run):
    it = run["items"]["S5_01"]
    assert {a: F(m) for a, m in it["mean"].items()} == {"G": 1, "T-rows": Fraction(1, 3), "T-canon": 0, "B0": 0}
    assert it["correct"]["G"] == [3, 3] and it["subtype"] == "S5_L3"
    assert set(it["reps"]) == {f"{a}|{r}" for a in ("G", "T-rows", "T-canon", "B0") for r in (1, 2, 3)}
    rec = it["reps"]["T-rows|1"]
    assert set(rec) >= {"score", "format_fail", "trap", "truncated", "value", "flags", "distractor", "answer_line",
                        "job_id"}
    assert (rec["value"], rec["distractor"]) == (75, ["off_by_one"])
    assert it["reps"]["T-canon|1"]["trap"] == ["hedge"] and it["reps"]["T-canon|2"]["format_fail"]
    assert F(run["items"]["F1_01"]["mean"]["B0p"]) == 1


def test_family_means_and_gaps(run):
    fam = run["families"]
    assert {a: F(v) for a, v in fam["DYN"].items()} == {"G": Fraction(5, 6), "T-rows": Fraction(1, 6),
                                                       "T-canon": Fraction(1, 6), "B0": Fraction(1, 6)}
    assert fam["DYN"]["G"]["n_items"] == 2 and fam["DYN"]["G"]["float"] == pytest.approx(5 / 6)
    assert {a: F(v) for a, v in fam["GEN"].items()} == {"G": 1, "T-rows": Fraction(1, 3), "B0": 0,
                                                       "B0p": Fraction(1, 2)}
    gaps = run["gaps"]
    assert (F(gaps["DYN"]["gap2"]), F(gaps["DYN"]["gap1"]), gaps["DYN"]["pC_arm"]) == (Fraction(2, 3), Fraction(2, 3),
                                                                                      "T-canon")
    # GEN has no T-canon: pC_GEN := pB_GEN, H1_GEN = G − B0 (prereg §4)
    assert (F(gaps["GEN"]["gap2"]), F(gaps["GEN"]["gap1"]), gaps["GEN"]["pC_arm"]) == (Fraction(2, 3), 1, "B0")
    assert {g: F(v["G"]) for g, v in run["groups"].items()} == {"S5_L3": 1, "S5_L4": Fraction(2, 3), "F1_5": 1,
                                                                 "F3": 1}


def test_lenient_tables_mirror_the_strict_ones(tmp_path):
    """score_any: T-rows writes the gold first and a component last (strict 0, lenient 1)."""
    jobs, recs = jobs_and_recs()
    lenient = "61年,甲朗在位41年,乙朗在位20年"
    recs = [dict(r, content=f"推理略。\n答案：{lenient}") if r["job_id"] == "X|S5_02|T-rows|1" else r for r in recs]
    write_run(tmp_path, recs)
    doc = S.score_all(tmp_path, ITEMS, jobs, num_ctx=NUM_CTX)
    it = doc["items"]["S5_02"]
    assert (F(it["mean"]["T-rows"]), F(it["mean_any"]["T-rows"])) == (0, Fraction(1, 3))
    assert F(doc["families"]["DYN"]["T-rows"]) == Fraction(1, 6)
    assert F(doc["families_any"]["DYN"]["T-rows"]) == Fraction(1, 3) and doc["families_any"]["DYN"]["T-rows"]["n_items"] == 2
    assert F(doc["gaps_any"]["DYN"]["gap2"]) == Fraction(5, 6) - Fraction(1, 3)
    assert F(doc["groups_any"]["S5_L4"]["T-rows"]) == Fraction(1, 3)
    c = doc["counts"]["DYN"]["T-rows"]
    assert (c["correct"], c["correct_any"]) == (1, 2)
    # elsewhere the lenient tables equal the strict ones
    assert doc["families_any"]["GEN"] == doc["families"]["GEN"] and doc["gaps_any"]["GEN"] == doc["gaps"]["GEN"]


def test_scores_record_the_generation_files_sha256(tmp_path, run):
    assert run["schema"] == "arith.scores.v2"
    assert run["gen_sha256"] == {"gen_arms.jsonl": X.sha256_file(tmp_path / "gen_arms.jsonl")}
    assert S.gen_sha256(tmp_path) == run["gen_sha256"]
    assert S.gen_sha256(tmp_path / "nowhere") == {"gen_arms.jsonl": None}
    with (tmp_path / "gen_arms.jsonl").open("a", encoding="utf-8") as f:
        f.write("{}\n")
    assert S.gen_sha256(tmp_path) != run["gen_sha256"]


def test_counts_per_family_and_arm(run):
    c = run["counts"]["DYN"]
    assert (c["G"]["calls"], c["G"]["correct"]) == (6, 5)
    assert (c["T-canon"]["hedge"], c["T-canon"]["format_fail"]) == (1, 1)
    assert c["T-rows"]["distractor"] == {"off_by_one": 1, "component": 1}
    assert run["missing_jobs"] == [] and run["n_records"] == 44


def test_fraction_boundary_is_exact(tmp_path):
    """16 items x 3 calls: a gap of exactly 12/48 stays 1/4 (a float mean of item thirds may not)."""
    items, jobs, recs = [], [], []
    g_hits = [3] * 4 + [2] * 6 + [1] * 6
    r_hits = [2] * 4 + [1] * 10 + [0] * 2
    for i, (g, r) in enumerate(zip(g_hits, r_hits)):
        iid = f"S5_{i:02d}"
        items.append(arith(iid, "DYN", "S5", 50, L=3))
        for arm, n in (("G", g), ("T-rows", r)):
            for rep in (1, 2, 3):
                jobs.append(job(iid, arm, rep))
                recs.append(gen(iid, arm, rep, "50年" if rep <= n else "49年"))
    write_run(tmp_path, recs)
    doc = S.score_all(tmp_path, items, jobs, num_ctx=NUM_CTX)
    assert F(doc["gaps"]["DYN"]["gap2"]) == Fraction(12, 48) and doc["gaps"]["DYN"]["gap2"]["frac"] == "1/4"


# ---------------------------------------------------------------- missing jobs and truncation (prereg §1)
def test_missing_reps_leave_the_item_and_family_undefined(tmp_path):
    jobs, recs = jobs_and_recs(skip={("S5_02", "G", 2)})
    write_run(tmp_path, recs)
    doc = S.score_all(tmp_path, ITEMS, jobs, num_ctx=NUM_CTX)
    assert doc["missing_jobs"] == ["X|S5_02|G|2"]
    assert doc["items"]["S5_02"]["mean"]["G"] is None and doc["families"]["DYN"]["G"] is None
    assert doc["gaps"]["DYN"]["gap2"] is None and doc["items"]["S5_02"]["reps"]["G|2"] is None


def test_truncation_counts_and_void_rule(tmp_path):
    trunc = {("S5_01", "G", 1), ("S5_02", "G", 3), ("F1_01", "T-rows", 2)}
    jobs, recs = jobs_and_recs(trunc=trunc)
    write_run(tmp_path, recs)
    doc = S.score_all(tmp_path, ITEMS, jobs, num_ctx=NUM_CTX)
    assert doc["truncation"]["DYN"] == {"G": 2, "T-rows": 0, "T-canon": 0, "B0": 0}
    assert doc["truncation"]["GEN"] == {"G": 0, "T-rows": 1, "B0": 0, "B0p": 0}
    assert doc["truncation_problems"] == {"DYN": ["G truncated 2 times", "G and T-rows truncations differ by 2"]}
    ex = doc["families_excl_truncated"]
    assert ex["DYN"]["items_dropped"] == ["S5_01", "S5_02"] and ex["DYN"]["means"]["G"] is None
    assert ex["GEN"]["items_dropped"] == ["F1_01"] and F(ex["GEN"]["means"]["G"]) == 1
    assert F(ex["GEN"]["gaps"]["gap2"]) == Fraction(2, 3)


def test_b0p_truncations_never_void_a_family():
    assert S.truncation_problems({"GEN": {"G": 0, "T-rows": 0, "B0": 0, "B0p": 5}}) == {}
    assert S.truncation_problems({"GEN": {"G": 1, "T-rows": 0, "B0": 1}}) == {}
    assert S.truncation_problems({"GEN": {"G": 0, "T-rows": 2, "B0": 0}}) == {
        "GEN": ["T-rows truncated 2 times", "G and T-rows truncations differ by 2"]}


def test_unknown_job_items_are_refused(tmp_path):
    write_run(tmp_path, [gen("S5_01", "G", 1, "76年")])
    with pytest.raises(ValueError):
        S.score_all(tmp_path, ITEMS, [job("Q_99", "G", 1)], num_ctx=NUM_CTX)


# ---------------------------------------------------------------- SYNC (both keys; Z alone reported)
def test_sync_items_score_both_keys_and_report_z(tmp_path):
    item = dict(sync_item("J01", 2, "J", "丙雅", "乙朗", "I"), id="SYNC_01", L=None)
    answers = {"G": ["丙雅;以色列王乙朗", "猶大王丙雅於以色列王乙朗第5年登基", "以色列王乙朗"],
               "T-rows": ["丁雅;以色列王丙朗", "以色列王乙朗", "以色列王乙朗"]}
    jobs, recs = [], []
    for arm, ans in answers.items():
        for rep, a in enumerate(ans, 1):
            jobs.append(job("SYNC_01", arm, rep))
            recs.append(gen("SYNC_01", arm, rep, a))
    write_run(tmp_path, recs)
    doc = S.score_all(tmp_path, [item], jobs, num_ctx=NUM_CTX, VR=toy_view())
    it = doc["items"]["SYNC_01"]
    assert (F(it["mean"]["G"]), F(it["mean_z"]["G"])) == (Fraction(2, 3), 1)
    assert (F(it["mean"]["T-rows"]), F(it["mean_z"]["T-rows"])) == (0, Fraction(2, 3))
    assert F(doc["families_z"]["SYNC"]["T-rows"]) == Fraction(2, 3) and it["subtype"] == "SYNC2"


# ---------------------------------------------------------------- store regression (K0-4)
KG = X.STORE / "reports/kg_cards_20261018"
needs_a = pytest.mark.skipif(not (KG / "A_confirm/scores.json").is_file(), reason=f"store not mounted ({KG})")
BARE = {f"A_confirm|QJ1s2a2|{a}|{r}|4" for a, r in (("G-auto", 2), ("G-auto", 3), ("T-rows", 1), ("T-rows", 2),
                                                     ("T-rows", 3), ("G-ref", 1), ("G-ref", 2), ("G-ref", 3))}
BARE.add("A_confirm|QJ3s2a1|T-rows|3|4")


@needs_a
def test_store_regression_on_experiment_a_records():
    doc = S.regress_a(KG)
    assert (doc["n_records"], doc["n_keys"]) == (66, 75)
    assert doc["line_diff"] == []
    assert doc["lost"] == [] and doc["score_down"] == []
    assert set(doc["gained"]) == BARE and len(doc["gained"]) == 9
    assert len(doc["score_up"]) == 9

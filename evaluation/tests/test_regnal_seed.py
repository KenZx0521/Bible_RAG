"""Rule-seed regression harness (evaluation/experiments/2026-10-19_regnal_seed/): cards, jobs, scores.

Ollama is never called. The synthetic tests run on regnal_seed_helpers' small two-kingdom layer and
template questions (no scripture text, no question of experiment A's sets). The store-backed tests at
the end read the candidate layer, the routing lexicon and experiment A's records; they skip when the
store is not mounted, and they print no question or card text. The runner's and the CLI's guards are
in test_regnal_seed_guards.py.
"""

import difflib
import json
from pathlib import Path

import pytest
from regnal_seed_helpers import (CONFIRM, DEV, RAW_A, UNTAKEN, fake_api, gen_seed_rows, make_syn, response_rows,
                                 write_jsonl)
from regnal_seed_helpers import slot as _slot

import a4_card_check as A4  # noqa: E402
import rs_cards as K  # noqa: E402
import rs_common as C  # noqa: E402
import rs_jobs as J  # noqa: E402
import rs_run as R  # noqa: E402
import rs_score as S  # noqa: E402

B = C.backend()
cc = C.cc
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def syn(tmp_path):
    return make_syn(tmp_path)


def test_the_backend_modules_are_this_checkouts():
    for mod in (B.card, B.engine, B.layer, B.seeds, B.trigger):
        assert Path(mod.__file__).resolve().is_relative_to(REPO / "backend")
    for mod in (B.regnal, B.routing):
        assert Path(mod.__file__).resolve().is_relative_to(REPO / "packages")
    assert set(B.files_sha256) == {"backend/utils/regnal/card.py", "backend/utils/regnal/engine.py",
                                   "backend/utils/regnal/layer.py", "backend/utils/regnal/seeds.py",
                                   "backend/utils/regnal/trigger.py", "packages/ragcommon/regnal.py",
                                   "packages/ragcommon/routing.py"}
    assert len(B.sha256) == 64


# ---------------------------------------------------------------- recorded seed formats

def test_recorded_seeds_raw_and_parsed(tmp_path):
    rows = gen_seed_rows({"X": "猶大｜亞撒"}) + [dict(gen_seed_rows({"Y": "猶大｜亞撒"})[0], done_reason="length")]
    raw = K.raw_seeds(write_jsonl(tmp_path / "s.jsonl", rows))
    assert raw["X"] == {"kind": "raw", "text": "猶大｜亞撒", "truncated": False}
    assert raw["Y"] == {"kind": "raw", "text": "", "truncated": True}   # a truncated seed call: no seeds (A)
    rows = response_rows({"X": ["猶大｜亞撒", "以色列｜巴沙"], "Y": None})
    aux = K.aux_seeds(write_jsonl(tmp_path / "r.jsonl", rows))
    assert aux["X"] == {"kind": "parsed", "pairs": [["J", "亞撒"], ["I", "巴沙"]], "no_aux_card": False}
    assert aux["Y"] == {"kind": "parsed", "pairs": [], "no_aux_card": True}
    with pytest.raises(ValueError):
        K.parse_aux(["埃及｜法老"])


# ---------------------------------------------------------------- card construction

def test_rule_arm_cards_come_from_the_rule_path(syn):
    lay, info, doc, _ = syn
    for rep in (1, 2, 3):
        s = _slot(doc, "confirm", "Q1", "rule", rep)
        want = B.card.card_from_rule(lay, ("I01",))
        assert (s["seed_source"], s["kings"], s["text"]) == ("rule", ["I01"], want.text)
        assert s["text_sha256"] == C.sha256_text(want.text) and s["chars"] == len(want.text)
        assert s["seeds"] == ["以色列｜耶羅波安"] and s["rule_ids"] == ["I01"] and s["rule_reason"] is None


def test_gemma_arm_replays_each_recorded_set_on_the_layer(syn):
    lay, _info, doc, _ = syn
    q1 = CONFIRM[0]["question"]
    a = _slot(doc, "confirm", "Q1", "gemma", 1)
    assert a["seed_source"] == "gemma:a"
    assert a["text"] == B.card.card_from_seeds(lay, q1, RAW_A["Q1"]).text
    assert a["text"] != _slot(doc, "confirm", "Q1", "rule", 1)["text"]          # two seeds, not one
    b = _slot(doc, "confirm", "Q1", "gemma", 2)
    assert b["seed_source"] == "gemma:b"
    assert b["text"] == B.card.card_from_parsed(lay, q1, [("I", "耶羅波安")]).text
    assert _slot(doc, "confirm", "Q1", "gemma", 3)["text"] == a["text"]        # set c holds set a's seeds
    none = _slot(doc, "confirm", "Q2", "gemma", 2)                              # no aux_card recorded
    assert (none["card"], none["text"], none["text_sha256"], none["seed_source"]) == (False, None, None, "gemma:b")
    assert _slot(doc, "confirm", "Q2", "gemma", 1)["text"] == _slot(doc, "confirm", "Q2", "rule", 1)["text"]


def test_a_rule_abstention_takes_the_reference_arms_card(syn):
    _lay, _info, doc, _ = syn
    for rep, label in ((1, "a"), (2, "b"), (3, "c")):
        rule, ref = _slot(doc, "confirm", "Q3", "rule", rep), _slot(doc, "confirm", "Q3", "gemma", rep)
        assert rule["seed_source"] == f"gemma:{label}" == ref["seed_source"]
        assert rule["text"] == ref["text"] and rule["card"]
        assert rule["rule_ids"] == [] and rule["rule_reason"] == "the anchor's relative"
    for rep in (1, 2, 3):
        assert _slot(doc, "dev", "D3", "rule", rep)["seed_source"] == "gemma:dev"
        assert _slot(doc, "dev", "D3", "rule", rep)["text"] == _slot(doc, "dev", "D3", "gemma", rep)["text"]
    assert doc["rule"]["dev"]["D3"] == {"ids": [], "reason": "the anchor's relative"}


def test_only_taken_dev_questions_and_every_confirm_question(syn):
    _lay, _info, doc, _ = syn
    assert doc["items"] == {"confirm": ["Q1", "Q2", "Q3", "Q4"], "dev": ["D1", "D3"]}
    assert doc["not_fired"] == {"confirm": [], "dev": ["D2"]}
    assert not any(s["item"] == "D2" for s in doc["slots"])
    assert len(doc["slots"]) == (4 + 2) * 2 * C.REPS


def test_slots_record_the_guard_and_the_pins(syn):
    lay, info, doc, _ = syn
    q4 = _slot(doc, "confirm", "Q4", "rule", 1)
    assert q4["guard_blocked"] == ["J06"]
    on = B.engine.cards(lay.view, ["J06"])
    assert q4["text"] == on["g_block"] and q4["rows_dropped"] == len(on["rows_dropped"])
    assert _slot(doc, "confirm", "Q1", "rule", 1)["guard_blocked"] == []
    for s in doc["slots"]:
        assert (s["layer_sha256"], s["lexicon_sha256"], s["backend_sha256"]) == \
            (lay.sha256, info["lexicon_sha256"], B.sha256)
    assert doc["header"]["layer_sha256"] == lay.sha256 and doc["header"]["backend_files_sha256"] == B.files_sha256


def test_a_card_not_from_the_guarded_engine_is_refused(syn, monkeypatch):
    lay, _info, _doc, _ = syn
    card = B.card.card_from_rule(lay, ("J03",))
    assert K.card_fields(lay, card)["text"] == card.text
    cards = B.engine.cards
    monkeypatch.setattr(B.engine, "cards", lambda V, seeds, **kw: {**cards(V, seeds, **kw), "g_block": "另一張"})
    with pytest.raises(SystemExit, match="guarded engine"):
        K.card_fields(lay, card)


def test_an_untaken_confirm_question_gets_no_card_in_either_arm(tmp_path, syn):
    lay, info, _doc, _ = syn
    items = [UNTAKEN]
    sets = {"confirm": K.SetSpec(items, {k: {"Q9": {"kind": "raw", "text": "以色列｜暗利", "truncated": False}}
                                         for k in "abc"}, only_fired=False)}
    doc = K.build_cards(lay, info, sets)
    assert doc["not_fired"]["confirm"] == ["Q9"] and not any(s["card"] for s in doc["slots"])


# ---------------------------------------------------------------- jobs

def test_jobs_interleave_the_arms_question_by_question(syn):
    _lay, _info, doc, items = syn
    jobs = J.build_jobs(doc, items)
    assert len(jobs) == (4 + 2) * 2 * C.REPS and len({j["job_id"] for j in jobs}) == len(jobs)
    firsts = []
    for k in range(0, len(jobs), 2):
        a, b = jobs[k], jobs[k + 1]
        assert (a["set"], a["item"], a["rep"]) == (b["set"], b["item"], b["rep"])
        assert {a["arm"], b["arm"]} == {"rule", "gemma"}
        firsts.append(a["arm"])
    assert firsts[:6] == ["rule", "gemma", "rule", "gemma", "rule", "gemma"]   # rotated by question index
    assert [j["rep"] for j in jobs[::12]] == [1, 2, 3]                          # rep -> set -> question -> arm


def test_job_prompts_are_g_autos(syn):
    _lay, _info, doc, items = syn
    by_id = {it["id"]: it for its in items.values() for it in its}
    for j in J.build_jobs(doc, items):
        s = _slot(doc, j["set"], j["item"], j["arm"], j["rep"])
        it = by_id[j["item"]]
        assert j["system"] == cc.SYSTEM_PROMPT
        assert j["user"] == cc.build_user(cc.build_context(it["sources"]), it["question"], s["text"] or None)
        assert j["card_sha256"] == s["text_sha256"] and j["seed_source"] == s["seed_source"]
        assert j["job_id"] == J.job_id(j["set"], j["item"], j["arm"], j["rep"])
    nocard = next(j for j in J.build_jobs(doc, items) if j["item"] == "Q2" and j["arm"] == "gemma" and j["rep"] == 2)
    assert cc.AUX_LABEL not in nocard["user"]


# ---------------------------------------------------------------- truncation, thresholds, verdict

OPTS = C.OPTIONS


def _rec(**kw):
    return {"type": "answer", "job_id": "j", "content": "答案：x", "done_reason": "stop", "eval_count": 100,
            "prompt_eval_count": 100, **kw}


def test_r3_counts_truncation_and_errors():
    recs = [_rec(), _rec(done_reason="length"), _rec(eval_count=OPTS["num_predict"]),
            _rec(prompt_eval_count=OPTS["num_ctx"] - 5, eval_count=5)]
    assert [S.truncated(r, OPTS) for r in recs] == [False, True, True, True]
    r3 = S.r3(recs, [{"type": "error", "job_id": "e"}], OPTS)
    assert (r3["truncated"], r3["errors"], r3["pass"]) == (3, 1, False)
    assert S.r3([_rec()], [], OPTS)["pass"]
    errors_only = S.r3([_rec(), _rec()], [{"type": "error", "job_id": "e"}], OPTS)     # no truncation
    assert (errors_only["truncated"], errors_only["errors"], errors_only["pass"]) == (0, 1, False)
    assert errors_only["error_ids"] == ["e"]


def test_the_threshold_boundary_passes():
    assert S.threshold_pass(-0.05) and S.threshold_pass(-0.1 / 2) and S.threshold_pass(0.0)
    assert not S.threshold_pass(-0.0501)
    rows = {"q1": {"unit": "U1", "mean": {"rule": 0.4, "gemma": 0.5}},
            "q2": {"unit": "U1", "mean": {"rule": 0.4, "gemma": 0.5}},
            "q3": {"unit": "U2", "mean": {"rule": 1.0, "gemma": 1.0}}}
    units, delta = S.unit_delta(rows)
    assert units == pytest.approx({"U1": -0.1, "U2": 0.0}) and delta == pytest.approx(-0.05)
    assert S.threshold_pass(delta)
    rows["q3"]["mean"]["rule"] = 0.999
    assert not S.threshold_pass(S.unit_delta(rows)[1])
    assert S.item_delta({"d1": {"mean": {"rule": 0.9, "gemma": 1.0}}, "d2": {"mean": {"rule": 1.0, "gemma": 1.0}}}) \
        == pytest.approx(-0.05)


OK_R3 = {"truncated": 0, "errors": 0, "pass": True}
ERR_R3 = {"truncated": 0, "errors": 3, "pass": False}


def test_the_verdict_needs_every_rule_and_says_in_sample():
    v = S.verdict(-0.05, -0.02, OK_R3, missing=[], digest="ok")
    assert v["result"] == "pass" and v["pass"] and v["R1"]["pass"] and v["R2"]["pass"] and "樣本內" in v["wording"]
    assert any("非劣性" in n for n in v["notes"]) and any("932d2242" in n for n in v["notes"])
    assert not S.verdict(-0.06, 0.0, OK_R3, [], "ok")["pass"]
    assert not S.verdict(0.0, -0.06, OK_R3, [], "ok")["pass"]
    assert not S.verdict(0.0, 0.0, {"truncated": 1, "errors": 0, "pass": False}, [], "ok")["pass"]
    assert not S.verdict(0.0, 0.0, ERR_R3, [], "ok")["pass"]
    stop = S.verdict(-0.2, 0.0, OK_R3, [], "ok")
    assert stop["result"] == "fail" and "停" in stop["wording"] and "樣本內" in stop["wording"]


def test_the_verdict_on_an_unfinished_void_or_unknown_run():
    left = ["RS|dev|D1|rule|1"]
    inc = S.verdict(0.0, 0.0, OK_R3, left, "ok")
    assert (inc["result"], inc["pass"]) == ("incomplete", False) and "續跑" in inc["wording"]
    assert "重跑" not in inc["wording"]
    # stopped before the after-check (interrupted, or three errors in a row): not void, resume it
    unf = S.verdict(0.0, 0.0, OK_R3, [], "unfinished")
    assert unf["result"] == "incomplete" and "續跑" in unf["wording"] and "重跑" not in unf["wording"]
    # errors are final: R3 has failed already, the rest is not judged
    err = S.verdict(None, None, ERR_R3, left, "unfinished")
    assert (err["result"], err["pass"]) == ("fail", False) and "R3" in err["wording"] and "未判" in err["wording"]
    assert "重跑" not in err["wording"]
    void = S.verdict(0.0, 0.0, OK_R3, [], "mismatch")
    assert (void["result"], void["pass"]) == ("void_digest", False) and "--rerun-of" in void["wording"]
    assert S.verdict(0.0, 0.0, ERR_R3, left, "mismatch")["result"] == "void_digest"
    unk = S.verdict(0.0, 0.0, OK_R3, [], "unknown")
    assert (unk["result"], unk["pass"]) == ("digest_unknown", False) and "續跑" in unk["wording"]
    assert "--rerun-of" not in unk["wording"]


def test_a_dry_run_verdict_is_never_a_pass():
    v = S.verdict(0.0, 0.0, OK_R3, [], "ok", dry_run=True)
    assert (v["result"], v["pass"], v["dry_judgment"]) == ("dry_run", False, "pass")
    assert v["wording"].startswith("（假 chat，分數無意義）")
    assert S.verdict(-0.2, 0.0, OK_R3, [], "ok", dry_run=True)["dry_judgment"] == "fail"


def test_fake_chat_answers_from_the_card():
    user = cc.build_user("ctx", "q", "列1\n依上列資料推算：\n甲之後第1位王：乙（父甲）")
    assert R.fake_chat("s", user, OPTS)["content"].endswith("答案：乙（父甲）")
    assert "答案：" in R.fake_chat("s", cc.build_user("ctx", "q", None), OPTS)["content"]


# ---------------------------------------------------------------- A4' card check

def _a4_rows(lay, items, override=None):
    rows = []
    for it in items:
        rs = B.seeds.rule_seeds(lay, it["question"])
        card = B.card.card_from_rule(lay, rs.ids) if rs.ids else None
        aux = None if card is None else {"kind": "regnal", "text": card.text, "seeds": [], "kings": list(card.kings),
                                         "lines": card.lines, "evidence": [], "layer_sha256": lay.sha256,
                                         "seed_source": "rule"}
        if not rs.ids:
            aux = {"kind": "regnal", "text": "（gemma 卡）", "seeds": [], "kings": [], "lines": 1, "evidence": [],
                   "layer_sha256": lay.sha256, "seed_source": "gemma"}
        rows.append({"item": it["id"], "error": None, "answer": "x", "aux_card": aux})
    for iid, change in (override or {}).items():
        row = next(r for r in rows if r["item"] == iid)
        row.update(change.get("row", {}))
        if row["aux_card"] is not None:
            row["aux_card"].update(change.get("aux", {}))
    return rows


def test_a4_check_passes_when_the_staging_cards_are_the_cpu_cards(syn):
    lay, _info, _doc, _ = syn
    rep = A4.check(lay, CONFIRM, _a4_rows(lay, CONFIRM))
    assert rep["pass"] and rep["n"] == 4 and rep["errors"] == 0
    assert rep["text_same"] == 3 and rep["abstained"] == ["Q3"]
    row_text = json.dumps(rep, ensure_ascii=False)
    assert B.card.card_from_rule(lay, ("I01",)).text not in row_text          # no card text in the report


@pytest.mark.parametrize("override, problem", [
    ({"Q1": {"aux": {"text": "另一張卡"}}}, "text"),
    ({"Q2": {"aux": {"seed_source": "gemma"}}}, "seed_source"),
    ({"Q3": {"aux": {"seed_source": "rule"}}}, "seed_source"),
    ({"Q4": {"aux": {"layer_sha256": "0" * 64}}}, "layer_sha256"),
    ({"Q1": {"row": {"error": "HTTP 500"}}}, "error"),
    ({"Q2": {"row": {"aux_card": None}}}, "no card"),
])
def test_a4_check_flags_each_mismatch(syn, override, problem):
    lay, _info, _doc, _ = syn
    rep = A4.check(lay, CONFIRM, _a4_rows(lay, CONFIRM, override))
    assert not rep["pass"]
    bad = [r for r in rep["rows"] if r["problems"]]
    assert len(bad) == 1 and any(problem in p for p in bad[0]["problems"])


def test_a4_check_flags_a_missing_question(syn):
    lay, _info, _doc, _ = syn
    rep = A4.check(lay, CONFIRM, _a4_rows(lay, CONFIRM)[:3])
    assert not rep["pass"] and rep["missing"] == ["Q4"]


def test_a4_check_without_a_layer_sha_in_the_record(syn):
    lay, _info, _doc, _ = syn
    rows = _a4_rows(lay, CONFIRM)
    for r in rows:
        r["aux_card"].pop("layer_sha256")
    assert A4.check(lay, CONFIRM, rows)["pass"]


# ---------------------------------------------------------------- store-backed (in-sample)

CANDIDATE = C.STORE / "reports/regnal_fix_20261019/candidate/regnal_layer.json"
LEXICON = C.STORE / "contracts/b20261019_18aa84ad/routing_lexicon.json"
OLD_LAYER = C.STORE / "layers/relations/relations@a04b67a301dc/regnal_layer.json"
needs_store = pytest.mark.skipif(
    not all(p.exists() for p in (CANDIDATE, LEXICON, OLD_LAYER, C.A_CONFIRM / "items.json", C.A_DEV / "items.json",
                                 *C.SEED_SOURCES.values())),
    reason="the candidate layer, the lexicon or experiment A's records not in the store")


@pytest.fixture(scope="module")
def store_doc():
    lay, info = C.load_layer(CANDIDATE, LEXICON)
    return lay, K.build_cards(lay, info, K.store_sets()), K.store_items()


@needs_store
def test_store_rule_arm_cards_every_confirm_question(store_doc):
    _lay, doc, _items = store_doc
    rule = [s for s in doc["slots"] if s["set"] == "confirm" and s["arm"] == "rule"]
    assert len(rule) == 32 * C.REPS and all(s["card"] and s["seed_source"] == "rule" for s in rule)
    assert doc["not_fired"]["confirm"] == []


@needs_store
def test_store_dev_taken_questions_and_the_one_abstention(store_doc):
    _lay, doc, _items = store_doc
    assert len(doc["items"]["dev"]) == 27
    assert doc["not_fired"]["dev"] == ["SUC_01", "N_SUC_01", "N_KIN_14"]
    abstained = sorted(i for i, r in doc["rule"]["dev"].items() if not r["ids"])
    assert abstained == ["N_SUC_05"]
    assert {s["seed_source"] for s in doc["slots"] if s["item"] == "N_SUC_05" and s["arm"] == "rule"} == {"gemma:dev"}


@needs_store
def test_store_job_count(store_doc):
    _lay, doc, items = store_doc
    jobs = J.build_jobs(doc, items)
    assert len(jobs) == 32 * 3 * 2 + 27 * 3 * 2


@needs_store
def test_store_the_scorers_reproduce_the_recorded_g_auto_scores():
    rep = S.reproduce()
    assert rep["confirm"]["ok"] and rep["confirm"]["n_items"] == 32 and rep["confirm"]["n_units"] == 14
    assert rep["dev"]["ok"] and rep["dev"]["n_items"] == 30


@needs_store
def test_store_the_confirm_adapter_scores_g_auto_records_as_g_auto():
    """G-auto's recorded calls fed in as the rule arm score as score_c scored them."""
    items = K.store_items()["confirm"]
    recs = C.cc.done_jobs(C.A_CONFIRM / "gen_arms.jsonl")
    scores = C.read_json(C.A_CONFIRM / "scores.json")["items"]
    by_job = {J.job_id("confirm", it["id"], arm, rep): recs[f"A|{it['id']}|G-auto|{rep}"]
              for it in items for arm in ("rule", "gemma") for rep in (1, 2, 3)}
    per, missing = S.score_confirm(items, by_job, C.ref_view(), C.OPTIONS["num_ctx"])
    assert missing == []
    for it in items:
        assert per[it["id"]]["mean"]["rule"] == scores[it["id"]]["mean"]["G-auto"]


@needs_store
def test_store_on_experiment_as_layer_unguarded_the_set_a_prompts_are_g_autos(monkeypatch):
    """The gemma arm's set-a prompts, built on experiment A's layer without the S4 guard, are the
    recorded G-auto rep-1 prompts byte for byte (the context is the item's G-auto context)."""
    cards = B.engine.cards
    monkeypatch.setattr(B.engine, "cards", lambda V, seeds, **kw: cards(V, seeds, **{**kw, "guard": False}))
    lay, info = C.load_layer(OLD_LAYER, LEXICON)
    sets = K.store_sets()
    doc = K.build_cards(lay, info, {"confirm": sets["confirm"]})
    jobs = {(j["item"], j["rep"]): j for j in J.build_jobs(doc, {"confirm": K.store_items()["confirm"]})
            if j["arm"] == "gemma"}
    recorded = {j["item"]: j for j in C.read_json(C.A_CONFIRM / "arms_jobs.json")
                if j["arm"] == "G-auto" and j["rep"] == 1}
    assert len(recorded) == 32
    for item, rec in recorded.items():
        assert (jobs[(item, 1)]["system"], jobs[(item, 1)]["user"]) == (rec["system"], rec["user"]), item


def _mean(xs):
    return sum(xs) / len(xs)


@needs_store
def test_store_score_run_wires_each_arm_into_its_delta(tmp_path, store_doc):
    """Recorded calls with known scores through the runner and score_run: the rule arm takes experiment A's
    G-auto calls, the gemma arm its B0 calls (dev reps 1, 2, 1); R1 and R2 must be the deltas computed here
    from A's scores.json alone, per unit (confirm) and per question (dev)."""
    _lay, doc, items = store_doc
    jobs = J.build_jobs(doc, items)
    recorded = {"confirm": C.cc.done_jobs(C.A_CONFIRM / "gen_arms.jsonl"),
                "dev": C.cc.done_jobs(C.A_DEV / "gen_arms.jsonl")}
    src_arm, dev_rep = {"rule": "G-auto", "gemma": "B0"}, {1: 1, 2: 2, 3: 1}

    def source(j):
        rep = j["rep"] if j["set"] == "confirm" else dev_rep[j["rep"]]
        return recorded[j["set"]][f"A|{j['item']}|{src_arm[j['arm']]}|{rep}"]
    feed = iter([source(j) for j in jobs])
    keys = ("content", "thinking_chars", "prompt_eval_count", "eval_count", "done_reason", "elapsed_s")

    def chat(system, user, options):
        rec = next(feed)
        return {k: rec.get(k) for k in keys}
    out = tmp_path / "run"
    # these are the real jobs on the real layer: the store's formal run of them (r4_run1) must not
    # refuse this replay, so the one-formal-run registry is looked up in tmp_path only
    R.execute(jobs, out, chat, fake_api(), log=lambda *_a: None, runs_root=tmp_path)
    _scores, v = S.score_run(out, doc, jobs, items)

    sc = C.read_json(C.A_CONFIRM / "scores.json")["items"]
    units: dict = {}
    for it in items["confirm"]:
        units.setdefault(it["unit"], []).append(sc[it["id"]]["mean"]["G-auto"] - sc[it["id"]]["mean"]["B0"])
    want_r1 = _mean([_mean(d) for d in units.values()])
    sd = C.read_json(C.A_DEV / "scores.json")["items"]
    want_r2 = _mean([_mean([sd[i]["reps"][f"G-auto|{dev_rep[r]}"]["score"] for r in (1, 2, 3)])
                     - _mean([sd[i]["reps"][f"B0|{dev_rep[r]}"]["score"] for r in (1, 2, 3)])
                     for i in doc["items"]["dev"]])
    assert abs(want_r1) > 0.05 and abs(want_r2) > 0.05 and abs(want_r1 - want_r2) > 0.01   # tells arms, sets apart
    assert v["R1"]["delta"] == pytest.approx(want_r1) and v["R2"]["delta"] == pytest.approx(want_r2)
    assert v["n_units"] == 14 and v["confirm_units_delta"] == pytest.approx({u: _mean(d) for u, d in units.items()})
    assert v["R3"]["pass"] and v["missing"] == [] and v["dry_run"] is False
    want = "pass" if S.threshold_pass(want_r1) and S.threshold_pass(want_r2) else "fail"
    assert v["result"] == want


@needs_store
def test_store_synthetic_questions_are_not_store_questions():
    store = [it["question"] for its in K.store_items().values() for it in its]
    for it in [*CONFIRM, *DEV, UNTAKEN]:
        best = max(difflib.SequenceMatcher(None, it["question"], q).ratio() for q in store)
        assert best <= 0.8, it["id"]


@needs_store
def test_store_dry_run_end_to_end(tmp_path):
    rep = R.dry_run(CANDIDATE, LEXICON, tmp_path / "dry")
    assert rep["n_jobs"] == 32 * 3 * 2 + 27 * 3 * 2
    v = rep["verdict"]
    assert (v["result"], v["pass"]) == ("dry_run", False)       # a dry run is never a pass
    assert v["dry_judgment"] in ("pass", "fail") and v["R3"]["pass"]
    saved = C.read_json(tmp_path / "dry" / "verdict.json")
    assert saved["result"] == "dry_run" and saved["wording"].startswith("（假 chat，分數無意義）")
    est = rep["estimate"]
    assert est["seconds"] > est["lower_bound"]["seconds"] > 0
    for name in ("cards.json", "jobs.json", R.GEN, R.RUN_META, "scores.json", "verdict.json"):
        assert (tmp_path / "dry" / name).is_file()

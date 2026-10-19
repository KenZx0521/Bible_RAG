"""Rule-seed regression harness (evaluation/experiments/2026-10-19_regnal_seed/).

Ollama is never called: generation goes through fake chats and the model check through a fake
/api/ps and /api/tags. The synthetic tests run on a small two-kingdom regnal layer and template
questions built here (no scripture text, no question of experiment A's sets). The store-backed
tests at the end read the candidate layer, the routing lexicon and experiment A's records; they
skip when the store is not mounted, and they print no question or card text.
"""

import json
import sys
import urllib.error
from pathlib import Path

import pytest

RS = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-19_regnal_seed"
if str(RS) not in sys.path:
    sys.path.insert(0, str(RS))

import a4_card_check as A4  # noqa: E402
import rs_cards as K  # noqa: E402
import rs_common as C  # noqa: E402
import rs_jobs as J  # noqa: E402
import rs_run as R  # noqa: E402
import rs_score as S  # noqa: E402

B = C.backend()
cc = C.cc
REPO = Path(__file__).resolve().parents[2]


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


# ---------------------------------------------------------------- synthetic layer, lexicon, items

ISRAEL = ("耶羅波安", "拿答<耶羅波安", "巴沙", "以拉<巴沙", "心利", "暗利")
JUDAH = ("羅波安", "亞比央<羅波安", "亞撒<亞比央", "約沙法<亞撒", "約蘭<約沙法", "亞哈謝<約蘭")
# an alternative accession age for J06: the S4 guard takes its born line off
CONFLICT = ["J06", "亞哈謝", "age", [33, "1ki.11.2", "ki"], [53, "2ch.22.2", "ch"]]


def _node(nid, kd, spec, order):
    nm, _, father = spec.partition("<")
    fields = {"reign": [8 + order % 5, f"1ki.{order}.1", "ki"], "age": [30 + order % 4, f"1ki.{order}.2", "ki"]}
    if father:
        fields["father"] = [father, f"1ki.{order}.3", "succ"]
    return {"id": nid, "kingdom": kd, "name": nm, "aliases": [], "fields": fields, "evidence": [f"1ki.{order}.1"],
            "pending": False, "order": order, "created_by": "t", "has_acc": True}


def layer_doc(conflicts=(CONFLICT,)):
    nodes, edges = [], []
    for kd, specs in (("I", ISRAEL), ("J", JUDAH)):
        for i, spec in enumerate(specs, 1):
            nodes.append(_node(f"{kd}{i:02d}", kd, spec, len(nodes)))
            if i > 1:
                edges.append([f"{kd}{i - 1:02d}", f"{kd}{i:02d}", "son", "1ki.1.1"])
    return {"policy": "occ", "fn_rule": "slot", "nodes": nodes, "edges": edges, "fallback_edges": [], "syncs": [],
            "conflicts": list(conflicts), "log": [], "occ_alias": [], "union_classes": None}


def lexicon_doc():
    from ragcommon.tests.lexicon_doc import document, name
    return document(names=[name("掃羅", "nm:5b0000000001", "Person")])


def _src(i):
    return {"book_name": "列王紀上", "chapter_num": i, "title": "合成", "verse_range": "1-2",
            "content": f"（合成段落 {i}）"}


def _item(iid, question, unit=None):
    it = {"id": iid, "question": question, "sources": [_src(1), _src(2)]}
    return {**it, "unit": unit} if unit else it


CONFIRM = [_item("Q1", "耶羅波安之後的第二位王是誰？", "U1"),       # rule I01; set a names two kings
           _item("Q2", "亞撒之後的第三位王是誰？", "U1"),           # rule J03 = set a's card
           _item("Q3", "亞比央的兒子之後的第一位王是誰？", "U2"),   # the rules abstain: gemma fallback
           _item("Q4", "亞哈謝出生時在位的猶大王是誰？", "U2")]     # rule J06: the guard takes its born line
DEV = [_item("D1", "巴沙之後的第二位王是誰？"),
       _item("D2", "暗利是誰？"),                                  # no cue: not taken
       _item("D3", "以拉的兒子之後的第二位王是誰？")]              # the rules abstain: gemma fallback

RAW_A = {"Q1": "以色列｜耶羅波安\n以色列｜拿答", "Q2": "猶大｜亞撒", "Q3": "猶大｜亞比央", "Q4": "猶大｜亞哈謝"}
AUX_B = {"Q1": ["以色列｜耶羅波安"], "Q2": None, "Q3": ["猶大｜亞比央"], "Q4": ["猶大｜亞哈謝"]}
AUX_C = {"Q1": ["以色列｜耶羅波安", "以色列｜拿答"], "Q2": ["猶大｜亞撒"], "Q3": ["猶大｜亞比央"],
         "Q4": ["猶大｜亞哈謝"]}
RAW_DEV = {"D1": "以色列｜巴沙", "D2": "以色列｜暗利", "D3": "以色列｜以拉"}


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def _gen_seed_rows(texts):
    return [{"type": "answer", "job_id": f"A|{i}|seed|1", "item": i, "content": t, "done_reason": "stop",
             "eval_count": 10, "prompt_eval_count": 10} for i, t in texts.items()]


def _response_rows(seeds):
    return [{"item": i, "error": None, "answer": "x",
             "aux_card": None if s is None else {"kind": "regnal", "text": "t", "seeds": s, "kings": [],
                                                  "lines": 1, "evidence": [], "layer_sha256": "0" * 64}}
            for i, s in seeds.items()]


@pytest.fixture
def syn(tmp_path):
    layer_p = tmp_path / "regnal_layer.json"
    layer_p.write_text(json.dumps(layer_doc(), ensure_ascii=False), encoding="utf-8")
    lex_p = tmp_path / "routing_lexicon.json"
    lex_p.write_text(json.dumps(lexicon_doc(), ensure_ascii=False), encoding="utf-8")
    lay, info = C.load_layer(layer_p, lex_p)
    seeds = {"a": K.raw_seeds(_write_jsonl(tmp_path / "gen_seed_a.jsonl", _gen_seed_rows(RAW_A))),
             "b": K.aux_seeds(_write_jsonl(tmp_path / "responses_b.jsonl", _response_rows(AUX_B))),
             "c": K.aux_seeds(_write_jsonl(tmp_path / "responses_c.jsonl", _response_rows(AUX_C))),
             "dev": K.raw_seeds(_write_jsonl(tmp_path / "gen_seed_dev.jsonl", _gen_seed_rows(RAW_DEV)))}
    sets = {"confirm": K.SetSpec(CONFIRM, {k: seeds[k] for k in "abc"}, only_fired=False),
            "dev": K.SetSpec(DEV, {"dev": seeds["dev"]}, only_fired=True)}
    doc = K.build_cards(lay, info, sets)
    return lay, info, doc, {"confirm": CONFIRM, "dev": DEV}


def _slot(doc, set_, item, arm, rep):
    return K.slot_map(doc)[(set_, item, arm, rep)]


# ---------------------------------------------------------------- recorded seed formats

def test_recorded_seeds_raw_and_parsed(tmp_path):
    rows = _gen_seed_rows({"X": "猶大｜亞撒"}) + [dict(_gen_seed_rows({"Y": "猶大｜亞撒"})[0], done_reason="length")]
    raw = K.raw_seeds(_write_jsonl(tmp_path / "s.jsonl", rows))
    assert raw["X"] == {"kind": "raw", "text": "猶大｜亞撒", "truncated": False}
    assert raw["Y"] == {"kind": "raw", "text": "", "truncated": True}   # a truncated seed call: no seeds (A)
    rows = _response_rows({"X": ["猶大｜亞撒", "以色列｜巴沙"], "Y": None})
    aux = K.aux_seeds(_write_jsonl(tmp_path / "r.jsonl", rows))
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


def test_an_untaken_confirm_question_gets_no_card_in_either_arm(tmp_path, syn):
    lay, info, _doc, _ = syn
    items = [_item("Q9", "暗利是誰？", "U9")]
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


# ---------------------------------------------------------------- runner: digest, resume, errors

EXPECTED = C.EXPECTED_DIGEST


def fake_api(ps_digest=EXPECTED, tags_digest=None, ps_has_model=True):
    def get(path):
        if path == "/api/ps":
            return {"models": [{"name": C.MODEL, "model": C.MODEL, "digest": ps_digest}] if ps_has_model else []}
        if path == "/api/tags":
            return {"models": [{"name": C.MODEL, "model": C.MODEL, "digest": tags_digest}] if tags_digest else []}
        raise AssertionError(path)
    return get


class CountingChat:
    def __init__(self, fail_after=None, error=None):
        self.calls, self.fail_after, self.error = 0, fail_after, error

    def __call__(self, system, user, options):
        if self.error is not None:
            self.calls += 1
            raise self.error
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise KeyboardInterrupt("simulated stop")
        self.calls += 1
        return R.fake_chat(system, user, options)


def _small_jobs(n=6):
    return [{"job_id": f"RS|dev|D{i}|rule|1", "exp": "RS", "set": "dev", "item": f"D{i}", "arm": "rule", "rep": 1,
             "kind": "gen", "seed_source": "rule", "card_sha256": None, "system": "s", "user": f"u{i}"}
            for i in range(n)]


def test_digest_check(monkeypatch):
    assert R.model_digest(fake_api()) == (EXPECTED, "ps")
    assert R.model_digest(fake_api(ps_has_model=False, tags_digest=EXPECTED)) == (EXPECTED, "tags")
    assert R.model_digest(fake_api(ps_has_model=False)) == (None, None)

    def down(path):
        raise urllib.error.URLError("refused")
    assert R.model_digest(down) == (None, None)
    before, after = {"when": "before", "digest": EXPECTED}, {"when": "after", "digest": EXPECTED}
    assert R.digest_ok({"digest_checks": [before, after]})
    assert not R.digest_ok({"digest_checks": [before]})                       # never checked after the run
    assert not R.digest_ok({"digest_checks": [before, dict(after, digest="f" * 64)]})
    fake = [dict(before, fake=True), dict(after, fake=True)]
    assert not R.digest_ok({"digest_checks": fake}) and R.digest_ok({"digest_checks": fake, "dry_run": True})


def test_a_wrong_digest_refuses_before_any_call(tmp_path):
    chat = CountingChat()
    with pytest.raises(SystemExit, match="digest"):
        R.execute(_small_jobs(), tmp_path / "o", chat, fake_api(ps_digest="0" * 64))
    with pytest.raises(SystemExit, match="digest"):
        R.execute(_small_jobs(), tmp_path / "o", chat, fake_api(ps_has_model=False))
    assert chat.calls == 0 and not (tmp_path / "o" / R.GEN).exists()


def test_a_run_records_meta_and_resume_skips_done_jobs(tmp_path):
    out, jobs = tmp_path / "o", _small_jobs()
    with pytest.raises(KeyboardInterrupt):
        R.execute(jobs, out, CountingChat(fail_after=4), fake_api())
    assert len(R.done_ids(out / R.GEN)) == 4
    chat = CountingChat()
    meta = R.execute(jobs, out, chat, fake_api())
    assert chat.calls == 2 and meta["n_done"] == 6 and meta["n_errors"] == 0
    assert meta["jobs_sha256"] == J.jobs_sha256(jobs) and meta["options"] == C.OPTIONS
    assert (meta["digest_before"], meta["digest_after"], meta["attempt"]) == (EXPECTED, EXPECTED, 1)
    assert meta["resumed"]
    again = CountingChat()
    R.execute(jobs, out, again, fake_api())
    assert again.calls == 0
    recs = [json.loads(line) for line in (out / R.GEN).read_text(encoding="utf-8").splitlines()]
    assert all(r["type"] == "answer" for r in recs) and {r["job_id"] for r in recs} == {j["job_id"] for j in jobs}


def test_other_jobs_in_the_same_directory_are_refused(tmp_path):
    out, jobs = tmp_path / "o", _small_jobs()
    R.execute(jobs, out, CountingChat(), fake_api())
    changed = [dict(jobs[0], user="other")] + jobs[1:]
    with pytest.raises(SystemExit, match="jobs"):
        R.execute(changed, out, CountingChat(), fake_api())
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / R.GEN).write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="run_meta"):
        R.execute(jobs, bare, CountingChat(), fake_api())


def test_errors_are_recorded_never_retried_and_three_in_a_row_stop(tmp_path):
    out, jobs = tmp_path / "o", _small_jobs()
    chat = CountingChat(error=urllib.error.URLError("refused"))
    with pytest.raises(SystemExit, match="consecutive"):
        R.execute(jobs, out, chat, fake_api())
    assert chat.calls == R.MAX_CONSECUTIVE_ERRORS
    ok = CountingChat()
    meta = R.execute(jobs, out, ok, fake_api())
    assert ok.calls == len(jobs) - R.MAX_CONSECUTIVE_ERRORS      # the errored jobs are not run again
    assert meta["n_errors"] == R.MAX_CONSECUTIVE_ERRORS
    parse = CountingChat(error=ValueError("bad json"))
    with pytest.raises(SystemExit):
        R.execute(jobs, tmp_path / "p", parse, fake_api())
    assert len(R.error_lines(tmp_path / "p" / R.GEN)) == R.MAX_CONSECUTIVE_ERRORS


def test_a_rerun_only_once_and_only_after_a_digest_mismatch(tmp_path):
    jobs = _small_jobs()
    calls = {"n": 0}

    def drifting(path):              # the expected digest before the run, another one after it
        calls["n"] += 1
        return fake_api(ps_digest=EXPECTED if calls["n"] == 1 else "f" * 64)(path)
    first = R.execute(jobs, tmp_path / "r1", CountingChat(), drifting)
    assert first["digest_after"] == "f" * 64 and not R.digest_ok(first) and first["attempt"] == 1
    R.execute(jobs, tmp_path / "c1", CountingChat(), fake_api())
    with pytest.raises(SystemExit, match="digest"):          # the clean run may not be redone
        R.execute(jobs, tmp_path / "c2", CountingChat(), fake_api(), rerun_of=tmp_path / "c1")
    with pytest.raises(SystemExit, match="jobs"):            # a rerun is the same jobs
        R.execute(_small_jobs(5), tmp_path / "x", CountingChat(), fake_api(), rerun_of=tmp_path / "r1")
    with pytest.raises(SystemExit, match="digest"):          # a void run is not resumed either
        R.execute(jobs, tmp_path / "r1", CountingChat(), fake_api())
    second = R.execute(jobs, tmp_path / "r2", CountingChat(), fake_api(), rerun_of=tmp_path / "r1")
    assert (second["attempt"], second["rerun_of"]) == (2, str((tmp_path / "r1").resolve()))
    assert R.digest_ok(second)
    assert C.read_json(tmp_path / "r1" / R.RUN_META)["rerun_by"] == str((tmp_path / "r2").resolve())
    R.execute(jobs, tmp_path / "r2", CountingChat(), fake_api(), rerun_of=tmp_path / "r1")   # resuming it is fine
    with pytest.raises(SystemExit, match="once"):            # r1 was redone already
        R.execute(jobs, tmp_path / "r3", CountingChat(), fake_api(), rerun_of=tmp_path / "r1")
    with pytest.raises(SystemExit, match="once"):            # a rerun is never redone
        R.execute(jobs, tmp_path / "r4", CountingChat(), fake_api(), rerun_of=tmp_path / "r2")


def test_store_writes_only_go_to_the_new_directory(tmp_path):
    assert C.writable(tmp_path / "x") == (tmp_path / "x").resolve()
    assert C.writable(C.OUT_ROOT / "dry_run") == (C.OUT_ROOT / "dry_run").resolve()
    for frozen in (C.STORE / "reports/kg_cards_20261018/A_confirm", C.STORE / "reports/regnal_card_20261019/a4x",
                   C.STORE / "layers/x", C.STORE / "contracts/x", C.STORE / "releases/x", C.STORE / "reports/other"):
        with pytest.raises(SystemExit):
            C.writable(frozen)


def test_the_prereg_gate():
    sha = "1" * 64
    draft = f"{C.DRAFT_MARK}\n層 {C.LAYER_SHA_PLACEHOLDER}"
    assert C.prereg_problems(draft, sha) == ["draft", "placeholder", "layer sha"]
    assert C.prereg_problems(f"正式版\n{C.LAYER_LINE} {sha} |", sha) == []
    assert C.prereg_problems(f"正式版\n{C.LAYER_LINE} {'2' * 64} |\n§9 {sha}", sha) == ["layer sha"]   # §1 only
    text = (RS / "prereg.md").read_text(encoding="utf-8")
    assert C.DRAFT_MARK in text and C.LAYER_SHA_PLACEHOLDER in text      # the committed draft
    assert sum(line.startswith(C.LAYER_LINE) for line in text.splitlines()) == 1
    assert C.prereg_problems(text, sha)


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


def test_the_verdict_needs_every_rule_and_says_in_sample():
    ok_r3 = {"truncated": 0, "errors": 0, "pass": True}
    v = S.verdict(-0.05, -0.02, ok_r3, missing=[], digest_ok=True)
    assert v["pass"] and v["R1"]["pass"] and v["R2"]["pass"] and "樣本內" in v["wording"]
    assert any("非劣性" in n for n in v["notes"]) and any("932d2242" in n for n in v["notes"])
    assert not S.verdict(-0.06, 0.0, ok_r3, [], True)["pass"]
    assert not S.verdict(0.0, -0.06, ok_r3, [], True)["pass"]
    assert not S.verdict(0.0, 0.0, {"truncated": 1, "errors": 0, "pass": False}, [], True)["pass"]
    assert S.verdict(0.0, 0.0, ok_r3, ["RS|dev|D1|rule|1"], True)["result"] == "incomplete"
    assert S.verdict(0.0, 0.0, ok_r3, [], False)["result"] == "void_digest"
    stop = S.verdict(-0.2, 0.0, ok_r3, [], True)
    assert stop["result"] == "fail" and "停" in stop["wording"] and "樣本內" in stop["wording"]


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


@needs_store
def test_store_dry_run_end_to_end(tmp_path):
    rep = R.dry_run(CANDIDATE, LEXICON, tmp_path / "dry")
    assert rep["n_jobs"] == 32 * 3 * 2 + 27 * 3 * 2
    assert rep["verdict"]["result"] in ("pass", "fail") and rep["verdict"]["R3"]["pass"]
    assert rep["estimate"]["seconds"] > 0
    for name in ("cards.json", "jobs.json", R.GEN, R.RUN_META, "scores.json", "verdict.json"):
        assert (tmp_path / "dry" / name).is_file()

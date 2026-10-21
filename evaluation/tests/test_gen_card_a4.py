"""Plan A4's runner and scorer (evaluation/experiments/2026-10-21_gen_card/, plan §3.2) with fakes: no network, no
Ollama, no docker. Synthetic items, cards and answers (made-up ids, numbers and strings); every run writes tmp_path
(a dry-run Writer). The GT check's pick is compared with smoke20's by question id on the repository's GT v2. The
store-backed tests at the end read the pinned inputs and assert counts only.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import urllib.error
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest

A4_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-21_gen_card"
if str(A4_DIR) not in sys.path:
    sys.path.insert(0, str(A4_DIR))

import a4_g as A  # noqa: E402
import a4_score as SC  # noqa: E402

cc, GC = A.cc, A.GC
BUILD = "b_test_new"
PLAN_DOC = A.REPO / "docs/records/2026-10-21_gen_card_integration_plan.md"
ENV = ["LLM_TEMPERATURE=0.1", "LLM_MAX_TOKENS=10000", f"OLLAMA_MODEL={A.MODEL}", "SECRET_TOKEN=zzz"]
STORE_OK = all((GC.RUN_ROOT / n).is_file() for n in A.INPUT_SHA256)
needs_store = pytest.mark.skipif(not STORE_OK, reason="store not mounted")


# ---------------------------------------------------------------- synthetic items, cards and fakes
def item(sid: str, gold: int) -> dict:
    return {"id": sid, "sid": sid, "question": f"QQ-{sid}-synthetic-question", "gold": gold, "context_from": f"ps:x.{sid}",
            "keys": [{"type": "arith", "value": gold, "classes": ["A", "Y"], "ordinal": False, "basis": ["x.1.1"]}],
            "distractors": []}


def world(n: int = 4, abstain: tuple[str, ...] = ("S01",)) -> tuple[list[dict], dict]:
    items = [item(f"S{i:02d}", 100 + i) for i in range(n)]
    cards = {it["sid"]: {"g": None if it["sid"] in abstain else
                         {"g_block": f"CARD-{it['sid']}-g", "t_block": f"CARD-{it['sid']}-t"}} for it in items}
    return items, cards


def generator_join() -> str:
    """The separator backend/utils/generator.py's _build_context joins its blocks with (read as source, no import,
    as test_context_blocks reads AUX_LABEL)."""
    tree = ast.parse((A.REPO / "backend/utils/generator.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_context")
    seps = [n.func.value.value for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "join" and isinstance(n.func.value, ast.Constant)]
    assert len(seps) == 1
    return seps[0]


class Backend:
    """/query: two sources per call whose contexts name the call; ON carries the card; answers the gold unless
    ``values`` says otherwise; ``faults`` {(sid, arm, nth call): kind} breaks one call."""

    def __init__(self, items: list[dict], cards: dict, build: str = BUILD):
        self.by_q, self.cards, self.build = {it["question"]: it for it in items}, cards, build
        self.bodies, self.n, self.faults, self.values = [], Counter(), {}, {}

    def __call__(self, url, body, timeout):
        it = self.by_q[body["question"]]
        sid, arm = it["sid"], "OFF" if body.get("use_gen_card") is False else "ON"
        self.n[sid, arm] += 1
        k, fault = self.n[sid, arm], self.faults.get((sid, arm, self.n[sid, arm]))
        self.bodies.append(body)
        if fault == "http":
            return None, "HTTPError 500", 1.0
        g = self.cards[sid]["g"] if arm == "ON" else None
        aux = None if g is None else {"kind": "gen", "text": g["g_block"], "layer_sha256": SC.GEN_LAYER_SHA256}
        src = {"id": "ck:other", "context": f"[1] X\nctx-{sid}-{arm}-{k}-a", "build_id": self.build,
               "strategy": "hybrid_hybrid", "passage_id": it["context_from"] if k % 2 else "ps:other",
               "split_passage_ids": []}
        src2 = {**src, "id": "ck:second", "context": f"[2] Y\nctx-{sid}-{arm}-{k}-b", "passage_id": "ps:second"}
        data = {"answer": f"step\n答案：{self.values.get((sid, arm), it['gold'])}歲", "sources": [src, src2], "aux_card": aux,
                "intent": {"type": "t"}, "retrieval_stats": {"strategy_errors": {}}}
        sec = 130.0 if fault == "slow" else 1.0
        if fault == "gen_error":
            data["answer"] = A.GENERATION_ERROR_PREFIX + "。"
        elif fault == "infra":
            data["retrieval_stats"]["strategy_errors"] = {"event_registry": "boom"}
        elif fault == "no_source":
            data["sources"] = []
        elif fault == "no_context":
            src["context"] = None
        elif fault == "build":
            src["build_id"] = "b_old"
        elif fault == "card":
            data["aux_card"] = {**aux, "text": aux["text"] + "x"}
        elif fault == "off_card":
            data["aux_card"] = {"kind": "gen", "text": "x", "layer_sha256": SC.GEN_LAYER_SHA256}
        return data, None, sec


class Chat:
    """cards_common.chat: answers the gold unless ``values`` says otherwise; ``faults`` breaks one call."""

    def __init__(self, items: list[dict]):
        self.items, self.calls, self.n, self.faults, self.values = items, [], Counter(), {}, {}

    def __call__(self, system, user, options=None):
        it = next(x for x in self.items if user.endswith("\n" + x["question"]))
        arm = "T-rows-prod" if cc.AUX_LABEL in user else "B0-prod"
        self.n[it["sid"], arm] += 1
        fault = self.faults.get((it["sid"], arm, self.n[it["sid"], arm]))
        self.calls.append({"sid": it["sid"], "arm": arm, "system": system, "user": user, "options": options})
        if fault == "raise":
            raise urllib.error.URLError("down")
        content = "" if fault == "empty" else f"step\n答案：{self.values.get((it['sid'], arm), it['gold'])}歲"
        return {"content": content, "thinking_chars": 3, "prompt_eval_count": 100, "eval_count": 50,
                "done_reason": "length" if fault == "length" else "stop", "elapsed_s": 125.0 if fault == "slow" else 1.0}


class Ollama:
    def __init__(self, ctx_lengths=(131072,), digest=GC.EXPECTED_DIGEST, version=GC.OLLAMA_VERSION):
        self.ctx, self.digest, self.version, self.ps = list(ctx_lengths), digest, version, 0

    def __call__(self, path):
        if path == "/api/version":
            return {"version": self.version}
        if path == "/api/ps":
            self.ps += 1
        n = self.ctx[min(self.ps, len(self.ctx)) - 1] if self.ps else self.ctx[0]
        return {"models": [{"name": A.MODEL, "model": A.MODEL, "digest": self.digest, "context_length": n}]}


def healthy(url: str) -> dict:
    return {"status": "ok", "build_id": BUILD}


def staging(name: str) -> list:
    return [{"Config": {"Env": ENV}, "State": {"Running": True}, "Image": "i"}]


def make_io(items, cards, **kw) -> A.Io:
    logs, sleeps = [], []
    io = A.Io(post=kw.get("post") or Backend(items, cards), chat=kw.get("chat") or Chat(items),
              ollama=kw.get("ollama") or Ollama(), health=kw.get("health") or healthy,
              inspect=kw.get("inspect") or staging, sleep=sleeps.append, log=logs.append)
    io.logs, io.sleeps = logs, sleeps
    return io


def run(tmp_path, items, cards, io, mode="a4", name="run"):
    return A.run(A.MODES[mode], A.Writer(tmp_path / name, dry=True), items, cards, BUILD, io, dry=True)


def calls(tmp_path, name="run") -> list[dict]:
    return A.Writer(tmp_path / name, dry=True).jsonl(A.CALLS)


def meta(tmp_path, name="run") -> dict:
    return A.Writer(tmp_path / name, dry=True).read_json(A.RUN_META)


# ---------------------------------------------------------------- order and pairing
def test_order_is_rep_then_sid_then_on_and_the_rotated_rest_without_t_rows_on_an_abstention():
    items, cards = world(4)
    units = A.plan(items, cards, A.MODES["a4"])
    assert [(r, it["sid"]) for r, it, _a in units] == [(r, f"S{i:02d}") for r in (1, 2, 3) for i in range(4)]
    arms = {it["sid"]: a for r, it, a in units if r == 1}
    assert arms == {"S00": ["ON", "B0-prod", "T-rows-prod", "OFF"], "S01": ["ON", "OFF", "B0-prod"],
                    "S02": ["ON", "OFF", "B0-prod", "T-rows-prod"], "S03": ["ON", "B0-prod", "T-rows-prod", "OFF"]}
    assert [a for _r, _i, a in A.plan(items, cards, A.MODES["prod-check"])] == [["ON"]] * 4


def test_a_full_run_calls_in_plan_order_and_pairs_every_direct_call_with_its_on_context(tmp_path):
    items, cards = world(4)
    io = make_io(items, cards)
    rep = run(tmp_path, items, cards, io)
    xs = calls(tmp_path)
    assert [(x["rep"], x["sid"], x["arm"]) for x in xs] == [(r, it["sid"], a) for r, it, arms in
                                                            A.plan(items, cards, A.MODES["a4"]) for a in arms]
    on = {(x["sid"], x["rep"]): x for x in xs if x["arm"] == "ON"}
    assert {len(o["sources"]) for o in on.values()} == {2}
    for x in xs:
        if x["arm"] in SC.DIRECT:
            o = on[x["sid"], x["rep"]]
            block = None if x["arm"] == "B0-prod" else cards[x["sid"]]["g"]["t_block"]
            joined = generator_join().join(s["context"] for s in o["sources"])
            want = cc.build_user(joined, items[int(x["sid"][1:])]["question"], block)
            assert (x["on_attempt"], x["ctx_sha256"], x["user_sha256"]) == (o["attempt"], o["ctx_sha256"], SC.sha(want))
    assert all(c["system"] == cc.SYSTEM_PROMPT and c["options"] == {"temperature": 0.1, "num_predict": 10000}
               for c in io.chat.calls)
    g = rep["gates"]
    assert rep["state"] == "valid" and rep["judged"] and g["wiring"]["pass"] and g["quality"]["pass"]
    assert g["stop"]["stop"] and not g["propose_prod"]          # every arm answers the gold: Δ 0, CI low 0


def test_ctx_on_joins_the_source_contexts_as_the_generator_joins_its_blocks():
    sources = [{"context": "[1] A\nca"}, {"context": "[2] B\ncb"}, {"context": "[3] C\ncc"}]
    assert A.ctx_on(sources) == generator_join().join(["[1] A\nca", "[2] B\ncb", "[3] C\ncc"])
    assert A.ctx_on(sources[:1]) == "[1] A\nca"


def test_on_sends_no_card_flag_and_off_sends_false():
    items, cards = world(2)
    b = Backend(items, cards)
    c = A.Ctx(A.MODES["a4"], None, cards, BUILD, make_io(items, cards, post=b), [], {}, {"ps": []}, 0)
    A.query_call(c, items[0], "ON")
    A.query_call(c, items[0], "OFF")
    assert b.bodies == [{"question": items[0]["question"], "include_context": True},
                        {"question": items[0]["question"], "include_context": True, "use_gen_card": False}]
    assert A.OPTIONS == cc.OPTIONS and "num_ctx" not in A.OPTIONS


# ---------------------------------------------------------------- per-call voids and reruns
@pytest.mark.parametrize("fault, reason", [("http", "http"), ("gen_error", "generation_error"), ("infra", "infra_failed"),
                                           ("slow", "slow"), ("no_source", "no_source"), ("no_context", "no_context")])
def test_a_void_on_is_rerun_and_its_direct_calls_use_the_new_context(tmp_path, fault, reason):
    items, cards = world(2)
    io = make_io(items, cards)
    io.post.faults[("S00", "ON", 1)] = fault
    rep = run(tmp_path, items, cards, io)
    xs = [x for x in calls(tmp_path) if x["sid"] == "S00" and x["rep"] == 1]
    assert [(x["arm"], x["attempt"], x["void"]) for x in xs][:2] == [("ON", 1, reason), ("ON", 2, None)]
    assert {x["on_attempt"] for x in xs if x["arm"] in SC.DIRECT} == {2}
    assert io.sleeps == [A.BACKOFF_S] and rep["state"] == "valid" and rep["voids"] == {"ON": {reason: 1}}


@pytest.mark.parametrize("fault, reason", [("raise", "error"), ("empty", "empty"), ("slow", "slow")])
def test_a_void_direct_call_reruns_on_the_same_context(tmp_path, fault, reason):
    items, cards = world(2)
    io = make_io(items, cards)
    io.chat.faults[("S00", "B0-prod", 1)] = fault
    rep = run(tmp_path, items, cards, io)
    xs = [x for x in calls(tmp_path) if (x["sid"], x["arm"], x["rep"]) == ("S00", "B0-prod", 1)]
    assert [(x["attempt"], x["void"]) for x in xs] == [(1, reason), (2, None)]
    assert xs[0]["user_sha256"] == xs[1]["user_sha256"] and rep["voids"] == {"B0-prod": {reason: 1}}


def test_a_call_past_its_rerun_cap_voids_the_run_and_the_run_is_never_resumed(tmp_path):
    items, cards = world(2)
    io = make_io(items, cards)
    io.post.faults.update({("S01", "OFF", k): "http" for k in (1, 2, 3)})
    rep = run(tmp_path, items, cards, io)
    xs = [x for x in calls(tmp_path) if (x["sid"], x["arm"]) == ("S01", "OFF")]
    assert [x["attempt"] for x in xs] == [1, 2, 3] and io.sleeps == [5, 10]
    assert rep["state"] == "void" and not rep["judged"] and meta(tmp_path)["state"] == "void"
    assert "S01 OFF r1" in rep["void"][0] and rep["voids"] == {"OFF": {"http": 3}}
    with pytest.raises(SystemExit, match="never resumed"):
        run(tmp_path, items, cards, make_io(items, cards))


def test_a_source_from_another_build_voids_the_run_at_once(tmp_path):
    items, cards = world(2)
    io = make_io(items, cards)
    io.post.faults[("S00", "ON", 1)] = "build"
    rep = run(tmp_path, items, cards, io)
    assert len(calls(tmp_path)) == 1 and rep["state"] == "void" and "build_id" in rep["void"][0]


def interrupted(io: A.Io, at: int) -> A.Io:
    """The at-th direct call raises KeyboardInterrupt (a killed session: no after-check, no t_end)."""
    real, n = io.chat, Counter()

    def chat(system, user, options=None):
        n["calls"] += 1
        if n["calls"] == at:
            raise KeyboardInterrupt
        return real(system, user, options)
    io.chat = chat
    return io


def test_an_interrupted_run_resumes_without_repeating_a_valid_call(tmp_path):
    items, cards = world(3)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, items, cards, interrupted(make_io(items, cards), 3))
    assert len(calls(tmp_path)) == 6 and "t_end" not in meta(tmp_path)["sessions"][-1]
    rep = run(tmp_path, items, cards, make_io(items, cards))
    xs = calls(tmp_path)
    assert len(xs) == rep["n_planned"] and len({(x["sid"], x["arm"], x["rep"]) for x in xs}) == len(xs)
    assert rep["state"] == "valid" and len(meta(tmp_path)["sessions"]) == 2


def test_a_torn_last_line_is_moved_aside_and_its_call_redone(tmp_path):
    items, cards = world(2)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, items, cards, interrupted(make_io(items, cards), 2))
    torn = '{"type": "call", "sid": "S0'
    with (tmp_path / "run" / A.CALLS).open("a", encoding="utf-8") as f:
        f.write(torn)
    rep = run(tmp_path, items, cards, make_io(items, cards))
    assert (tmp_path / "run" / A.TORN).read_text(encoding="utf-8") == torn + "\n"
    assert rep["state"] == "valid" and meta(tmp_path)["sessions"][-1]["torn_bytes"] == len(torn)


# ---------------------------------------------------------------- checks before and after a session
@pytest.mark.parametrize("env, why", [
    (["LLM_TEMPERATURE=0.2", "LLM_MAX_TOKENS=10000", f"OLLAMA_MODEL={A.MODEL}"], "options"),
    (["LLM_TEMPERATURE=0.1", "LLM_MAX_TOKENS=10000", "OLLAMA_MODEL=other"], "OLLAMA_MODEL"),
    (["LLM_TEMPERATURE=0.1", "LLM_MAX_TOKENS=10000"], "OLLAMA_MODEL"),
    (ENV + ["RAG_GEN_CARD=false"], "RAG_GEN_CARD")])
def test_a_staging_env_other_than_the_direct_calls_is_refused_before_any_call(tmp_path, env, why):
    items, cards = world(2)
    io = make_io(items, cards, inspect=lambda n: [{"Config": {"Env": env}, "State": {"Running": True}}])
    with pytest.raises(SystemExit, match=why):
        run(tmp_path, items, cards, io)
    assert calls(tmp_path) == [] and io.post.bodies == []


def test_only_the_four_env_values_are_kept():
    got = A.env_check([{"Config": {"Env": ENV + ["RAG_GEN_CARD=True"]}, "State": {"Running": True}}])
    assert set(got["env"]) == set(A.ENV_KEYS) and got["problems"] == [] and "zzz" not in json.dumps(got)


@pytest.mark.parametrize("kw, why", [({"health": lambda u: {"status": "ok", "build_id": "b_other"}}, "build_id"),
                                     ({"health": lambda u: {"status": "mismatch", "build_id": BUILD}}, "status"),
                                     ({"ollama": Ollama(digest="sha-other")}, "digest"),
                                     ({"ollama": Ollama(version="0.0.1")}, "version")])
def test_a_wrong_build_or_model_is_refused_before_any_call(tmp_path, kw, why):
    items, cards = world(2)
    io = make_io(items, cards, **kw)
    with pytest.raises(SystemExit, match=why):
        run(tmp_path, items, cards, io)
    assert io.post.bodies == []


def test_the_old_prod_build_is_never_the_new_one(tmp_path):
    items, cards = world(2)
    with pytest.raises(SystemExit, match="old prod build"):
        A.run(A.MODES["a4"], A.Writer(tmp_path / "r", dry=True), items, cards, A.OLD_BUILD, make_io(items, cards))


def test_a_digest_change_after_an_unclosed_session_voids_the_run(tmp_path):
    items, cards = world(2)
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, items, cards, interrupted(make_io(items, cards), 1))
    with pytest.raises(SystemExit, match="void"):
        run(tmp_path, items, cards, make_io(items, cards, ollama=Ollama(digest="sha-other")))
    assert meta(tmp_path)["state"] == "void"


def test_ps_readings_that_differ_void_the_run_and_a_direct_arm_truncated_twice_too(tmp_path):
    items, cards = world(2)
    rep = run(tmp_path, items, cards, make_io(items, cards, ollama=Ollama(ctx_lengths=(131072, 131072, 4096))))
    assert rep["state"] == "void" and rep["void"] == ["/api/ps readings differ in model or context_length"]
    assert rep["context_length_readings"] == [131072, 4096] and rep["sentence"] is None
    io = make_io(items, cards)
    io.chat.faults.update({("S00", "B0-prod", 1): "length", ("S01", "B0-prod", 2): "length"})
    rep = run(tmp_path, items, cards, io, name="run2")
    assert rep["void"] == ["B0-prod truncated 2 times"] and rep["truncated"] == {"B0-prod": 2, "T-rows-prod": 0}
    assert meta(tmp_path, "run2")["state"] == "void" and not rep["gates"]["propose_prod"]


# ---------------------------------------------------------------- scoring, abstentions and gates
def test_an_abstention_has_d_zero_and_t_rows_prod_reuses_b0_prod(tmp_path):
    items, cards = world(2, abstain=("S01",))
    io = make_io(items, cards)
    io.chat.values[("S01", "B0-prod")] = 1                     # wrong: B0-prod 0, ON (right) would be 1
    rep = run(tmp_path, items, cards, io)
    row = next(r for r in rep["items"] if r["sid"] == "S01")
    assert (row["fired"], row["d1"]["frac"], row["d2"]["frac"]) == (False, "0", "0")
    assert row["mean"]["ON"]["frac"] == "1"
    assert row["mean"]["T-rows-prod"] == row["mean"]["B0-prod"] == {"frac": "0", "float": 0.0}
    assert not any(x["arm"] == "T-rows-prod" and x["sid"] == "S01" for x in calls(tmp_path))
    assert rep["means"]["whole_answer_lenient"]["ON_abstained"]["frac"] == "1"


def test_delta_means_and_strata_follow_the_fixed_algorithm(tmp_path):
    items, cards = world(4, abstain=("S01",))
    io = make_io(items, cards)
    for sid in ("S00", "S02", "S03"):
        io.chat.values[(sid, "B0-prod")] = 1
    io.chat.values[("S03", "T-rows-prod")] = 1
    rep = run(tmp_path, items, cards, io)
    t1, t2 = rep["delta"]["ON-B0-prod"], rep["delta"]["ON-T-rows-prod"]
    assert (t1["delta"], t1["W"], t1["L"], t1["T"]) == (0.75, 3, 0, 1)
    assert (t2["delta"], t2["W"], t2["L"], t2["T"]) == (0.25, 1, 0, 3)
    d = [1.0, 0.0, 1.0, 1.0]
    assert t1["ci95"] == list(SC.ab_stats.bootstrap_ci(d, 10000, seed=20261018))
    assert t1["p"] == SC.ab_stats.sign_flip_p(d, seed=20261018)
    assert rep["means"]["ON"]["fired"]["frac"] == "1" and rep["means"]["B0-prod"]["all_strict"]["frac"] == "1/4"
    assert rep["means"]["OFF"]["all"]["frac"] == "1"
    # the fake backend's ON source holds context_from on its odd calls: reps 1 and 3 hit, 2 misses
    assert {r["stratum"] for r in rep["items"]} == {"some"} and rep["strata"]["some"]["n"] == 4


def test_the_quality_gate_and_the_stop_rule(tmp_path):
    items, cards = world(5, abstain=())
    io = make_io(items, cards)
    for it in items[:2]:
        io.post.values[(it["sid"], "ON")] = 1                  # ON right on 3 of 5 fired: 0.6 < 0.8
    rep = run(tmp_path, items, cards, io)
    g = rep["gates"]
    assert g["quality"]["on_mean_fired"]["frac"] == "3/5" and not g["quality"]["pass"]
    assert g["stop"]["stop"] and rep["delta"]["ON-B0-prod"]["delta"] == -0.4 and not g["propose_prod"]
    assert rep["judged"] and rep["sentence"] is not None


@pytest.mark.parametrize("wrong", ["B0-prod", "T-rows-prod"])
def test_the_stop_rule_and_the_sentence_read_on_minus_b0_prod_first(tmp_path, wrong):
    """Δ1 and Δ2 apart: the arm that is wrong on every item has Δ 1 (CI [1, 1]), the other Δ 0 (CI [0, 0])."""
    items, cards = world(4, abstain=())
    io = make_io(items, cards)
    for it in items:
        io.chat.values[(it["sid"], wrong)] = 1
    rep = run(tmp_path, items, cards, io)
    one, zero = (1.0, [1.0, 1.0], "+1.000", "[+1.000, +1.000]"), (0.0, [0.0, 0.0], "+0.000", "[+0.000, +0.000]")
    a, b = (one, zero) if wrong == "B0-prod" else (zero, one)
    got = [(rep["delta"][k]["delta"], rep["delta"][k]["ci95"]) for k in ("ON-B0-prod", "ON-T-rows-prod")]
    assert got == [a[:2], b[:2]]
    g, stop = rep["gates"], wrong != "B0-prod"
    assert rep["judged"] and g["wiring"]["pass"] and g["quality"]["pass"]
    assert (g["stop"]["stop"], g["propose_prod"]) == (stop, not stop)
    assert rep["sentence"] == SC.SENTENCE.format(d1=a[2], ci1=a[3], d2=b[2], ci2=b[3])


@pytest.mark.parametrize("fault, arm", [("card", "ON"), ("off_card", "OFF")])
def test_a_wiring_failure_stops_the_run_at_once(tmp_path, fault, arm):
    items, cards = world(2)
    io = make_io(items, cards)
    io.post.faults[("S00", arm, 1)] = fault
    rep = run(tmp_path, items, cards, io)
    assert rep["state"] == "void" and rep["void"][0].startswith("wiring:") and calls(tmp_path)[-1]["arm"] == arm


def test_an_abstained_on_with_a_card_fails_parity_and_a_regnal_card_never_passes():
    _items, cards = world(2, abstain=("S01",))
    gen = {"kind": "gen", "text": "CARD-S00-g", "layer_sha256": SC.GEN_LAYER_SHA256}
    assert SC.card_ok(gen, cards["S00"]) and SC.card_ok(None, cards["S01"])
    assert not SC.card_ok(gen, cards["S01"]) and not SC.card_ok({**gen, "kind": "regnal"}, cards["S00"])
    assert not SC.card_ok({**gen, "layer_sha256": "0" * 64}, cards["S00"]) and not SC.card_ok(None, cards["S00"])


def test_retrieval_hits_compare_whole_strings_only():
    src = {"id": "ck:a", "passage_id": "ps:gen.5.10", "split_passage_ids": ["ps:gen.5.12"]}
    assert not SC.hit({"sources": [src]}, "ps:gen.5.1")
    assert SC.hit({"sources": [src]}, "ps:gen.5.12") and SC.hit({"sources": [{"id": "ps:gen.5.1"}]}, "ps:gen.5.1")


def test_the_whole_answer_lenient_score_reads_every_line():
    it = item("S00", 105)
    assert SC.whole_answer_score(it, "abc 105歲\nmore") == 1 and SC.whole_answer_score(it, "abc 106歲") == 0
    assert SC.whole_answer_score(it, "") == 0


def test_the_sentence_is_the_plans_with_the_numbers_filled_in():
    assert SC.SENTENCE.format(d1="…", ci1="…", d2="…", ci2="…") in PLAN_DOC.read_text(encoding="utf-8")
    t = {"delta": 0.5, "ci95": [0.25, -0.125]}
    s = SC.sentence(t, {"delta": -0.03125, "ci95": [-0.1, 0.0]})
    assert "Δ̄＝+0.500（棄權記 0），95% CI [+0.250, -0.125]；" in s and "Δ̄＝-0.031，95% CI [-0.100, +0.000]；" in s


# ---------------------------------------------------------------- prod check, the writer, what is printed
def test_prod_check_runs_on_once_without_the_flag_and_checks_card_parity(tmp_path):
    items, cards = world(3, abstain=("S02",))
    io = make_io(items, cards, ollama=lambda p: pytest.fail("prod-check reads no Ollama"),
                 inspect=lambda n: pytest.fail("prod-check inspects no container"))
    rep = run(tmp_path, items, cards, io, mode="prod-check")
    assert [b.get("use_gen_card") for b in io.post.bodies] == [None] * 3 and io.chat.calls == []
    assert (rep["card_parity"], rep["gen_cards"], rep["n_fired"], rep["pass"]) == (3, 2, 2, True)


def test_the_writer_refuses_every_other_path(tmp_path):
    assert A.Writer(A.OUT_ROOT / "a4").root == (A.OUT_ROOT / "a4").resolve()
    for bad in (A.STORE / "reports/other/a4", A.OUT_ROOT, A.OUT_ROOT / "a4/sub", A.OUT_ROOT / "../x"):
        with pytest.raises(SystemExit):
            A.Writer(bad)
    for bad in (A.STORE / "tmp/x", A.REPO / "tmp_x", A.OUT_ROOT / "a4"):
        with pytest.raises(SystemExit):
            A.Writer(bad, dry=True)
    w = A.Writer(tmp_path / "ok", dry=True)
    for name in ("sub/x.json", "../x.json", "/tmp/x.json"):
        with pytest.raises(SystemExit):
            w.path(name)
    assert not (tmp_path / "ok").exists()


def test_a_record_holding_a_unicode_line_break_reads_back_as_one_record(tmp_path):
    w = A.Writer(tmp_path / "w", dry=True)
    recs = [{"answer": "a\u2028b\u2029c\x85d\x0be"}, {"answer": "f"}]
    for r in recs:
        w.append(A.CALLS, r)
    assert w.jsonl(A.CALLS) == recs and A.repair_tail(w) == 0


def test_nothing_printed_or_reported_holds_a_question_card_or_answer(tmp_path, capsys):
    items, cards = world(3)
    io = make_io(items, cards)
    rep = run(tmp_path, items, cards, io)
    print(json.dumps(A.summary(rep), ensure_ascii=False))
    shown = capsys.readouterr().out + "\n".join(map(str, io.logs))
    root = tmp_path / "run"
    assert sorted(p.name for p in root.iterdir()) == [A.CALLS, A.REPORT, A.LOCK, A.RUN_META]
    kept = (root / A.REPORT).read_text(encoding="utf-8") + (root / A.RUN_META).read_text(encoding="utf-8")
    for s in ["QQ-", "CARD-", "step", "ctx-"]:
        assert s not in shown and s not in kept, s
    assert "QQ-" not in (root / A.CALLS).read_text(encoding="utf-8")       # the question is never stored either


# ---------------------------------------------------------------- the post-switch GT check
def gt_items(n: int = 3) -> list[dict]:
    return [{"question_id": f"GT{i}", "question": f"QQ-GT{i}-synthetic-question", "question_type": "t"} for i in range(n)]


def gt_file(tmp_path, qs: list[dict]) -> Path:
    p = tmp_path / "gt.json"
    p.write_text(json.dumps({"questions": qs}), encoding="utf-8")
    return p


def gt_io(post, **kw) -> A.Io:
    return make_io([], {}, post=post, chat=lambda *a: pytest.fail("the GT check calls no Ollama"),
                   ollama=lambda p: pytest.fail("the GT check reads no Ollama"),
                   inspect=lambda n: pytest.fail("the GT check inspects no container"), **kw)


def test_the_gt_questions_are_smoke20s(monkeypatch):
    monkeypatch.syspath_prepend(str(A.REPO / "packages"))          # smoke20 imports ragcommon
    spec = importlib.util.spec_from_file_location("smoke20_r1", A.REPO / "evaluation/experiments/2026-10-08_r1/smoke20.py")
    sm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sm)
    want, got = [q["question_id"] for q in sm.pick(A.GT_V2)], [q["question_id"] for q in A.gt_questions()]
    assert got == want and len(got) == 20


def test_the_gt_check_sends_smoke20s_full_request_to_prod_and_passes_without_a_card(tmp_path):
    qs, bodies = gt_items(), []

    def post(url, body, timeout):
        bodies.append((url, body))
        return {"answer": "x", "sources": [{"id": "ck:a", "build_id": BUILD}], "aux_card": None}, None, 1.0
    rep = A.gt_check(A.Writer(tmp_path / "gt", dry=True), BUILD, gt_io(post), gt_file(tmp_path, qs))
    assert bodies == [(A.MODES["prod-check"].url, {"question": q["question"], "top_k": 5}) for q in qs]
    assert (rep["n"], rep["errors"], rep["aux_cards"], rep["pass"]) == (3, [], {}, True)
    assert "QQ-" not in (tmp_path / "gt" / A.REPORT).read_text(encoding="utf-8")


@pytest.mark.parametrize("fault, errors, cards", [("card", [], {"GT1": "regnal"}), ("http", ["GT1"], {})],
                         ids=["card", "http"])
def test_a_gt_question_with_a_card_or_without_an_answer_fails_the_gt_check_which_is_never_redone(tmp_path, fault,
                                                                                                  errors, cards):
    qs = gt_items()

    def post(url, body, timeout):
        hit = body["question"] == qs[1]["question"]
        if hit and fault == "http":
            return None, "HTTPError 500", 1.0
        return {"answer": "x", "sources": [], "aux_card": {"kind": "regnal", "text": "x"} if hit else None}, None, 1.0
    rep = A.gt_check(A.Writer(tmp_path / "gt", dry=True), BUILD, gt_io(post), gt_file(tmp_path, qs))
    assert (rep["errors"], rep["aux_cards"], rep["pass"]) == (errors, cards, False)
    with pytest.raises(SystemExit, match="new --run"):
        A.gt_check(A.Writer(tmp_path / "gt", dry=True), BUILD, gt_io(post), gt_file(tmp_path, qs))


@pytest.mark.parametrize("build, health", [(A.OLD_BUILD, healthy), (BUILD, lambda u: {"status": "ok", "build_id": "b_x"})])
def test_the_gt_check_refuses_the_old_build_or_another_served_one_before_any_call(tmp_path, build, health):
    with pytest.raises(SystemExit):
        A.gt_check(A.Writer(tmp_path / "gt", dry=True), build, gt_io(lambda *a: pytest.fail("no call"), health=health),
                   gt_file(tmp_path, gt_items()))


# ---------------------------------------------------------------- the store inputs (counts only)
@needs_store
def test_the_pinned_inputs_load_as_58_items_48_fired():
    items, cards = A.load_inputs()
    n_units = len(A.plan(items, cards, A.MODES["a4"]))        # bound first: a failing assert prints no item
    assert (len(items), sum(SC.fired(cards, it["sid"]) for it in items)) == (58, 48)
    assert [it["sid"] for it in items] == sorted(cards) and n_units == 174
    assert sum(len(a) for _r, _i, a in A.plan(items, cards, A.MODES["a4"])) == 3 * (58 * 3 + 48)


@needs_store
def test_a_dry_run_on_the_store_inputs_writes_only_its_directory(tmp_path):
    rep = A.dry_run(tmp_path / "dry")
    assert (rep["state"], rep["n_attempts"], rep["gates"]["wiring"]["on_card_parity"]) == ("valid", 666, 58)
    assert rep["gates"]["quality"]["on_mean_fired"]["frac"] == "1" and rep["delta"]["ON-B0-prod"]["W"] == 48
    assert sorted(p.name for p in (tmp_path / "dry").iterdir()) == [A.CALLS, A.REPORT, A.LOCK, A.RUN_META]
    assert Fraction(rep["means"]["B0-prod"]["all_strict"]["frac"]) == 0

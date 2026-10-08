"""G-HELDOUT (experiments/2026-10-09_r2/prereg.md): src/heldout.py and heldout_gate.py.

Synthetic registries, held-out files and backend answers; the collector talks to
an httpx.MockTransport, never the network. R1 reports legacy ids, R2 ev ids;
both reach R2's surviving ev id (legacy id → R1 ev id → merged_into).
"""

import copy
import hashlib
import json

import httpx
import pytest

import heldout_gate
from src import heldout

R1_BUILD, R2_BUILD = "b20261008_6daa4f31", "b20261009_0000abcd"
CORE = ("ps:x.1.1", "ps:x.2.1", "ps:x.3.1", "ps:x.4.1", "ps:x.5.1")
# (ev id, legacy id, anchors, R1 triggers)
EVENTS = [("ev0001", "event:babieta", ("ps:gen.11.1",), ("巴別塔",)),
          ("ev0002", "event:guizhu", ("ps:act.9.1", "ps:act.9.19b"), ("保羅歸主",)),
          ("ev0003", "event:guizhu2", ("ps:act.9.1", "ps:act.9.19b"), ("保羅歸主",)),
          ("ev0014", "event:zhuanbian", ("ps:act.9.1",), ("保羅歸主",)),
          ("ev0020", "event:shounan", ("ps:mat.26.17", "ps:mat.27.32"), ("受難週",)),
          ("ev0027", "event:dingshizijia", ("ps:mat.27.32",), ("釘十字架",)),
          ("ev0031", "event:yuyue", ("ps:exo.12.1",), ("逾越節",))]
RETIRED = {"ev0003": "ev0002", "ev0014": "ev0002"}


def _anchors(passages):
    return [{"passage_id": p} for p in passages]


def r1_registry():
    return {"schema": "ragdata.event_registry.v2", "variant": "R1", "events": [
        {"event_id": ev, "legacy_id": legacy, "anchors": _anchors(anchors),
         "legacy_triggers": [{"text": t} for t in triggers], "pdf_terms": [],
         "external_aliases": []} for ev, legacy, anchors, triggers in EVENTS]}


def r2_registry():
    events = []
    for ev, legacy, anchors, triggers in EVENTS:
        if ev in RETIRED:
            continue
        legacy_ids = [legacy] + [lg for e, lg, _, _ in EVENTS if RETIRED.get(e) == ev]
        events.append({"event_id": ev, "legacy_ids": legacy_ids, "anchors": _anchors(anchors),
                       "pdf_terms": [{"text": triggers[0]}], "external_aliases": []})
    return {"schema": "ragdata.event_registry.v2", "variant": "R2", "events": events,
            "retired": [{"event_id": e, "merged_into": m} for e, m in RETIRED.items()]}


LEXICON_R1 = {"schema": "ragdata.routing_lexicon.v1", "books": [
    {"name": "創世記", "full_name": "創世記", "book_id": "gen"},
    {"name": "受難週記", "full_name": "受難週記", "book_id": "zzz"}]}
LEXICON_R2 = {"schema": "ragdata.routing_lexicon.v2", "books": [
    {"surface": "創世記", "full_name": "創世記", "book_id": "gen"},
    {"surface": "受難週記", "full_name": "受難週記", "book_id": "zzz"},
    {"surface": "難週", "full_name": "受難週記", "book_id": "zzz"}]}     # a made-up abbreviation

# id, kind, gold, question
ITEMS = [("p1", "positive", "ev0001", "巴別塔為什麼蓋不成？"),
         ("p2", "positive", "ev0014", "保羅歸主的時候看見什麼？"),
         ("p3", "positive", "ev0027", "釘十字架時誰在旁邊？"),
         ("p4", "positive", "ev0031", "第一個逾越節怎麼過？"),
         ("p5", "positive", "ev0001", "人們為什麼要造一座通天的塔？"),
         ("n1", "negative", None, "耶穌和門徒同度逾越節時說了什麼？"),
         ("n2", "negative", None, "掃羅王怎麼死的？")]


@pytest.fixture
def heldout_file(tmp_path):
    doc = {"schema": heldout.HELDOUT_SCHEMA, "items": [
        {"id": i, "kind": k, "event_id": e, "question": q, "tuned_on": False, "gold": []}
        for i, k, e, q in ITEMS]}
    path = tmp_path / "heldout.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def data(heldout_file):
    return heldout.load_heldout(*heldout_file)


def body(route="R4", events=(), appended=(), core=CORE, errors=None, lane_on=True):
    sources = ([{"id": p, "passage_id": p, "strategy": "hybrid_hybrid"} for p in core]
               + [{"id": p, "passage_id": p, "strategy": "event_registry"} for p in appended])
    return {"retrieval_stats": {"route_used": route, "event_registry_events": list(events),
                                "use_graph": True, "strategy_errors": errors or {},
                                "graph_strategies": ["event_registry"] if lane_on else []},
            "intent": {"type": "event", "entities": []}, "sources": sources}


def run(arm, answers, sha, build=None):
    """A collect output: ``answers`` maps item id -> body() (default: lane silent)."""
    rows = [heldout.response_row(i, 200, answers.get(i, body("fallback"))) for i, *_ in ITEMS]
    return {"schema": heldout.RUN_SCHEMA, "rows": rows,
            "meta": {"arm": arm, "data_build_id": build or (R1_BUILD if arm == "R1" else R2_BUILD),
                     "heldout_sha256": sha}}


# R1 (legacy ids): p1 right; p2 fires the three twins, ev0014 (fewest anchors) appends act.9.1;
# p3 fires 逾越節 (wrong event); p4 silent; n1 fires 逾越節 (error).
R1_ANSWERS = {
    "p1": body(events=["event:babieta"], appended=["ps:gen.11.1"]),
    "p2": body(events=["event:zhuanbian", "event:guizhu", "event:guizhu2"],
               appended=["ps:act.9.1"]),
    "p3": body(events=["event:yuyue"], appended=["ps:exo.12.1"]),
    "n1": body(events=["event:yuyue"], appended=["ps:exo.12.1"]),
}
# R2 (ev ids): p1, p2 right; p3 fires the parent ev0020 (accepted); p4 right; n1 silent.
R2_ANSWERS = {
    "p1": body(events=["ev0001"], appended=["ps:gen.11.1"]),
    "p2": body(events=["ev0002"], appended=["ps:act.9.1"]),
    "p3": body(events=["ev0020"], appended=["ps:mat.26.17"]),
    "p4": body(events=["ev0031"], appended=["ps:exo.12.1"]),
}


def contracts():
    return {"R1": (r1_registry(), LEXICON_R1), "R2": (r2_registry(), LEXICON_R2)}


def regs():
    return {arm: heldout.registry_from_contract(*c) for arm, c in contracts().items()}


def ids():
    return heldout.id_map(r1_registry(), r2_registry())


def gate(data, r1=None, r2=None, sha=None):
    sha = sha or data.sha256
    runs = {"R1": r1 or run("R1", R1_ANSWERS, sha), "R2": r2 or run("R2", R2_ANSWERS, sha)}
    return heldout.heldout_gate(runs, contracts(), data)


@pytest.fixture
def few_triggers(monkeypatch):
    monkeypatch.setattr(heldout, "MIN_TRIGGERS", 4)


# ---------------------------------------------------------------- questions and rows

def test_the_real_heldout_file_is_the_pinned_one():
    data = heldout.load_heldout()
    assert len(data.items) == 61 and sum(i.kind == "positive" for i in data.items) == 43


def test_any_other_heldout_bytes_are_refused(heldout_file):
    path, sha = heldout_file
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(heldout.HeldoutError, match="not the pinned held-out"):
        heldout.load_heldout(path, sha)


def test_response_rows_flag_http_and_infrastructure_failures():
    assert heldout.response_row("q", 503, "down")["invalid"] == "http"
    assert heldout.response_row("q", None, None, "ConnectError")["invalid"] == "http"
    lane_failed = body(events=["ev0001"], errors={"event_registry": "anchor missing"})
    assert heldout.response_row("q", 200, lane_failed)["invalid"] == "infra"
    row = heldout.response_row("q", 200, body(events=["ev0001"], appended=["ps:gen.11.1"]))
    assert row["invalid"] is None and row["event_registry_events"] == ["ev0001"]
    assert row["sources"][-1] == {"id": "ps:gen.11.1", "passage_id": "ps:gen.11.1",
                                  "strategy": "event_registry"}


# ---------------------------------------------------------------- ids

def test_legacy_ids_and_merged_twins_reach_the_surviving_event():
    m, reg = ids(), regs()["R1"]
    assert [m.canonical(reg.to_ev[r]) for r in ("event:zhuanbian", "event:guizhu2")] \
        == ["ev0002", "ev0002"]
    assert m.accepts("ev0014", "ev0002") and m.accepts("ev0003", "ev0014")


def test_the_parent_is_accepted_for_its_children_only():
    m = ids()
    assert m.accepts("ev0027", "ev0020")
    assert not m.accepts("ev0020", "ev0027") and not m.accepts("ev0031", "ev0020")


def test_r2_legacy_ids_must_agree_with_r1_ids_and_merged_into():
    r2 = r2_registry()
    r2["events"][0]["legacy_ids"].append("event:zhuanbian")      # ev0001 claims ev0014's id
    r2["events"][1]["legacy_ids"].remove("event:zhuanbian")
    with pytest.raises(heldout.HeldoutError, match="event:zhuanbian"):
        heldout.id_map(r1_registry(), r2)


# ---------------------------------------------------------------- the scored event

def test_the_scored_event_is_the_one_whose_anchor_was_appended():
    reg = regs()["R1"]
    row = heldout.response_row("p2", 200, R1_ANSWERS["p2"])
    assert heldout.scored_events(row, reg) == ["event:zhuanbian"]
    # act.9.1 already in the top-k: ev0014 has nothing left, ev0002 appends act.9.19b
    covered = body(events=["event:zhuanbian", "event:guizhu"], appended=["ps:act.9.19b"],
                   core=CORE[:4] + ("ps:act.9.1",))
    assert heldout.scored_events(heldout.response_row("p2", 200, covered), reg) \
        == ["event:guizhu"]


def test_nothing_appended_scores_the_first_triggered_event():
    covered = body(events=["event:dingshizijia", "event:shounan"],
                   core=CORE[:3] + ("ps:mat.27.32", "ps:mat.26.17"))
    row = heldout.response_row("p3", 200, covered)
    assert heldout.scored_events(row, regs()["R1"]) == ["event:dingshizijia"]


def test_an_appended_passage_the_lane_would_not_pick_is_refused():
    wrong = body(events=["event:babieta"], appended=["ps:act.9.1"])
    with pytest.raises(heldout.HeldoutError, match="the lane picks"):
        heldout.scored_events(heldout.response_row("p1", 200, wrong), regs()["R1"])
    unknown = body(events=["ev0001"], appended=["ps:gen.11.1"])     # an R2 id on R1
    with pytest.raises(heldout.HeldoutError, match="not in the arm's R1 registry"):
        heldout.scored_events(heldout.response_row("p1", 200, unknown), regs()["R1"])


def test_string_hits_mask_the_books_full_names_not_their_abbreviations():
    reg = regs()["R2"]
    assert heldout.string_hits("受難週的第一天", reg) == ["ev0020"]     # 難週 is no mask
    assert heldout.string_hits("受難週記第一章", reg) == []


# ---------------------------------------------------------------- the gate

def test_precision_recall_and_misses_per_arm(data, few_triggers):
    report = gate(data)
    r1, r2 = report["arms"]["R1"], report["arms"]["R2"]
    assert (r1["n_triggered"], r1["n_correct"], r1["errors"]) == (4, 2, ["p3", "n1"])
    assert r1["misses"] == {"trigger": ["p5"], "route": ["p4"], "wrong_event": ["p3"]}
    assert (r2["n_triggered"], r2["n_correct"], r2["precision"]) == (4, 4, 1.0)
    assert r2["recall"] == {"n_positive": 5, "n_correct": 4, "value": 0.8}
    assert r2["string_hit_recall"]["n_hit"] == 4      # p5 names no trigger


def test_pass_needs_enough_triggers_precision_and_no_net_loss(data, few_triggers):
    report = gate(data)
    ni = report["criteria"]["noninferiority"]
    assert (ni["r2_lose_r1_win"], sorted(ni["r2_win_r1_lose"])) == ([], ["n1", "p3", "p4"])
    assert report["verdict"] == "PASS" and report["passed"] is True


def test_too_few_triggers_is_a_signoff_not_a_verdict(data):
    report = gate(data)
    assert report["verdict"] == "SIGNOFF" and report["passed"] is None
    assert "Kay signs off" in report["fail_reasons"][0]


def test_triggered_negatives_and_wrong_events_fail_precision(data, few_triggers):
    answers = {**R2_ANSWERS, "n1": body(events=["ev0031"], appended=["ps:exo.12.1"]),
               "p4": body(events=["ev0001"], appended=["ps:gen.11.1"])}
    report = gate(data, r2=run("R2", answers, data.sha256))
    assert report["arms"]["R2"]["errors"] == ["p4", "n1"]
    assert report["criteria"]["precision"]["value"] == 3 / 5
    assert report["verdict"] == "FAIL"


def test_losing_three_more_questions_than_winning_fails(data, monkeypatch):
    monkeypatch.setattr(heldout, "MIN_TRIGGERS", 2)
    picks = {"p1": ("event:babieta", "ps:gen.11.1"), "p2": ("event:zhuanbian", "ps:act.9.1"),
             "p3": ("event:dingshizijia", "ps:mat.27.32"), "p4": ("event:yuyue", "ps:exo.12.1"),
             "p5": ("event:babieta", "ps:gen.11.1")}
    r1 = run("R1", {q: body(events=[e], appended=[a]) for q, (e, a) in picks.items()},
             data.sha256)
    r2 = run("R2", {"p3": body(events=["ev0027"], appended=["ps:mat.27.32"]),
                    "p4": R2_ANSWERS["p4"]}, data.sha256)
    report = gate(data, r1=r1, r2=r2)
    ni = report["criteria"]["noninferiority"]
    assert (ni["r2_lose_r1_win"], ni["r2_win_r1_lose"], ni["net_loss"]) \
        == (["p1", "p2", "p5"], [], 3)
    assert report["criteria"]["precision"]["value"] == 1.0
    assert report["verdict"] == "FAIL" and report["fail_reasons"] == ["net loss 3 > 2"]


@pytest.mark.parametrize("breaks, match", [
    (lambda runs: runs["R2"]["rows"][0].update(invalid="http"), "invalid rows"),
    (lambda runs: runs["R2"]["rows"].pop(), "exactly the 7 held-out ids"),
    (lambda runs: runs["R1"]["rows"][0].update(graph_strategies=[]), "lane was off"),
    (lambda runs: runs["R2"]["meta"].update(data_build_id=R1_BUILD), "both arms ran"),
    (lambda runs: runs["R2"]["meta"].update(heldout_sha256="0" * 64), "another held-out"),
    (lambda runs: runs["R1"]["meta"].update(arm="R2"), "the run is arm 'R2'"),
])
def test_runs_the_protocol_does_not_allow_are_refused(data, breaks, match):
    runs = {"R1": run("R1", R1_ANSWERS, data.sha256), "R2": run("R2", R2_ANSWERS, data.sha256)}
    breaks(runs)
    with pytest.raises(heldout.HeldoutError, match=match):
        heldout.heldout_gate(runs, contracts(), data)


def test_a_registry_of_the_wrong_variant_is_refused(data):
    swapped = {"R1": contracts()["R2"], "R2": contracts()["R2"]}
    runs = {"R1": run("R1", {}, data.sha256), "R2": run("R2", {}, data.sha256)}
    with pytest.raises(heldout.HeldoutError, match="R1: registry variant R2"):
        heldout.heldout_gate(runs, swapped, data)


# ---------------------------------------------------------------- CLI

def transport(build, answers, health_status=200):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(health_status, json={"build_id": build, "encoder": None})
        question = json.loads(request.content)["question"]
        qid = next(i for i, _, _, q in ITEMS if q == question)
        assert json.loads(request.content)["retrieval_only"] is True
        if answers.get(qid) == "boom":
            return httpx.Response(500, text="internal error")
        return httpx.Response(200, json=answers.get(qid, body("fallback")))
    return httpx.MockTransport(handle)


def collect(tmp_path, heldout_file, monkeypatch, arm, build, answers, *extra):
    path, sha = heldout_file
    monkeypatch.setattr(heldout, "HELDOUT_SHA256", sha)
    out = tmp_path / f"run_{arm}.json"
    code = heldout_gate.main(["collect", "--arm", arm, "--build", build, "--heldout", str(path),
                              "--out", str(out), *extra], transport=transport(R1_BUILD, answers))
    return code, out


def test_collect_records_every_answer_and_the_build(tmp_path, heldout_file, monkeypatch):
    code, out = collect(tmp_path, heldout_file, monkeypatch, "R1", R1_BUILD, R1_ANSWERS)
    saved = json.loads(out.read_text())
    assert code == 0 and [r["id"] for r in saved["rows"]] == [i for i, *_ in ITEMS]
    assert saved["meta"]["data_build_id"] == R1_BUILD and saved["meta"]["arm"] == "R1"
    assert saved["rows"][0]["event_registry_events"] == ["event:babieta"]


def test_collect_refuses_a_backend_serving_another_build(tmp_path, heldout_file, monkeypatch,
                                                         capsys):
    code, out = collect(tmp_path, heldout_file, monkeypatch, "R2", R2_BUILD, {})
    assert code == 2 and not out.exists() and "not --build" in capsys.readouterr().err


def test_collect_exits_1_on_failed_answers(tmp_path, heldout_file, monkeypatch):
    code, out = collect(tmp_path, heldout_file, monkeypatch, "R1", R1_BUILD, {"p1": "boom"})
    rows = json.loads(out.read_text())["rows"]
    assert code == 1 and rows[0]["invalid"] == "http"
    assert collect(tmp_path, heldout_file, monkeypatch, "R1", R1_BUILD, {})[0] == 2   # exists
    assert collect(tmp_path, heldout_file, monkeypatch, "R1", R1_BUILD, {},
                   "--overwrite")[0] == 0


def _contracts(root, build, registry, lexicon):
    directory = root / build
    directory.mkdir(parents=True)
    for name, doc in (("manifest.json", {"build_id": build}), ("event_registry.json", registry),
                      ("routing_lexicon.json", lexicon)):
        (directory / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_score_cli_judges_two_runs_against_their_contracts(tmp_path, heldout_file, monkeypatch,
                                                          few_triggers, capsys):
    path, sha = heldout_file
    monkeypatch.setattr(heldout, "HELDOUT_SHA256", sha)
    root = tmp_path / "contracts"
    _contracts(root, R1_BUILD, r1_registry(), LEXICON_R1)
    _contracts(root, R2_BUILD, r2_registry(), LEXICON_R2)
    files = {}
    for arm, answers in (("R1", R1_ANSWERS), ("R2", R2_ANSWERS)):
        files[arm] = tmp_path / f"{arm}.json"
        files[arm].write_text(json.dumps(run(arm, answers, sha), ensure_ascii=False))
    out = tmp_path / "gate.json"
    argv = ["score", "--r1", str(files["R1"]), "--r2", str(files["R2"]), "--heldout", str(path),
            "--contracts-root", str(root), "--out", str(out)]
    assert heldout_gate.main(argv) == 0
    assert json.loads(out.read_text())["verdict"] == "PASS"
    assert "G-HELDOUT: PASS" in capsys.readouterr().out
    bad = copy.deepcopy(run("R2", R2_ANSWERS, sha))
    bad["meta"]["data_build_id"] = "b20261009_ffffffff"                # no contracts for it
    files["R2"].write_text(json.dumps(bad))
    assert heldout_gate.main([*argv, "--overwrite"]) == 2

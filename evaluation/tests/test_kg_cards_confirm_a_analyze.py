"""Experiment A confirmation set: analyze_c (confirm_A.md §9 test 8), the frozen wording, collect_ctx (test 9).

Synthetic unit values and mocked HTTP only: nothing launches an agent, calls Ollama or the backend.
These tests need no store.
"""

import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_kg_cards" / "A" / "confirm"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import analyze_c as A  # noqa: E402
import c_common as C  # noqa: E402
import collect_ctx as CX  # noqa: E402
from dry_run_c import synth_response  # noqa: E402

CONFIRM_MD = _DIR.parents[1] / "confirm_A.md"


# ---------------------------------------------------------------- test 8: analysis
def rows_of(units: dict) -> dict:
    """{unit: [d_q, ...]} -> score rows with G-auto = 0.5 + d/2 and the comparison arms at 0.5 − d/2."""
    out = {}
    for u, ds in units.items():
        for j, d in enumerate(ds):
            m = {a: 0.5 for a in C.ARMS}
            m.update({"G-auto": 0.5 + d / 2, "T-canon": 0.5 - d / 2, "T-rows": 0.5 - d / 2})
            out[f"{u}_{j}"] = {"unit": u, "mean": m, "reps": {}}
    return out


def test_8_exact_p_matches_hand_count():
    t = A.unit_test({"u1": 0.5, "u2": 0.0, "u3": -0.25, "u4": 0.25})
    # non-zero (0.5, −0.25, 0.25): |Σ| ≥ 0.5 for 6 of the 8 sign patterns
    assert t["p"] == 6 / 8 and t["exact"] and t["n_nonzero"] == 3
    assert t["delta"] == pytest.approx(0.125)                                 # the zero unit counts in Δ̄
    assert (t["W"], t["L"], t["T"]) == (2, 1, 1)
    all_pos = A.unit_test({f"u{i}": 0.5 for i in range(14)})
    assert all_pos["p"] == 2 / 2 ** 14 and all_pos["exact"]


def test_8_unit_values_unweighted_and_zero_units_kept():
    rows = rows_of({"I1": [1.0, 0.0, 0.0], "I2": [0.0, 0.0], "J1": [0.5]})
    v = A.unit_values(rows, "G-auto", "T-canon")
    assert v == {"I1": pytest.approx(1 / 3), "I2": 0.0, "J1": pytest.approx(0.5)}
    assert A.unit_test(v)["delta"] == pytest.approx((1 / 3 + 0 + 0.5) / 3)


def test_8_h2_p_not_reported_when_h1_fails():
    rows = rows_of({f"U{i}": [0.05] for i in range(14)})                      # significant but small
    seq = A.fixed_sequence(rows)
    assert seq["H1"]["significant"] and seq["H1"]["sig_small"] and not seq["H1"]["pass"]
    assert seq["H2"]["tested"] is False and "p" not in seq["H2"] and "exact" not in seq["H2"]
    v = A.verdict(seq, {}, [], {"flag": False})
    assert v["result"] == "H1 未過" and v["wording"].startswith("王朝年表推導卡在盲集上未達事先登記的門檻（單位 n＝14")
    assert v["notes"] == [f"G-auto−T-canon：{C.WORDING['h1_sig_small']}"]


def h2_entries(doc, path=()):
    """Every dict under a G-auto−T-rows key, with its path."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "G-auto−T-rows" and isinstance(v, dict):
                yield path + (k,), v
            yield from h2_entries(v, path + (k,))


@pytest.mark.parametrize("h2_tested", [False, True])
def test_8_h2_p_absent_from_descriptives_unless_tested(h2_tested):
    from descriptives_c import strata, trap_sensitivity
    from report_c import desc_lines
    rows = rows_of({f"U{i}": [0.05, -0.02] for i in range(14)})
    for r in rows.values():
        r["sens"] = {"template": {"mean": r["mean"], "trap_calls": 0}}
    assert A.fixed_sequence(rows)["H2"]["tested"] is False
    ds = {"pairs_desc": {}, "strata": strata(rows, h2_tested), "trap_rule_sensitivity": trap_sensitivity(rows, h2_tested)}
    rep = {"descriptive": ds, "item_level": A.item_level(rows, h2_tested)}
    found = list(h2_entries(rep))
    # non-empty strata (non_pilot, not_gen_passage, not_answer_is_father, excl_ref_disagree) + the template
    # rule + item level
    assert len(found) == 4 + 1 + 1 and all(("p" in t or "p_signflip" in t) is h2_tested for _p, t in found)
    assert "p" in ds["strata"]["excl_ref_disagree"]["G-auto−T-canon"]           # H1 p stays as description
    h2_md = [x for x in desc_lines(rep) if "G-auto−T-rows" in x]
    assert h2_md and all(("未檢定" in x) is (not h2_tested) for x in h2_md)


def test_8_verdict_wordings():
    neg = A.fixed_sequence(rows_of({f"U{i}": [-0.5] for i in range(14)}))
    v = A.verdict(neg, {}, [], {"flag": True})
    assert v["result"] == "H1 顯著為負" and v["wording"].endswith("，且 G-auto 顯著劣於正典經文窗")
    assert v["k3_wording"] == "不談 prod"
    both = A.verdict(A.fixed_sequence(rows_of({f"U{i}": [0.5] for i in range(14)})), {}, [], {"flag": False})
    assert both["result"] == "H1、H2 皆過"
    assert both["wording"] == f"{C.WORDING['h1_h2']}；{C.WORDING['h1_h2_scope']}"
    rows = rows_of({f"U{i}": [0.5] for i in range(14)})
    for r in rows.values():
        r["mean"]["T-rows"] = r["mean"]["G-auto"]                              # H2 Δ̄ = 0
    only = A.verdict(A.fixed_sequence(rows), {}, [], {"flag": False})
    assert only["result"] == "H1 過、H2 未過" and only["wording"] == C.WORDING["h1_only"]
    assert A.verdict(neg, {"k0": ["x"]}, [], {"flag": False})["result"] == A.VOID


def test_8_min_delta_boundary_and_pre_stops():
    t = {"p": 0.001, "delta": 0.1 - 1e-12}
    assert A.step(t)["pass"]                                                   # float tolerance at +0.10
    assert not A.step({"p": 0.05, "delta": 0.5})["pass"]                       # p must be < 0.05
    stops = A.pre_stops(11, {"stop": True, "wording": "K1 句"}, {"K0_1b": {"pass": False, "wrong": 2, "n": 20}})
    assert [s["rule"] for s in stops] == ["K1", "K0-1b", "K-U2"]
    assert stops[1]["wording"] == "依事先規則停止（K0-1b＝2/20），不構成無效證據；盲集未跑"
    assert stops[2]["wording"] == "依事先規則停止（K-U2＝凍結單位 n＝11<12），不構成無效證據；盲集未跑"
    v = A.verdict(A.fixed_sequence(rows_of({"U": [1.0]})), {}, stops, {"flag": False})
    assert v["result"] == "stop" and v["wording"] == "K1 句" and A.pre_stops(14, None, None) == []


def test_8_k3_counts_substitutes_and_format_failures():
    rec = lambda s, ff=False: {"score": s, "format_fail": ff}  # noqa: E731
    rows = {"a": {"unit": "U1", "mean": {}, "reps": {
        "G-auto|1": dict(rec(0.0), substituted_from="T-rows"), "G-auto|2": rec(1.0), "G-auto|3": rec(0.0, True),
        "T-canon|1": rec(1.0), "T-canon|2": rec(1.0), "T-canon|3": rec(1.0)}}}
    k = A.k3(rows)
    assert k["rate"]["G-auto"] == pytest.approx(1 / 3) and k["rate"]["T-canon"] == 0.0
    assert k["flag"] and k["diff"] == pytest.approx(1 / 3)


def test_wording_matches_confirm_md_table():
    """Every literal fragment of every frozen phrase occurs in confirm_A.md (they cannot drift)."""
    md = CONFIRM_MD.read_text(encoding="utf-8")
    for key, phrase in C.WORDING.items():
        for frag in re.split(r"\{[a-z_]+\}", phrase):
            assert frag in md, (key, frag)


# ---------------------------------------------------------------- test 9: collect_ctx (mock HTTP)
QS = [{"id": f"Q{i}", "question": f"合成題{i}"} for i in range(3)]


def mock_post(script):
    """script: list of callables or dicts, consumed one per call."""
    calls = []

    def post(_url, body, timeout):
        calls.append((body, timeout))
        step = script.pop(0) if len(script) > 1 else script[0]
        return step(body) if callable(step) else json.loads(json.dumps(step))
    post.calls = calls
    return post


def good(i=0, qid="Q"):
    return synth_response(i, qid)


def run_collect(tmp_path, post, qs=QS):
    return CX.collect(qs, "sha", out=tmp_path / "contexts.json", failed=tmp_path / "failed.json", post=post,
                      ps=lambda: {"models": []}, log=lambda *_: None, sleep=lambda _s: None)


def test_9_all_pass_writes_contexts(tmp_path):
    post = mock_post([good(0)])
    doc = run_collect(tmp_path, post)
    assert (tmp_path / "contexts.json").is_file() and not (tmp_path / "failed.json").exists()
    assert set(doc["items"]) == {"Q0", "Q1", "Q2"} and doc["meta"]["api_ps_before"]["ok"]
    body, timeout = post.calls[0]
    assert body == {"question": "合成題0", "top_k": 5, "include_sources": True, "include_context": True,
                    "retrieval_only": True} and timeout == 180
    rec = doc["items"]["Q0"]
    assert rec["context_sha"] == CX.sha("\n\n".join(s["context"] for s in rec["sources"])) and rec["n_aux"] == 1
    with pytest.raises(SystemExit):
        run_collect(tmp_path, mock_post([good(0)]))                            # F3 is frozen once


@pytest.mark.parametrize("tamper,expect", [
    (lambda r: r["sources"][0].update(build_id="b_other"), "build_id"),
    (lambda r: r["sources"][1].pop("context"), "no context block"),
    (lambda r: r["sources"][0].update(title="另一個標題"), "re-rendered"),
])
def test_9_rejections_are_not_retried(tmp_path, tamper, expect):
    bad = good(0)
    tamper(bad)
    post = mock_post([bad])
    with pytest.raises(SystemExit):
        run_collect(tmp_path, post, QS[:1])
    assert not (tmp_path / "contexts.json").exists() and len(post.calls) == 1
    fail = json.loads((tmp_path / "failed.json").read_text(encoding="utf-8"))["failed"]["Q0"]
    assert fail["kind"] == "Rejected" and expect in fail["log"][0]["error"]


def test_9_infra_failed_retried_up_to_two_times(tmp_path):
    infra = good(0)
    infra["retrieval_stats"]["strategy_errors"] = {"event_registry": "boom"}
    post = mock_post([infra])
    with pytest.raises(SystemExit):
        run_collect(tmp_path, post, QS[:1])
    assert len(post.calls) == 1 + C.COLLECT_RETRIES and not (tmp_path / "contexts.json").exists()
    fail = json.loads((tmp_path / "failed.json").read_text(encoding="utf-8"))["failed"]["Q0"]
    assert fail["kind"] == "Retryable" and all(x["retryable"] for x in fail["log"])


def test_9_http_errors_retried_then_pass(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.HTTPError("u", 502, "bad gateway", {}, None)
    monkeypatch.setattr(CX.urllib.request, "urlopen", boom)
    with pytest.raises(CX.Retryable):
        CX.post_json("http://x", {}, 1)
    flaky = [lambda b: (_ for _ in ()).throw(CX.Retryable("HTTP 502"))] * 2 + [good(0)]
    post = mock_post(list(flaky))
    doc = run_collect(tmp_path, post, QS[:1])
    assert doc["items"]["Q0"]["attempts"] == 3 and len(post.calls) == 3


def test_9_one_failure_freezes_nothing(tmp_path):
    bad = good(0)
    bad["sources"][0]["build_id"] = None
    post = mock_post([good(0), bad, good(0)])
    with pytest.raises(SystemExit):
        run_collect(tmp_path, post)
    doc = json.loads((tmp_path / "failed.json").read_text(encoding="utf-8"))
    assert doc["passed"] == ["Q0", "Q2"] and list(doc["failed"]) == ["Q1"]
    assert not (tmp_path / "contexts.json").exists()


def test_9_refuses_unfrozen_questions(tmp_path):
    q = tmp_path / "questions_frozen.json"
    q.write_text(json.dumps({"questions": QS}, ensure_ascii=False), encoding="utf-8")
    man, ku2 = tmp_path / "manifest.json", tmp_path / "k_u2.json"
    good = C.sha256_file(q)

    def put(path, obj):
        path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(SystemExit, match="missing"):
        CX.frozen_questions(q, man, ku2)                                       # no manifest
    put(man, {"frozen": {"questions_frozen.json": "0" * 64}})
    put(ku2, {"stop": False, "questions_frozen_sha256": "0" * 64})
    with pytest.raises(SystemExit, match="not the F2 manifest sha"):
        CX.frozen_questions(q, man, ku2)                                       # sha differs
    put(man, {"frozen": {"questions_frozen.json": good}})
    with pytest.raises(SystemExit, match="k_u2.json sha"):
        CX.frozen_questions(q, man, ku2)                                       # K-U2 names another file
    put(ku2, {"stop": True, "wording": "K-U2 停", "questions_frozen_sha256": good})
    with pytest.raises(SystemExit, match="K-U2 stopped"):
        CX.frozen_questions(q, man, ku2)
    ku2.unlink()
    with pytest.raises(SystemExit, match="K-U2 was not run"):
        CX.frozen_questions(q, man, ku2)
    put(ku2, {"stop": False, "questions_frozen_sha256": good})
    qs, sha = CX.frozen_questions(q, man, ku2)
    assert [x["id"] for x in qs] == ["Q0", "Q1", "Q2"] and sha == good


def test_9_infra_rule_is_src_validity():
    from src.validity import infra_failed
    assert CX.infra_failed is infra_failed
    assert CX.infra_failed([], {"hybrid": "x"}) and not CX.infra_failed([], {})

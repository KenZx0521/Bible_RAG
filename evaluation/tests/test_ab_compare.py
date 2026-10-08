"""Retrieval A/B comparison with k alignment (2026-10 graph audit).

An appended auxiliary passage makes a treatment's list longer than the
control's, so "treatment ⊇ control" can never lose — the audit nearly read
such a comparison as evidence. Treatment questions that got an extra passage
are therefore compared against an independent control request at the larger k
(chapter-pin depends on top_k, so a prefix of a k=7 run is not a k=6 run).
"""

import asyncio
import copy
import hashlib
import json
import sys
from collections import Counter

import httpx
import pytest

import quick_retrieval_eval as qre
from src.ab_compare import compare, compose_baseline, identity_report, run_k
from src.models import EvalSample, GroundTruthItem, SourceInfo


def _entry(sources, route="R4", vrec=0.5, **extra):
    return {
        "sources": [s["id"] for s in sources], "source_detail": sources, "route": route,
        "verse_recall_at_k": vrec, "anchor_coverage_at_k": vrec, "mrr": vrec, "hit_rate": 1.0,
        **extra,
    }


def _src(cid, gold=False, strategy="semantic"):
    return {"id": cid, "gold": gold, "strategy": strategy}


def _run(per_question, top_k=5, metric_k=6):
    return {"config": {"top_k": top_k, "metric_k": metric_k}, "per_question": per_question}


CORE = [_src(f"a:{i}:0") for i in range(5)]


def test_run_k_defaults_to_top_k_for_legacy_files():
    assert run_k({"config": {"top_k": 5}}) == 5
    assert run_k(_run({}, metric_k=6)) == 6


def test_compare_refuses_runs_scored_at_different_k():
    with pytest.raises(ValueError, match="metric k"):
        compare(_run({}, metric_k=5), _run({}, metric_k=6))


def test_baseline_uses_extended_control_only_where_treatment_appended():
    control = _run({"Q1": _entry(CORE), "Q2": _entry(CORE)})
    ext = _run({"Q1": _entry(CORE + [_src("dense:6:0")])}, top_k=6)
    treat = _run({"Q1": _entry(CORE + [_src("reg:9:0", strategy="event_registry")]),
                  "Q2": _entry(CORE)})

    base = compose_baseline(control, treat, ext)

    assert base["Q1"]["sources"][-1] == "dense:6:0"
    assert base["Q2"] is control["per_question"]["Q2"]


def test_baseline_requires_extended_control_for_every_touched_question():
    treat = _run({"Q1": _entry(CORE + [_src("reg:9:0")])})
    with pytest.raises(ValueError, match="Q1"):
        compose_baseline(_run({"Q1": _entry(CORE)}), treat, _run({}, top_k=6))


def test_compare_reports_core_invariant_touched_and_negatives():
    control = _run({
        "Q1": _entry(CORE, vrec=0.5),
        "Q2": _entry(CORE, vrec=0.5),
        "Q3": _entry(CORE, route="R3", vrec=0.5),
    })
    ext = _run({"Q1": _entry(CORE + [_src("dense:6:0")], vrec=0.6)}, top_k=6)
    treat = _run({
        "Q1": _entry(CORE + [_src("reg:9:0", gold=True)], vrec=0.9),
        "Q2": _entry([_src("x:1:0")] + CORE[1:], vrec=0.4),      # core changed
        "Q3": _entry(CORE, route="R4", vrec=0.5),                  # route noise
    })

    report = compare(control, treat, ext)

    assert report["route_mismatch"] == ["Q3"]
    assert report["invariants"]["core_mismatch"] == ["Q2"]
    assert report["invariants"]["touched"] == ["Q1"]
    assert report["negatives"]["verse_recall_at_k"] == ["Q2"]
    stats = report["stats"]["all"]["verse_recall_at_k"]
    assert (stats["n"], stats["wins"], stats["losses"]) == (2, 1, 1)
    assert report["ledger_summary"] == {"gold_in": 1, "nongold_swap": 1}


def test_compare_drops_invalid_questions():
    control = _run({"Q1": _entry(CORE), "Q2": _entry([], invalid=True)})
    treat = _run({"Q1": _entry(CORE), "Q2": _entry(CORE)})

    report = compare(control, treat)

    assert report["n"] == 1
    assert report["excluded_invalid"] == ["Q2"]


# --- quick eval: what a run records --------------------------------------------

def _sample(sources, errors=None):
    gt = GroundTruthItem(question_id="Q", question="q", question_type="EVENT_QUESTION",
                         book_name="使徒行傳", reference="使徒行傳 9:1-9")
    return EvalSample(question_id="Q", question="q", question_type="EVENT_QUESTION",
                      ground_truth=gt, sources=sources, strategy_errors=errors or {})


def test_source_detail_records_provenance_and_gold():
    sample = _sample([
        SourceInfo(id="act:9:0", book="使徒行傳", chapter=9, verse_range="1-9"),
        SourceInfo(id="gen:1:0", book="創世記", chapter=1, verse_range="1-5"),
    ])
    api = [{"id": "act:9:0", "strategy": "event_registry", "found_by": ["event_registry"],
            "score": None, "rerank_score": None},
           {"id": "gen:1:0", "strategy": "semantic", "found_by": ["semantic"],
            "score": 0.8, "rerank_score": 0.7}]

    detail = qre.source_detail(sample, api)

    assert [(d["id"], d["gold"], d["found_by"]) for d in detail] == [
        ("act:9:0", True, ["event_registry"]), ("gen:1:0", False, ["semantic"]),
    ]
    assert detail[0]["book"] == "使徒行傳" and detail[0]["verse_range"] == "1-9"


def test_aggregate_scores_at_metric_k_and_skips_infra_failures():
    hit = SourceInfo(id="act:9:0", book="使徒行傳", chapter=9, verse_range="1-9")
    filler = [SourceInfo(id=f"gen:{i}:0", book="創世記", chapter=i, verse_range="1-2") for i in range(1, 6)]
    ok = _sample(filler + [hit])
    ok.question_id = "OK"
    bad = _sample([], errors={"hybrid": "ConnectTimeout()"})
    bad.question_id = "BAD"

    agg = qre.aggregate([ok, bad], k=6)

    assert agg["per_question"]["OK"]["verse_recall_at_k"] == 1.0   # 6th source counted
    assert agg["per_question"]["BAD"]["invalid"] is True
    assert agg["overall"]["verse_recall_at_k"] == 1.0
    assert agg["n_invalid"] == 1


def test_touched_question_needs_matching_route_in_extended_control():
    control = _run({"Q1": _entry(CORE, route="R4")})
    ext = _run({"Q1": _entry(CORE + [_src("dense:6:0")], route="R3")}, top_k=6)
    treat = _run({"Q1": _entry(CORE + [_src("reg:9:0")], route="R4")})

    report = compare(control, treat, ext)

    assert report["route_mismatch"] == ["Q1"]
    assert report["n"] == 0


def test_extended_control_must_be_as_long_as_the_treatment():
    """A control_ext run without --top-k 6 would let the treatment never lose."""
    control = _run({"Q1": _entry(CORE)})
    ext = _run({"Q1": _entry(CORE)}, top_k=5)
    treat = _run({"Q1": _entry(CORE + [_src("reg:9:0")])})

    with pytest.raises(ValueError, match="shorter"):
        compare(control, treat, ext)


def test_compare_refuses_different_metric_versions():
    a = _run({"Q1": _entry(CORE)})
    b = _run({"Q1": _entry(CORE)})
    a["config"]["metric_version"] = "aaa"
    b["config"]["metric_version"] = "bbb"

    with pytest.raises(ValueError, match="metric version"):
        compare(a, b)


def test_compare_refuses_identical_lists_with_different_scores():
    """Same passages, different metric = different gold or scoring code."""
    with pytest.raises(ValueError, match="identical"):
        compare(_run({"Q1": _entry(CORE, vrec=0.5)}), _run({"Q1": _entry(CORE, vrec=0.9)}))


def test_quick_eval_records_metric_version_and_strategy_errors():
    version = qre.metric_version()
    assert isinstance(version, str) and len(version) == 12
    sample = _sample([SourceInfo(id="act:9:0", book="使徒行傳", chapter=9, verse_range="1-9")],
                     errors={"graph_event": "boom"})
    agg = qre.aggregate([sample], k=5)
    assert agg["per_question"]["Q"]["strategy_errors"] == {"graph_event": "boom"}


def test_quick_compare_skips_invalid_questions(tmp_path, capsys):
    def run(vrec, invalid):
        return {"overall": {}, "by_type": {}, "per_question": {
            "Q1": {"hit_rate": vrec, "verse_recall_at_k": vrec, "invalid": invalid}}}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run(1.0, False)))
    b.write_text(json.dumps(run(0.0, True)))

    qre.compare(a, b)

    out = capsys.readouterr().out
    assert "Q1 (-" not in out
    assert "excluded (invalid in either run): ['Q1']" in out


# --- quick eval: context digests (identity check, --include-context) ----------

def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_source_detail_records_each_context_digest():
    sample = _sample([
        SourceInfo(id="act:9:0", book="使徒行傳", chapter=9, verse_range="1-9"),
        SourceInfo(id="gen:1:0", book="創世記", chapter=1, verse_range="1-5"),
    ])
    api = [{"id": "act:9:0", "context": "[1] 使徒行傳 第9章\n掃羅"}, {"id": "gen:1:0"}]

    detail = qre.source_detail(sample, api)

    assert detail[0]["context_sha256"] == _sha("[1] 使徒行傳 第9章\n掃羅")
    assert detail[1]["context_sha256"] is None


def test_context_digest_hashes_blocks_as_the_generator_joins_them():
    blocks = [{"context": "[1] 創世記 第1章\n起初"}, {"context": "[2] 約翰福音 第1章\n太初"}]

    assert qre.context_digest(blocks) == _sha("[1] 創世記 第1章\n起初\n\n[2] 約翰福音 第1章\n太初")
    assert qre.context_digest(blocks[::-1]) != qre.context_digest(blocks)


def test_context_digest_refuses_sources_without_context():
    """An image without include_context drops the field; equal empty digests would pass."""
    with pytest.raises(RuntimeError, match="context"):
        qre.context_digest([{"id": "act:9:0", "context": "[1] x"}, {"id": "gen:1:0"}])


def _query(include_context, sources):
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            "answer": "", "sources": sources,
            "retrieval_stats": {"route_used": "R4", "graph_strategies": ["event_registry"]},
        })

    gt = GroundTruthItem(question_id="Q", question="q", question_type="EVENT_QUESTION",
                         book_name="使徒行傳", reference="使徒行傳 9:1-9")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await qre._query_one(client, asyncio.Semaphore(1), gt, None, None, 5,
                                        include_context=include_context)

    return captured, asyncio.run(go())


def test_query_one_requests_context_and_records_its_digest():
    block = "[1] 使徒行傳 第9章 (1-9節)\n掃羅"
    src = {"id": "act:9:0", "book": "使徒行傳", "chapter": 9, "title": "", "verse_range": "1-9",
           "strategy": "semantic", "context": block}

    payload, (_, detail, applied, extra) = _query(True, [src])

    assert payload["include_context"] is True
    assert extra["context_sha"] == _sha(block)
    assert detail[0]["context_sha256"] == _sha(block)
    assert applied == ["event_registry"]


def test_query_one_without_the_flag_leaves_payload_and_record_unchanged():
    src = {"id": "act:9:0", "book": "使徒行傳", "chapter": 9, "title": "", "verse_range": "1-9"}

    payload, (_, _, _, extra) = _query(False, [src])

    assert "include_context" not in payload
    assert "context_sha" not in extra


def test_applied_counts_labels_unreported_and_empty_lists():
    counts = qre.applied_counts({"Q1": ["cross_ref_expand", "graph_event"], "Q2": None, "Q3": []})

    assert counts == {"cross_ref_expand,graph_event": 1, "legacy (not reported)": 1, "(none)": 1}


def test_quick_eval_records_include_context_in_config(tmp_path, monkeypatch):
    seen = {}
    sample = _sample([SourceInfo(id="act:9:0", book="使徒行傳", chapter=9, verse_range="1-9")])

    async def fake_collect(*args, **kwargs):
        seen.update(kwargs)
        return ([sample], {"Q": [{"id": "act:9:0", "context_sha256": "s1"}]},
                {"Q": ["event_registry"]}, {"Q": {"context_sha": "c1"}})

    monkeypatch.setattr(qre, "collect", fake_collect)
    monkeypatch.setattr(qre, "fetch_health", lambda url: {"status": "ok"})
    monkeypatch.setattr(qre, "_OUT_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["quick_retrieval_eval.py", "--include-context", "--label", "t",
                                      "--gt", "v1"])

    assert qre.main() == 0

    out = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert seen["include_context"] is True
    assert out["config"]["include_context"] is True
    assert out["per_question"]["Q"]["context_sha"] == "c1"


# --- ab_compare --require-identical (identity check) --------------------------

CORE5 = [f"a:{i}:0" for i in range(5)]


def _ident_entry(ids, route="R4", ctx=None, strategies=("event_registry",), invalid=False):
    return {
        "sources": list(ids), "route": route, "invalid": invalid,
        "source_detail": [{"id": i, "gold": False, "context_sha256": f"sha-{i}"} for i in ids],
        "context_sha": ctx or "ctx-" + "|".join(ids),
        "graph_strategies": None if strategies is None else list(strategies),
    }


def _ident_run(per_question, top_k=5, include_context=True):
    applied = Counter("legacy (not reported)" if e["graph_strategies"] is None
                      else ",".join(e["graph_strategies"]) for e in per_question.values())
    return {"config": {"top_k": top_k, "metric_k": 6, "include_context": include_context,
                       "use_graph": True, "fusion_alpha": None,
                       "graph_strategies_requested": None,
                       "graph_strategies_applied": dict(applied)},
            "per_question": per_question}


def test_identical_runs_pass_the_identity_check():
    run = _ident_run({"Q1": _ident_entry(CORE5), "Q2": _ident_entry(CORE5 + ["reg:9:0"])})

    report = identity_report(run, copy.deepcopy(run))

    assert report["passed"] is True
    assert (report["n_paired"], report["same_route"], report["identical"]) == (2, 2, 2)
    assert report["mismatches"] == {}
    assert report["strategies"]["identical"] is True


def test_identity_flags_a_changed_core_passage():
    control = _ident_run({"Q1": _ident_entry(CORE5), "Q2": _ident_entry(CORE5)})
    treat = _ident_run({"Q1": _ident_entry(["x:1:0"] + CORE5[1:]), "Q2": _ident_entry(CORE5)})

    report = identity_report(control, treat)

    assert report["passed"] is False
    assert report["identical"] == 1
    assert set(report["mismatches"]) == {"Q1"}
    assert report["mismatches"]["Q1"]["core"] == {"control": CORE5,
                                                  "treatment": ["x:1:0"] + CORE5[1:]}
    assert "appended" not in report["mismatches"]["Q1"]


@pytest.mark.parametrize("control_tail, treat_tail", [
    (["reg:9:0"], ["reg:7:0"]),   # a different auxiliary passage
    (["reg:9:0"], []),            # the auxiliary passage disappeared
    ([], ["reg:9:0"]),            # a new auxiliary passage
])
def test_identity_flags_a_changed_appended_passage(control_tail, treat_tail):
    control = _ident_run({"Q1": _ident_entry(CORE5 + control_tail)})
    treat = _ident_run({"Q1": _ident_entry(CORE5 + treat_tail)})

    diff = identity_report(control, treat)["mismatches"]["Q1"]

    assert "core" not in diff
    assert diff["appended"] == {"control": control_tail, "treatment": treat_tail}


def test_identity_flags_context_change_on_identical_passages():
    """Same ids, different text or header: only the context digests can tell."""
    control = _ident_run({"Q1": _ident_entry(CORE5)})
    edited = _ident_entry(CORE5, ctx="ctx-edited")
    edited["source_detail"][2]["context_sha256"] = "sha-edited"
    treat = _ident_run({"Q1": edited})

    report = identity_report(control, treat)

    assert report["passed"] is False
    diff = report["mismatches"]["Q1"]
    assert set(diff) == {"context_sha"}
    assert diff["context_sha"]["positions"] == [2]
    assert diff["context_sha"]["treatment"] == "ctx-edited"


def test_identity_requires_the_same_applied_graph_strategies():
    control = _ident_run({"Q1": _ident_entry(CORE5)})
    treat = _ident_run({"Q1": _ident_entry(CORE5, strategies=("graph_event",))})

    report = identity_report(control, treat)

    assert report["passed"] is False
    assert report["mismatches"] == {}
    assert report["strategies"]["identical"] is False
    assert report["strategies"]["per_question_mismatch"] == ["Q1"]


def test_identity_requires_matching_run_level_strategy_counts():
    control = _ident_run({"Q1": _ident_entry(CORE5)})
    treat = _ident_run({"Q1": _ident_entry(CORE5)})
    treat["config"]["graph_strategies_applied"] = {"(none)": 1}

    report = identity_report(control, treat)

    assert report["passed"] is False
    assert report["strategies"]["treatment"] == {"(none)": 1}


def test_identity_cannot_vouch_for_unreported_strategies():
    control = _ident_run({"Q1": _ident_entry(CORE5, strategies=None)})
    treat = _ident_run({"Q1": _ident_entry(CORE5, strategies=None)})

    report = identity_report(control, treat)

    assert report["strategies"]["identical"] is False
    assert report["strategies"]["unreported"] == ["Q1"]
    assert report["passed"] is False


def test_route_mismatch_is_listed_apart_and_not_failed():
    control = _ident_run({"Q1": _ident_entry(CORE5, route="R3"), "Q2": _ident_entry(CORE5)})
    treat = _ident_run({"Q1": _ident_entry(["x:1:0"] + CORE5[1:], route="R4"),
                        "Q2": _ident_entry(CORE5)})

    report = identity_report(control, treat)

    assert report["route_mismatch"] == ["Q1"]
    assert report["routes"] == {"Q1": {"control": "R3", "treatment": "R4"}}
    assert report["same_route"] == 1
    assert report["mismatches"] == {}
    assert report["passed"] is True


def test_identity_fails_on_invalid_questions():
    control = _ident_run({"Q1": _ident_entry(CORE5), "Q2": _ident_entry([], invalid=True)})
    treat = _ident_run({"Q1": _ident_entry(CORE5), "Q2": _ident_entry(CORE5)})

    report = identity_report(control, treat)

    assert report["invalid"] == ["Q2"]
    assert "Q2" not in report["mismatches"]
    assert report["unpaired"] == {"control_only": [], "treatment_only": []}
    assert report["strategies"]["identical"] is True
    assert report["passed"] is False


@pytest.mark.parametrize("control_only, treatment_only", [
    (["Q3"], ["Q4"]),   # swapped ids: run-level strategy counts agree on their own
    (["Q3"], []),
    ([], ["Q4"]),
])
def test_identity_fails_on_unpaired_questions(control_only, treatment_only):
    """Run-level strategy counts are made equal so that only the pairing can fail."""
    control = _ident_run({q: _ident_entry(CORE5) for q in ["Q1", *control_only]})
    treat = _ident_run({q: _ident_entry(CORE5) for q in ["Q1", *treatment_only]})
    treat["config"]["graph_strategies_applied"] = control["config"]["graph_strategies_applied"]

    report = identity_report(control, treat)

    assert report["unpaired"] == {"control_only": control_only, "treatment_only": treatment_only}
    assert report["invalid"] == []
    assert report["strategies"]["identical"] is True
    assert report["passed"] is False


@pytest.mark.parametrize("make_legacy", [
    lambda run: run["config"].pop("include_context"),          # run predates the flag
    lambda run: run["per_question"]["Q1"].pop("context_sha"),  # one entry lacks a digest
])
def test_identity_refuses_runs_without_context_digests(make_legacy):
    legacy = _ident_run({"Q1": _ident_entry(CORE5)})
    make_legacy(legacy)

    with pytest.raises(ValueError, match="--include-context"):
        identity_report(_ident_run({"Q1": _ident_entry(CORE5)}), legacy)


@pytest.mark.parametrize("key, value", [
    ("top_k", 6),
    ("use_graph", False),
    ("fusion_alpha", 0.3),
    ("graph_strategies_requested", ["graph_event"]),
])
def test_identity_refuses_runs_requested_with_different_settings(key, value):
    treat = _ident_run({"Q1": _ident_entry(CORE5)})
    treat["config"][key] = value

    with pytest.raises(ValueError, match=key):
        identity_report(_ident_run({"Q1": _ident_entry(CORE5)}), treat)


def test_identity_refuses_runs_without_common_questions():
    with pytest.raises(ValueError, match="no question"):
        identity_report(_ident_run({"Q1": _ident_entry(CORE5)}),
                        _ident_run({"Q2": _ident_entry(CORE5)}))


def _cli(tmp_path, monkeypatch, control, treat, *extra):
    import ab_compare as cli

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(control), encoding="utf-8")
    b.write_text(json.dumps(treat), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ab_compare.py", str(a), str(b), "--require-identical", *extra])
    return cli.main()


def test_ab_compare_cli_require_identical_exit_codes(tmp_path, monkeypatch, capsys):
    same = _ident_run({"Q1": _ident_entry(CORE5)})
    assert _cli(tmp_path, monkeypatch, same, copy.deepcopy(same)) == 0

    changed = _ident_run({"Q1": _ident_entry(["x:1:0"] + CORE5[1:])})
    assert _cli(tmp_path, monkeypatch, same, changed) == 1
    out = capsys.readouterr().out
    assert "Q1" in out and "core" in out


def test_ab_compare_cli_pass_says_route_mismatches_were_not_judged(tmp_path, monkeypatch,
                                                                    capsys):
    control = _ident_run({"Q1": _ident_entry(CORE5, route="R3"), "Q2": _ident_entry(CORE5)})
    treat = _ident_run({"Q1": _ident_entry(["x:1:0"] + CORE5[1:], route="R4"),
                        "Q2": _ident_entry(CORE5)})

    assert _cli(tmp_path, monkeypatch, control, treat) == 0
    assert "identity: PASS (1 route mismatch not judged; re-ask them)" in capsys.readouterr().out

    assert _cli(tmp_path, monkeypatch, control, copy.deepcopy(control)) == 0
    assert capsys.readouterr().out.rstrip().endswith("identity: PASS")


def test_ab_compare_cli_rejects_legacy_runs_with_exit_1(tmp_path, monkeypatch, capsys):
    legacy = _ident_run({"Q1": _ident_entry(CORE5)}, include_context=False)

    assert _cli(tmp_path, monkeypatch, legacy, copy.deepcopy(legacy)) == 1
    assert "--include-context" in capsys.readouterr().err

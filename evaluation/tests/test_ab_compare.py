"""Retrieval A/B comparison with k alignment (2026-10 graph audit).

An appended auxiliary passage makes a treatment's list longer than the
control's, so "treatment ⊇ control" can never lose — the audit nearly read
such a comparison as evidence. Treatment questions that got an extra passage
are therefore compared against an independent control request at the larger k
(chapter-pin depends on top_k, so a prefix of a k=7 run is not a k=6 run).
"""

import pytest

import quick_retrieval_eval as qre
from src.ab_compare import compare, compose_baseline, run_k
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
    import json
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

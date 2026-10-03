"""graph_strategies plumbing on the evaluation side (2026-10 per-strategy gating).

- The collector must not silently delete a pre-gating archive (records without
  `graph_strategies`): those are the Round 3 run-of-record files, and `--graph`
  now means graph_event only, so a rerun would overwrite a different condition.
- The A/B tools must fail loudly when the backend did not apply the requested
  strategies (e.g. an image built before the field existed silently drops it).
"""

import json

import pytest

import quick_retrieval_eval as qre
from src import collector


# --- collector archive guard -------------------------------------------------

def _write_raw(path, records):
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_clear_refuses_pre_gating_archive(tmp_path, monkeypatch):
    raw = tmp_path / "raw_responses.json"
    _write_raw(raw, [{"question_id": "Q1", "use_graph": True}])
    monkeypatch.setattr(collector, "_raw_responses_path", lambda: raw)

    with pytest.raises(RuntimeError, match="graph_strategies"):
        collector._clear_previous_results()

    assert raw.exists()


def test_clear_removes_gated_checkpoint(tmp_path, monkeypatch):
    raw = tmp_path / "raw_responses.json"
    _write_raw(raw, [{"question_id": "Q1", "graph_strategies": ["graph_event"]}])
    monkeypatch.setattr(collector, "_raw_responses_path", lambda: raw)

    collector._clear_previous_results()

    assert not raw.exists()


def test_clear_removes_empty_checkpoint(tmp_path, monkeypatch):
    raw = tmp_path / "raw_responses.json"
    _write_raw(raw, [])
    monkeypatch.setattr(collector, "_raw_responses_path", lambda: raw)

    collector._clear_previous_results()

    assert not raw.exists()


def test_clear_without_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "_raw_responses_path", lambda: tmp_path / "missing.json")
    collector._clear_previous_results()


# --- applied-strategy check ----------------------------------------------------

def test_check_passes_through_backend_report_when_nothing_requested():
    assert qre.applied_graph_strategies(None, {"graph_strategies": ["graph_event"]}) == ["graph_event"]


def test_check_tolerates_old_backend_when_nothing_requested():
    assert qre.applied_graph_strategies(None, {}) is None


def test_check_rejects_backend_that_dropped_the_field():
    with pytest.raises(RuntimeError, match="rebuild"):
        qre.applied_graph_strategies(["all"], {"use_graph": True})


def test_check_rejects_mismatched_explicit_list():
    stats = {"use_graph": True, "graph_strategies": ["graph_event"]}
    with pytest.raises(RuntimeError, match="graph_person"):
        qre.applied_graph_strategies(["graph_event", "graph_person"], stats)


def test_check_accepts_matching_explicit_list():
    stats = {"use_graph": True, "graph_strategies": ["graph_event", "graph_person"]}
    assert qre.applied_graph_strategies(["graph_person", "graph_event"], stats) == [
        "graph_event", "graph_person"]


def test_check_accepts_all_when_backend_reports_a_full_set():
    stats = {"use_graph": True, "graph_strategies": ["cross_ref_expand", "graph_event"]}
    assert qre.applied_graph_strategies(["all"], stats) == ["cross_ref_expand", "graph_event"]


def test_check_accepts_empty_report_when_graph_is_off():
    stats = {"use_graph": False, "graph_strategies": []}
    assert qre.applied_graph_strategies(["graph_event"], stats) == []

"""Collection audit trail (2026-10-28 P0): raw_responses.json keeps what /api/v1/query said
about each question, the arm it was asked under, when and how long; run_meta.json v2 is
written when collection starts and completed when it ends.

The backend is answered in-process; git, docker and Ollama are refused (conftest).
"""

import asyncio
import json
import sys
from datetime import datetime

import pytest

import run_eval
from src import collector, evaluator
from src import run_record as rr
from src.config import settings
from src.data_loader import load_gt
from src.provenance import RUN_META, Provenance

GT = load_gt("v2")
BUILD = "b20261008_0000abcd"
INTENT = {"type": "verse_lookup", "entities": ["約翰"], "verse_refs": ["約翰福音3:16"],
          "rejected_refs": ["約翰福音3:99"]}
STATS = {"route_used": "R1", "strategies_used": ["verse_direct"], "strategy_errors": {},
         "use_graph": False, "graph_strategies": [], "total_candidates": 17, "reranked_top_k": 5,
         "fusion_alpha": 0.3, "event_registry_events": ["ev:jhn.3"]}
BLOCK = "[1] 約翰福音 第3章 (16節)\n16 上帝愛世人"
SOURCE = {"id": "ps:jhn.3.16", "book": "約翰福音", "chapter": 3, "verse_range": "16",
          "context": BLOCK, "strategy": "verse_direct"}


@pytest.fixture(autouse=True)
def _results_dir_back_to_modes():
    yield
    settings.set_results_dir(None)
    settings.set_graph_mode(None)
    settings.set_semantic_mode(False)


def _answer(stats=STATS, intent=INTENT):
    body = {"answer": "上帝愛世人", "sources": [SOURCE], "retrieval_stats": dict(stats)}
    if intent is not None:
        body["intent"] = intent
    return body


def _offline(monkeypatch, tmp_path, query):
    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def no_sleep(*args, **kwargs):
        pass

    monkeypatch.setattr(collector, "query_rag", query)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(type(collector.settings), "results_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)


def _collect(questions, provenance=None, **kwargs):
    return asyncio.run(collector.collect_responses(questions, provenance=provenance, **kwargs))


def _raw(tmp_path):
    return json.loads((tmp_path / "raw_responses.json").read_text(encoding="utf-8"))


def _has_tz(text):
    return datetime.fromisoformat(text).tzinfo is not None


# --- A1: per-question raw fields -----------------------------------------------------------

def test_each_record_keeps_intent_stats_mode_time_and_latency(monkeypatch, tmp_path):
    async def query(*args, **kwargs):
        return _answer()

    _offline(monkeypatch, tmp_path, query)

    samples, _ = _collect(list(GT.items[:1]), use_graph=True)

    rec = _raw(tmp_path)[0]
    assert rec["intent"] == INTENT
    assert {k: rec[k] for k in ("fusion_alpha", "total_candidates", "reranked_top_k",
                                "event_registry_events")} == {
        "fusion_alpha": 0.3, "total_candidates": 17, "reranked_top_k": 5,
        "event_registry_events": ["ev:jhn.3"]}
    assert rec["mode"] == "graph"
    assert rec["use_graph"] is False             # what the backend reported, not the CLI flag
    assert _has_tz(rec["collected_at"])
    assert isinstance(rec["latency_ms"], (int, float)) and rec["latency_ms"] >= 0
    assert rec["request_attempts"] == 1
    assert (samples[0].intent, samples[0].mode) == (INTENT, "graph")


SEMANTIC_STATS = {**STATS, "route_used": "semantic_only", "strategies_used": ["semantic"],
                  "use_graph": True, "graph_strategies": [], "fusion_alpha": None,
                  "event_registry_events": []}


def test_semantic_mode_is_the_arm_though_the_backend_reports_use_graph_true(monkeypatch, tmp_path):
    """A semantic_only request carries no use_graph, so the backend reports RAG_USE_GRAPH
    (true; utils/retrieval/router.py): use_graph never tells the semantic arm, mode does."""
    payloads = []

    async def query(*args, **kwargs):
        payloads.append(kwargs)
        return _answer(stats=SEMANTIC_STATS)

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]), semantic_only=True)

    rec = _raw(tmp_path)[0]
    assert rec["mode"] == "semantic" and rec["use_graph"] is True
    assert rec["route_used"] == "semantic_only"
    assert payloads[0].get("use_graph") is None and payloads[0].get("semantic_only") is True


def test_a_use_graph_the_backend_does_not_report_is_null(monkeypatch, tmp_path):
    async def query(*args, **kwargs):
        return _answer(stats={k: v for k, v in STATS.items() if k != "use_graph"}, intent=None)

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]), use_graph=True)

    rec = _raw(tmp_path)[0]
    assert rec["mode"] == "graph" and rec["use_graph"] is None and rec["intent"] is None


@pytest.mark.parametrize("use_graph, semantic, mode", [
    (None, False, "default"), (False, False, "no_graph")])
def test_mode_names_every_arm(monkeypatch, tmp_path, use_graph, semantic, mode):
    async def query(*args, **kwargs):
        return _answer()

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]), use_graph=use_graph, semantic_only=semantic)

    assert _raw(tmp_path)[0]["mode"] == mode


def test_a_failed_request_keeps_the_same_fields_null(monkeypatch, tmp_path):
    async def query(*args, **kwargs):
        raise RuntimeError("HTTP 500")

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]), use_graph=True, graph_strategies=["event_registry"])

    rec = _raw(tmp_path)[0]
    assert rec["mode"] == "graph" and rec["use_graph"] is None
    assert rec["graph_strategies"] == ["event_registry"]       # unchanged: what was asked
    assert all(rec[k] is None for k in ("intent", "fusion_alpha", "total_candidates",
                                        "reranked_top_k", "event_registry_events"))
    assert _has_tz(rec["collected_at"]) and rec["latency_ms"] >= 0
    assert rec["request_attempts"] == 3 and "request" in rec["strategy_errors"]


def test_a_retried_request_counts_its_attempts(monkeypatch, tmp_path):
    calls = []

    async def query(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("ReadError")
        return _answer()

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]))

    assert _raw(tmp_path)[0]["request_attempts"] == 2


# --- A2: run_meta.json written at the start, completed at the end ---------------------------

def test_run_meta_is_on_disk_before_the_first_question_and_finished_after(monkeypatch, tmp_path):
    seen = []

    async def query(*args, **kwargs):
        seen.append(json.loads((tmp_path / RUN_META).read_text(encoding="utf-8")))
        return _answer()

    _offline(monkeypatch, tmp_path, query)
    inputs = rr.CollectionInputs(argv=("run_eval.py", "--graph"), health={"handshake": {"ok": True}})

    _collect(list(GT.items[:2]), provenance=Provenance(BUILD), use_graph=True, inputs=inputs)

    first = seen[0]
    assert first["data_build_id"] == BUILD and first["run_meta_version"] == 2
    assert first["collection"]["finished_at"] is None and _has_tz(first["collection"]["started_at"])
    assert first["collection"]["mode"] == "graph" and first["collection"]["n_questions"] == 2
    assert first["backend_health"]["ok"] is True
    done = json.loads((tmp_path / RUN_META).read_text(encoding="utf-8"))
    assert _has_tz(done["collection"]["finished_at"])
    assert done["collection"]["started_at"] == first["collection"]["started_at"]
    assert (done["collection"]["n_collected"], done["collection"]["n_request_failures"]) == (2, 0)


def test_an_interrupted_collection_leaves_started_at_on_disk(monkeypatch, tmp_path):
    async def query(*args, **kwargs):
        return _answer()

    def disk_full(collected):
        raise OSError("disk full")

    _offline(monkeypatch, tmp_path, query)
    monkeypatch.setattr(collector, "_save_responses", disk_full)

    with pytest.raises(OSError, match="disk full"):
        _collect(list(GT.items[:1]), provenance=Provenance(BUILD))

    meta = json.loads((tmp_path / RUN_META).read_text(encoding="utf-8"))
    assert _has_tz(meta["collection"]["started_at"]) and meta["collection"]["finished_at"] is None


def test_no_provenance_writes_no_run_meta(monkeypatch, tmp_path):
    async def query(*args, **kwargs):
        return _answer()

    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]))

    assert not (tmp_path / RUN_META).exists()


# --- run_eval: the CLI's argv, ids file and /health reach the record ------------------------

class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _client_class():
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):
            return _Response(_answer())
    return _Client


def test_cli_collection_records_mode_argv_ids_file_and_health(monkeypatch, tmp_path, write_contracts):
    import src.provenance

    class _Pool:
        async def close(self):
            pass

    async def pool():
        return _Pool()

    async def no_sleep(*args, **kwargs):
        pass

    health = {"status": "ok", "build_id": BUILD, "encoder": None,
              "handshake": {"build_id": BUILD, "ok": True, "strict": True, "mismatches": []}}
    monkeypatch.setattr(collector.httpx, "AsyncClient", _client_class())
    monkeypatch.setattr(src.provenance, "fetch_health", lambda url: health)
    monkeypatch.setattr(collector, "get_pool", pool)
    monkeypatch.setattr(collector.settings, "request_delay", 0)
    monkeypatch.setattr(collector.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(run_eval, "_setup_logging", lambda: None)
    ids = tmp_path / "ids.txt"
    ids.write_text("VERSE_LOOKUP_001\n", encoding="utf-8")
    out = tmp_path / "arm"
    argv = ["run_eval.py", "--collect-only", "--graph", "--gt", "v2", "--contracts-dir",
            str(write_contracts(tmp_path / "contracts")), "--ids-file", str(ids),
            "--results-dir", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    run_eval.main()

    meta = json.loads((out / RUN_META).read_text(encoding="utf-8"))
    col = meta["collection"]
    assert (col["mode"], col["argv"], col["ids_file"], col["n_questions"]) == (
        "graph", argv, str(ids), 1)
    assert col["ids_file_sha256"] and _has_tz(col["finished_at"])
    assert meta["backend_health"] == {"status": "ok", "services": None, "ok": True,
                                      "strict": True, "mismatches": []}
    assert _raw(out)[0]["mode"] == "graph"


def test_eval_only_on_an_old_checkpoint_is_not_refused(monkeypatch, tmp_path):
    """A3: a checkpoint with neither run_meta v2 nor the new raw fields still evaluates."""
    (tmp_path / "raw_responses.json").write_text(json.dumps([{
        "question_id": "VERSE_LOOKUP_001", "question": "q", "rag_answer": "a", "contexts": ["c"],
        "context_source": "backend", "sources": [], "use_graph": True,
        "graph_strategies": ["event_registry"]}]))
    monkeypatch.setattr(type(evaluator.settings), "results_dir", property(lambda self: tmp_path))

    samples = evaluator.load_samples_from_checkpoint(gt=GT)

    assert (samples[0].intent, samples[0].mode) == (None, None)


def test_an_odd_ollama_tags_body_does_not_stop_the_collection(monkeypatch, tmp_path):
    """/api/tags answering a list once raised out of start_record before the first question."""
    async def query(*args, **kwargs):
        return _answer()

    inspect = [{"Config": {"Image": "bible_rag-backend:r5",
                           "Env": ["LLM_PROVIDER=ollama", "OLLAMA_MODEL=gemma4:e4b"]},
                "Image": "sha256:img", "State": {"StartedAt": "t"}}]
    monkeypatch.setattr(rr, "_run", lambda cmd, timeout: json.dumps(inspect) if cmd[0] == "docker"
                        else (_ for _ in ()).throw(RuntimeError("no git")))
    monkeypatch.setattr(rr, "_get_json", lambda url, timeout: [])
    _offline(monkeypatch, tmp_path, query)

    _collect(list(GT.items[:1]), provenance=Provenance(BUILD), use_graph=True)

    assert len(_raw(tmp_path)) == 1
    meta = json.loads((tmp_path / RUN_META).read_text(encoding="utf-8"))
    assert meta["generator"]["provider"] == "ollama" and "error" in meta["generator"]
    assert meta["collection"]["finished_at"] is not None

"""probes/xref_measure: the measured side of xref 模擬等於實測 (W1 1B-T2).

The probe must measure through the real retriever functions (the XREF-3 call
sites in cross_ref_retriever), never query Postgres, open only READ sessions,
and close the driver whatever happens. Neo4j and Postgres are faked here; the
real stores are only touched by the acceptance runs.
"""

import asyncio
import io
import json
import re
from pathlib import Path

import neo4j
import pytest

from config import settings
from database import neo4j_db, postgres
from probes import xref_measure
from utils.retrieval import cross_ref_retriever as xr

SEEDS = {"version": 1, "questions_sha256": "0" * 64,
         "singles": ["jer:29:0", "rom:8:1"], "sets": {"GENERAL_001": ["rom:8:1", "jer:29:0"]}}
KEYS = ["legacy:jer:29:0", "legacy:rom:8:1", "q:GENERAL_001", "single:jer:29:0", "single:rom:8:1"]
NEIGHBOUR = {"id": "isa:55:0", "hop_distance": 1, "curated": False, "votes": 1130}
ROUTER = Path(__file__).resolve().parents[1] / "utils" / "retrieval" / "router.py"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    async def data(self):
        return [dict(r) for r in self._rows]


class FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, **params):
        return FakeResult(self._rows)


class FakeDriver:
    """Answers every query with the same rows; records each session's access mode."""

    def __init__(self, rows):
        self.rows, self.modes, self.closed = rows, [], False

    def session(self, **kwargs):
        self.modes.append(kwargs.get("default_access_mode"))
        return FakeSession(self.rows)

    async def close(self):
        self.closed = True


@pytest.fixture
def driver(monkeypatch):
    fake = FakeDriver([NEIGHBOUR])

    async def init_driver():
        neo4j_db._driver = fake
        return fake

    monkeypatch.setattr(neo4j_db, "init_driver", init_driver)
    monkeypatch.setattr(neo4j_db, "_driver", None)
    return fake


def _as_json(rows):
    return json.dumps(rows)


def test_measure_goes_through_the_retrievers(monkeypatch, driver):
    calls = []

    async def multi_hop(ids, max_hops=2, limit=30):
        calls.append(("multi_hop", list(ids), max_hops, limit))
        return [
            {"id": ids[0], "hop_distance": 1, "curated": True},      # a seed: the retriever skips it
            dict(NEIGHBOUR),
            {"id": "isa:55:0", "hop_distance": 2, "curated": True},  # repeated id: skipped
            {"id": "gen:1:0", "hop_distance": 2, "curated": 1},      # the retriever makes it a bool
        ]

    async def one_hop(pid, limit=10):
        calls.append(("legacy", pid, limit))
        return [{"id": "eph:1:1", "curated": False, "votes": 1268},
                {"id": "jer:1:1", "curated": True, "votes": 5}]

    monkeypatch.setattr(neo4j_db, "get_cross_references_multi_hop", multi_hop)
    monkeypatch.setattr(neo4j_db, "get_cross_references", one_hop)

    doc = asyncio.run(xref_measure.measure(SEEDS))

    assert doc["version"] == 1
    assert doc["params"] == {"max_hops": settings.rag_cross_ref_max_hops,
                             "limit": settings.rag_cross_ref_expand_limit}
    assert doc["params"] == {"max_hops": 2, "limit": 10}
    assert sorted(doc["rows"]) == KEYS
    assert _as_json(doc["rows"]["single:rom:8:1"]) == _as_json(
        [["isa:55:0", 1, False, 0.60], ["gen:1:0", 2, True, 0.55]])
    assert _as_json(doc["rows"]["legacy:rom:8:1"]) == _as_json(
        [["eph:1:1", 1, False, 0.60], ["jer:1:1", 1, True, 0.75]])
    for rows in doc["rows"].values():
        assert rows
        for _, hop, curated, weight in rows:
            assert weight == xr._edge_weight(hop, curated)
    assert ("multi_hop", ["rom:8:1"], 2, 10) in calls
    assert ("legacy", "rom:8:1", 10) in calls
    assert ("multi_hop", ["rom:8:1", "jer:29:0"], 2, 10) in calls


def test_params_follow_the_router_settings(monkeypatch, driver):
    """RAG_CROSS_REF_MAX_HOPS / RAG_CROSS_REF_EXPAND_LIMIT reach the probe as they reach the router."""
    calls = []

    async def multi_hop(ids, max_hops=2, limit=30):
        calls.append(("multi_hop", list(ids), max_hops, limit))
        return [dict(NEIGHBOUR)]

    monkeypatch.setattr(neo4j_db, "get_cross_references_multi_hop", multi_hop)
    monkeypatch.setattr(settings, "rag_cross_ref_max_hops", 3)
    monkeypatch.setattr(settings, "rag_cross_ref_expand_limit", 7)

    doc = asyncio.run(xref_measure.measure(SEEDS))

    assert doc["params"] == {"max_hops": 3, "limit": 7}
    assert ("multi_hop", ["rom:8:1"], 3, 7) in calls


def test_legacy_top_k_is_the_router_literal():
    """LEGACY_TOP_K copies the router's legacy call; every call site must still pass it."""
    calls = re.findall(r"\bretrieve_cross_references\(([^)]*)\)", ROUTER.read_text(encoding="utf-8"))

    assert calls == [f"source_ids, top_k={xref_measure.LEGACY_TOP_K}"]


def test_neo4j_db_runs_queries_only_through_session_run():
    """READ_ACCESS binds session.run and begin_transaction, not execute_write: the
    probe's read-only claim holds only while neo4j_db calls nothing else."""
    source = Path(neo4j_db.__file__).read_text(encoding="utf-8")

    assert set(re.findall(r"\bsession\.(\w+)\(", source)) == {"run"}
    assert not re.search(r"\b(execute_write|write_transaction)\b", source)


def test_postgres_is_stubbed_and_restored(monkeypatch, driver):
    async def real_postgres(pericope_id):
        raise AssertionError("the probe must not query Postgres")

    monkeypatch.setattr(postgres, "get_content_by_id", real_postgres)
    seen = []

    async def multi_hop(ids, max_hops=2, limit=30):
        seen.append(postgres.get_content_by_id)
        return [dict(NEIGHBOUR)]

    monkeypatch.setattr(neo4j_db, "get_cross_references_multi_hop", multi_hop)

    doc = asyncio.run(xref_measure.measure(SEEDS))

    assert seen and all(fn is not real_postgres for fn in seen)
    assert doc["rows"]["single:rom:8:1"] == [["isa:55:0", 1, False, 0.60]]  # stub content is truthy
    assert postgres.get_content_by_id is real_postgres

    async def broken(ids, max_hops=2, limit=30):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(neo4j_db, "get_cross_references_multi_hop", broken)
    with pytest.raises(RuntimeError, match="neo4j down"):
        asyncio.run(xref_measure.measure(SEEDS))
    assert postgres.get_content_by_id is real_postgres


def test_sessions_are_read_access(driver):
    doc = asyncio.run(xref_measure.measure(SEEDS))

    # one session per legacy key, one or two (sparse fallback) per multi-hop key
    assert len(driver.modes) >= len(KEYS)
    assert set(driver.modes) == {neo4j.READ_ACCESS}
    assert doc["rows"]["legacy:jer:29:0"] == [["isa:55:0", 1, False, 0.60]]
    assert driver.closed and neo4j_db._driver is None

    xref_measure._ReadOnlyDriver(driver).session(default_access_mode=neo4j.WRITE_ACCESS)
    assert driver.modes[-1] == neo4j.READ_ACCESS


def test_close_driver_runs_on_error(monkeypatch, driver):
    async def broken(pericope_id, limit=10):
        raise RuntimeError("boom")

    monkeypatch.setattr(neo4j_db, "get_cross_references", broken)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(xref_measure.measure(SEEDS))

    assert driver.closed
    assert neo4j_db._driver is None


def test_main_reads_stdin_writes_json(monkeypatch, capsys, driver):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(SEEDS)))

    assert xref_measure.main() == 0

    doc = json.loads(capsys.readouterr().out)  # stdout holds the JSON document only
    assert doc["version"] == 1
    assert doc["params"] == {"max_hops": 2, "limit": 10}
    assert sorted(doc["rows"]) == KEYS
    assert doc["rows"]["q:GENERAL_001"] == [["isa:55:0", 1, False, 0.60]]


def test_rejects_a_seed_file_of_another_version(monkeypatch, capsys, driver):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({**SEEDS, "version": 2})))

    with pytest.raises(ValueError, match="version"):
        xref_measure.main()

    assert capsys.readouterr().out == ""
    assert driver.modes == []

"""Cross-reference provenance: the curated/TSK split comes from the r.curated flag.

XREF-3: the old split was coalesce(r.votes, 999) >= 999, so the three TSK
edges with 999+ community votes (jer:29:0-isa:55:0 1130, rom:8:1-eph:1:1 1268,
rom:8:1-jer:1:1 1143) were weighted as hand-curated. During the transition
the flag falls back to r.source for edges written before it existed; W2/1D
C14 drops that fallback.
"""

import asyncio
import re
from pathlib import Path

from database import neo4j_db, postgres
from utils.retrieval import cross_ref_retriever as xr

CURATED_XREF = "coalesce(r.curated, r.source IN ['markdown', 'supplementary'])"


async def _content(pid):
    return {"content": f"text of {pid}", "title": "t", "book_name": "b",
            "chapter_num": 1, "metadata": {"verse_range": "1-2"}}


def _multi_hop_returns(monkeypatch, rows):
    async def multi_hop(ids, max_hops=2, limit=30):
        return [dict(r) for r in rows]
    monkeypatch.setattr(neo4j_db, "get_cross_references_multi_hop", multi_hop)
    monkeypatch.setattr(postgres, "get_content_by_id", _content)


def _one_hop_returns(monkeypatch, rows):
    async def one_hop(pid, limit=10):
        return [dict(r) for r in rows]
    monkeypatch.setattr(neo4j_db, "get_cross_references", one_hop)
    monkeypatch.setattr(postgres, "get_content_by_id", _content)


# --- weights -----------------------------------------------------------------

def test_edge_weight_by_curated_flag():
    assert xr._edge_weight(1, True) == 0.75
    assert xr._edge_weight(1, False) == 0.60
    assert xr._edge_weight(2, True) == 0.55
    assert xr._edge_weight(2, False) == 0.50
    assert xr._edge_weight(5, True) == 0.30
    assert xr._edge_weight(5, False) == 0.30


def test_tsk_edge_with_votes_1268_not_curated_weighs_0_60(monkeypatch):
    row = {"id": "eph:1:1", "hop_distance": 1, "votes": 1268, "curated": False}
    _multi_hop_returns(monkeypatch, [row])
    _one_hop_returns(monkeypatch, [row])

    [expand] = asyncio.run(xr.retrieve_via_cross_references(["rom:8:1"]))
    [legacy] = asyncio.run(xr.retrieve_cross_references(["rom:8:1"]))

    for cand in (expand, legacy):  # high votes never stand in for the flag
        assert cand["weight"] == 0.60
        assert cand["curated"] is False
        assert cand["votes"] == 1268


def test_curated_edge_with_few_votes_weighs_0_75(monkeypatch):
    row = {"id": "jer:1:1", "hop_distance": 1, "votes": 5, "curated": True}
    _multi_hop_returns(monkeypatch, [row])
    _one_hop_returns(monkeypatch, [row])

    [expand] = asyncio.run(xr.retrieve_via_cross_references(["rom:8:1"]))
    [legacy] = asyncio.run(xr.retrieve_cross_references(["rom:8:1"]))

    for cand in (expand, legacy):
        assert cand["weight"] == 0.75
        assert cand["curated"] is True
        assert cand["votes"] == 5


def test_fallback_row_weight_uses_curated(monkeypatch):
    _multi_hop_returns(monkeypatch, [
        {"id": "gen:1:0", "hop_distance": 2, "curated": True},
        {"id": "exo:1:0", "hop_distance": 2, "curated": False},
    ])

    cands = asyncio.run(xr.retrieve_via_cross_references(["jer:29:0"]))

    assert [(c["id"], c["weight"], c["curated"]) for c in cands] == [
        ("gen:1:0", 0.55, True), ("exo:1:0", 0.50, False)]


# --- Cypher ------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    async def data(self):
        return [dict(r) for r in self._rows]


class _FakeSession:
    def __init__(self, driver):
        self._driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, query, **params):
        self._driver.calls.append((query, params))
        return _FakeResult(self._driver.replies.pop(0))


class _FakeDriver:
    """Records (query, params) per session.run and replies with canned rows."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def session(self, **kwargs):
        return _FakeSession(self)


def _order_by(query: str) -> str:
    clause = query[query.rindex("ORDER BY") + len("ORDER BY"):query.rindex("LIMIT")]
    return " ".join(clause.split())


def test_cypher_reads_the_curated_flag(monkeypatch):
    driver = _FakeDriver([
        [{"id": "isa:55:0", "curated": False, "votes": 1268}],
        # one row < limit forces the sparse fallback
        [{"id": "isa:55:0", "hop_distance": 1, "seed_support": 1, "curated": False, "votes": 1268}],
        [{"id": "jer:1:1", "hop_distance": 2, "curated": True}],
    ])
    monkeypatch.setattr(neo4j_db, "get_driver", lambda: driver)

    asyncio.run(neo4j_db.get_cross_references("jer:29:0", limit=10))
    rows = asyncio.run(neo4j_db.get_cross_references_multi_hop(["jer:29:0"], max_hops=2, limit=10))

    assert [r["id"] for r in rows] == ["isa:55:0", "jer:1:1"]
    queries = [q for q, _ in driver.calls]
    assert len(queries) == 3
    for q in queries:
        assert CURATED_XREF in q
        assert "coalesce(r.votes, 999)" not in q
    assert "(p:Pericope {id: $pericope_id})" in queries[0]
    assert [_order_by(q) for q in queries] == [
        "curated DESC, votes DESC, apoc.util.md5([target.id])",
        "seed_support DESC, curated DESC, votes DESC, apoc.util.md5([target.id])",
        "hop_distance ASC, curated DESC, apoc.util.md5([target.id])",
    ]
    assert driver.calls[2][1]["limit"] == 9


def test_no_sentinel_left():
    assert not hasattr(xr, "_CURATED_VOTES")
    source = Path(neo4j_db.__file__).read_text(encoding="utf-8")
    assert "999" not in source
    assert re.search(r"_CURATED_XREF = \(?\s*\"coalesce\(r\.curated, ", source)

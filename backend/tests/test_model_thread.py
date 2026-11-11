"""The models run off the event loop, so a question being ranked cannot time out another's Neo4j read.

Measured on staging with three questions at a time: the walk's 0.8 s ran out on 27 questions (a median of
8.4 s spent waiting, while Neo4j answers in 7 ms), and 54 more went without the graph behind those.
"""

import asyncio
import threading
import time

from router_fakes import cand as _c
from router_fakes import fake_dense as _dense
from utils import embedder, model_thread, reranker
from utils.retrieval import dense, router

BLOCK_S = 0.3
TICK_S = 0.01


async def _longest_stall_during(coroutine) -> tuple[object, float]:
    """(the coroutine's result, the longest the event loop went without running a tick)."""
    longest = 0.0

    async def ticks():
        nonlocal longest
        last = time.perf_counter()
        while True:
            await asyncio.sleep(TICK_S)
            now = time.perf_counter()
            longest, last = max(longest, now - last), now

    ticking = asyncio.create_task(ticks())
    await asyncio.sleep(0)
    result = await coroutine
    await asyncio.sleep(TICK_S * 2)     # a coroutine that never yielded: the tick after it sees the stall
    ticking.cancel()
    return result, longest


def test_ranking_leaves_the_event_loop_free(active, monkeypatch):
    _dense(monkeypatch, hits=[_c("ps:a.1.1")])

    def slow(query, passages, top_k=5, text_key="content"):
        time.sleep(BLOCK_S)
        return [{**p, "rerank_score": 0.5} for p in passages][:top_k]
    monkeypatch.setattr(reranker, "rerank", slow)

    (ranked, _), stall = asyncio.run(_longest_stall_during(router.retrieve_and_rerank(
        "平安是什麼", [])))

    assert [c["id"] for c in ranked] == ["ps:a.1.1"]
    assert stall < BLOCK_S / 2


def test_encoding_the_query_leaves_the_event_loop_free(monkeypatch):
    def slow(text):
        time.sleep(BLOCK_S)
        return [0.1, 0.2]

    async def fetch_sources(passage_ids, chunk_ids=()):
        return {}
    monkeypatch.setattr(embedder, "encode_query", slow)
    monkeypatch.setattr(dense.qdrant_db, "search", lambda vector, top_k=20, book_ids=None: [])
    monkeypatch.setattr(dense.postgres, "fetch_sources", fetch_sources)

    found, stall = asyncio.run(_longest_stall_during(dense.retrieve_dense("q", dense.ROUTE_ARM)))

    assert found == []
    assert stall < BLOCK_S / 2


def test_a_model_runs_one_call_at_a_time():
    """The fast tokenizer's padding state is not safe across threads ("Already borrowed")."""
    running, most = 0, 0
    guard = threading.Lock()

    def call():
        nonlocal running, most
        with guard:
            running += 1
            most = max(most, running)
        time.sleep(0.02)
        with guard:
            running -= 1

    async def together():
        await asyncio.gather(*(model_thread.run(call) for _ in range(5)))

    asyncio.run(together())
    assert most == 1


def test_a_failing_model_raises_at_the_caller():
    def broken():
        raise RuntimeError("cuda")

    async def call():
        try:
            await model_thread.run(broken)
        except RuntimeError as exc:
            return str(exc)
        return None

    assert asyncio.run(call()) == "cuda"

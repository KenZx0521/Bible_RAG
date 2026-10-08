"""Stand-ins shared by the router tests: candidates, a fake dense arm, one call of the router.

The ``active`` and ``scores`` fixtures that go with them live in conftest.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ragcommon import books, ids, routing
from ragcommon.tests.lexicon_doc import book, document, event, name
from utils.retrieval import event_registry as reg
from utils.retrieval import router, routes

BACKEND = Path(__file__).resolve().parents[1]
EVENT = reg.RegistryEvent("ev0002", ("event:baoluoxushuguizhudejingguo",), "掃羅的轉變",
                          ("保羅歸主",), ("ps:act.9.1", "ps:act.9.3b"))
BOOK_TERMS = [book(b.name, b.book_id, b.name)
              for b in sorted(books.all_books(), key=lambda b: (-len(b.name), b.ord))]


def lexicon_doc() -> dict:
    """A v2 lexicon: the 66 book names, a few names, the EVENT trigger.

    The route types are made up for the route tests (K4 decides the real ones).
    """
    names = [name("掃羅", "nm:5a0000000001", "Person"), name("巴拿巴", "nm:5a0000000002", "Person"),
             name("耶路撒冷", "nm:5a0000000003", "Place")]
    return document(names=names, events=[event("保羅歸主", EVENT.id, EVENT.name)],
                    books=BOOK_TERMS)


LEXICON = routing.parse_lexicon(lexicon_doc())


def cand(cid, strategy="hybrid_hybrid", weight=0.7, book="act", chapter=9, **extra) -> dict:
    """A pool candidate as the stores return it (start_key defaults to verse 1)."""
    return {"id": cid, "source_strategy": strategy, "weight": weight, "content": cid,
            "book_id": book, "book_name": book, "chapter_num": chapter, "title": "",
            "verse_range": "1", "kind": "passage", "passage_id": cid,
            "start_key": f"{book}.{chapter}.1", **extra}


def passage(key: str, strategy="hybrid_hybrid", weight=0.7, **extra) -> dict:
    """The passage starting at verse key ``key`` (``lev.1.10``, ``act.9.3b``)."""
    parsed = ids.validate(key, "key")
    return cand(ids.passage_id(key), strategy, weight, book=parsed.book_id,
                chapter=parsed.chapter, start_key=key, **extra)


def fake_dense(monkeypatch, hits_by_book=None, hits=()) -> list[tuple]:
    """Dense arm returning ``hits`` (or ``hits_by_book[book]`` when restricted); records calls."""
    calls = []

    async def fake(query, arm, top_k=None, book_ids=None):
        calls.append((arm.label, top_k, book_ids))
        found = (hits_by_book or {}).get(book_ids[0], []) if book_ids else list(hits)
        return [{**c, "source_strategy": arm.label} for c in found]

    monkeypatch.setattr(routes, "retrieve_dense", fake)
    monkeypatch.setattr(router, "retrieve_dense", fake)
    return calls


def no_supplement(monkeypatch) -> None:
    async def chapter_passages(book_id, chapter):
        return []
    monkeypatch.setattr(routes.postgres, "chapter_passages", chapter_passages)


def run(**kwargs) -> tuple[list[dict], dict]:
    defaults = {"verse_refs": [], "intent_type": "topic", "entity_names": []}
    return asyncio.run(router.retrieve_and_rerank(**{**defaults, **kwargs}))

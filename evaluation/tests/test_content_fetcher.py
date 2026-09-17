"""
content_fetcher: merged verse numbers ("29-30", 70 entries in the corpus)
used to crash int() during context rebuild; lookups now work on inclusive
spans, and the block rebuild degrades per source instead of failing a sample.
"""

import asyncio

import pytest

from src.content_fetcher import (
    _fetch_single_verse,
    _fetch_verse_range,
    _iter_chapter_verses,
    fetch_context_blocks,
    verse_span,
)
from src.models import SourceInfo


class StubPool:
    """asyncpg pool stand-in: one chapter's pericope rows + pericope/chunk tables."""

    def __init__(self, rows=None, pericopes=None, chunks=None, fail=False):
        self.rows = rows or []
        self.pericopes = pericopes or {}
        self.chunks = chunks or {}
        self.fail = fail

    async def fetch(self, sql, arg):
        if self.fail:
            raise RuntimeError("db down")
        return self.rows

    async def fetchrow(self, sql, arg):
        if self.fail:
            raise RuntimeError("db down")
        table = self.pericopes if "pericopes" in sql else self.chunks
        return {"content": table[arg]} if arg in table else None


CHAPTER = [
    {"verses": [{"num": "28", "text": "A"}, {"num": "29-30", "text": "B"}]},
    {"verses": [{"num": "31", "text": "C"}]},
]


def test_verse_span_single_and_int():
    assert verse_span("16") == (16, 16)
    assert verse_span(16) == (16, 16)


def test_verse_span_merged():
    assert verse_span("29-30") == (29, 30)


def test_verse_span_invalid():
    assert verse_span(None) is None
    assert verse_span("a") is None
    assert verse_span("29-b") is None
    assert verse_span("") is None


def test_iter_chapter_verses_keeps_label_and_span():
    rows = [
        {"verses": [{"num": "28", "text": "A"}, {"num": "29-30", "text": "B"}]},
        {"verses": '[{"verse": 31, "text": "C"}, {"num": "x", "text": "bad"}]'},
    ]
    assert _iter_chapter_verses(rows) == [("28", (28, 28), "A"), ("29-30", (29, 30), "B"), ("31", (31, 31), "C")]


def test_single_verse_inside_merged_span():
    pool = StubPool(rows=CHAPTER)
    assert asyncio.run(_fetch_single_verse(pool, "gen", 24, 30)) == "29-30. B"
    assert asyncio.run(_fetch_single_verse(pool, "gen", 24, 31)) == "31. C"
    assert asyncio.run(_fetch_single_verse(pool, "gen", 24, 99)) == ""


def test_verse_range_overlap_and_ordering():
    pool = StubPool(rows=CHAPTER)
    assert asyncio.run(_fetch_verse_range(pool, "gen", 24, 28, 29)) == "28. A\n29-30. B"
    assert asyncio.run(_fetch_verse_range(pool, "gen", 24, 30, 31)) == "29-30. B\n31. C"
    assert asyncio.run(_fetch_verse_range(pool, "gen", 24, 40, 41)) == ""


def _src(i, **kw):
    base = dict(id=f"gen:24:{i}", book="創世記", chapter=24, title="", verse_range="")
    base.update(kw)
    return SourceInfo(**base)


def test_fetch_context_blocks_numbers_by_position_and_skips_missing():
    pool = StubPool(pericopes={"gen:24:0": "P0"})
    blocks = asyncio.run(fetch_context_blocks(pool, [_src(0), _src(1)]))
    assert blocks == ["[1] 創世記 第24章\nP0"]


def test_fetch_context_blocks_falls_back_to_stored_text_when_db_fails():
    pool = StubPool(fail=True)
    blocks = asyncio.run(fetch_context_blocks(pool, [_src(0), _src(1)], stored_texts=["t0", "t1"]))
    assert blocks == ["[1] 創世記 第24章\nt0", "[2] 創世記 第24章\nt1"]


def test_fetch_context_blocks_ignores_misaligned_stored_text():
    pool = StubPool(fail=True)
    assert asyncio.run(fetch_context_blocks(pool, [_src(0), _src(1)], stored_texts=["only-one"])) == []


def test_fetch_context_blocks_verse_id_resolves_single_verse_not_pericope():
    # 3jn:1:2-style collision: verse_range == third segment -> verse lookup, never the pericope row
    pool = StubPool(rows=[{"verses": [{"num": "2", "text": "V2"}]}], pericopes={"3jn:1:2": "PERICOPE"})
    src = SourceInfo(id="3jn:1:2", book="約翰三書", chapter=1, title="問候", verse_range="2", strategy="verse_direct")
    assert asyncio.run(fetch_context_blocks(pool, [src])) == ["[1] 約翰三書 第1章 - 問候 (2節)\n2. V2"]

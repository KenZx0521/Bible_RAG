"""Chapter references and the chapter pin: a range is served by its first chapter.

The legacy parser read 「利未記1-7章」 as chapter 1, so R1 fetches and pins only
that chapter (design §0.2: one score-changing step at a time). The pin adds at
most ``top_k`` passages in the order the user wrote the chapters, picks each
chapter's first passages in canonical order, and leaves the other slots to the
reranker.
"""

import pytest

from router_fakes import cand, fake_dense, passage, run
from utils.retrieval import pins, routes
from utils.verse_parser import VerseRef, parse_verse_references

LEV_1 = [passage(k) for k in ("lev.1.1", "lev.1.3", "lev.1.10")]   # canonical order


@pytest.fixture
def chapters(monkeypatch):
    """chapter_passages over LEV_1 and one passage per other chapter; records each call."""
    asked = []

    async def chapter_passages(book_id, chapter):
        asked.append((book_id, chapter))
        if (book_id, chapter) == ("lev", 1):
            return [dict(c) for c in LEV_1]
        return [passage(f"{book_id}.{chapter}.1")]

    monkeypatch.setattr(routes.postgres, "chapter_passages", chapter_passages)
    return asked


def test_a_chapter_range_pins_its_first_chapter_and_the_reranker_orders_the_rest(
        active, scores, chapters, monkeypatch):
    dense = [passage(f"lev.{ch}.1", "semantic", 0.6) for ch in (2, 3, 4, 5, 7)]
    fake_dense(monkeypatch, hits=dense)
    scores.update({"ps:lev.2.1": 0.95, "ps:lev.3.1": 0.9, "ps:lev.4.1": 0.85,
                   "ps:lev.5.1": 0.8, "ps:lev.7.1": 0.5})
    scores.update({c["id"]: 0.1 for c in LEV_1})
    question = "利未記1-7章記載了哪五種祭？各有什麼特點？"

    ranked, stats = run(query=question, verse_refs=parse_verse_references(question), top_k=5)

    assert stats["route_used"] == "R2" and chapters == [("lev", 1)]
    assert [c["id"] for c in ranked] == ["ps:lev.1.1", "ps:lev.1.3",
                                         "ps:lev.2.1", "ps:lev.3.1", "ps:lev.4.1"]


def test_a_whole_book_range_fetches_one_chapter(active, scores, chapters, monkeypatch):
    fake_dense(monkeypatch, hits=[passage("psa.23.1", "semantic", 0.6)])
    question = "詩篇1-150篇的主題有哪些？"

    ranked, stats = run(query=question, verse_refs=parse_verse_references(question), top_k=5)

    assert chapters == [("psa", 1)]
    assert stats["total_candidates"] == 2 and len(ranked) == 2


def _others(n=5):
    return [cand(f"ps:rom.{i}.1", book="rom", chapter=i, rerank_score=0.5) for i in range(1, n + 1)]


def _chapter_pool(*books):
    return [passage(f"{b}.1.{v}", "sql_chapter", 0.9) for b in books for v in (1, 5, 12)]


def _pin(refs, pool, top_k=5):
    ranked = _others()
    return [c["id"] for c in pins.pin_chapter_candidates(ranked, ranked + pool, refs, top_k)]


def test_pins_follow_the_order_the_user_wrote_and_never_exceed_k():
    refs = [VerseRef(b, b, 1) for b in ("jhn", "gen", "mat", "act")]

    assert _pin(refs, _chapter_pool("act", "mat", "gen", "jhn"), top_k=3) == [
        "ps:jhn.1.1", "ps:jhn.1.5", "ps:gen.1.1"]


def test_pins_take_the_chapter_s_first_passages_in_canonical_order():
    pool = [passage(k, "sql_chapter", 0.9) for k in ("lev.1.10", "lev.1.3b", "lev.1.1")]

    assert _pin([VerseRef("lev", "利未記", 1)], pool)[:2] == ["ps:lev.1.1", "ps:lev.1.3b"]


def test_only_strong_candidates_of_the_chapter_are_pinned():
    weak = passage("lev.1.1", "semantic", 0.6)
    strong = passage("lev.1.5", "sql_chapter", 0.85)
    refs = [VerseRef("lev", "利未記", 1)]

    assert _pin(refs, [weak, strong])[:2] == ["ps:lev.1.5", "ps:rom.1.1"]
    assert _pin(refs, [weak]) == [c["id"] for c in _others()]


def test_verse_references_pin_nothing():
    refs = [VerseRef("lev", "利未記", 1, 3, 3)]

    assert _pin(refs, _chapter_pool("lev")) == [c["id"] for c in _others()]

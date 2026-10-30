"""R2/R5 chapter scope (B-lite): a named chapter served whole as one block, on fake stores.

A chapter range of at most three chapters, or a named chapter the top-k misses
passages of, becomes one block per chapter ahead of the ranked rest; anything
else, R1 (which reads chapter references too) and semantic_only keep exactly the
top-k they had (compared with the step switched off).
"""

import pytest

from database import content
from ragcommon import ids
from router_fakes import cand, fake_dense, passage, run
from routers import query
from utils.generator import build_context_blocks
from utils.retrieval import chapter_blocks, router, routes, verse_retriever
from utils.verse_parser import VerseRef, parse_verse_references

NAMES = {"rev": "啟示錄", "rom": "羅馬書", "mat": "馬太福音", "dan": "但以理書", "jhn": "約翰福音",
         "gen": "創世記", "act": "使徒行傳", "gal": "加拉太書", "1co": "哥林多前書"}


def _ps(start: str, end: str, title: str = "", text: str | None = None) -> dict:
    """A passage as postgres.chapter_passages returns it."""
    p = ids.validate(start, "key")
    return {"id": ids.passage_id(start), "kind": "passage", "content": text or f"text {start}",
            "title": title, "book_id": p.book_id, "book_name": NAMES[p.book_id],
            "chapter_num": p.chapter, "verse_range": "", "start_key": start, "end_key": end,
            "passage_id": ids.passage_id(start), "split_passage_ids": []}


CHAPTERS = {
    ("rev", 2): [_ps("rev.2.1", "rev.2.7", "給以弗所教會的信"), _ps("rev.2.8", "rev.2.11"),
                 _ps("rev.2.12", "rev.2.17"), _ps("rev.2.18", "rev.2.29")],
    ("rev", 3): [_ps("rev.3.1", "rev.3.6"), _ps("rev.3.7", "rev.3.13"),
                 _ps("rev.3.14", "rev.3.22")],
    ("rom", 8): [_ps("rom.8.1", "rom.8.17"), _ps("rom.8.18", "rom.8.30"),
                 _ps("rom.8.31", "rom.8.39")],
    ("mat", 6): [_ps("mat.6.1", "mat.6.4"), _ps("mat.6.5", "mat.6.34")],
    ("jhn", 1): [_ps("jhn.1.1", "jhn.1.18"), _ps("jhn.1.19", "jhn.1.28"),
                 _ps("jhn.1.29", "jhn.1.51")],
    ("gen", 1): [_ps("gen.1.1", "gen.1.31")],
    ("act", 9): [_ps("act.9.1", "act.9.3"), _ps("act.9.3b", "act.9.9"),
                 _ps("act.9.10", "act.9.43")],
    ("gal", 1): [_ps("gal.1.1", "gal.1.24")],
    **{("dan", ch): [_ps(f"dan.{ch}.1", f"dan.{ch}.9")] for ch in range(1, 5)},
}


@pytest.fixture
def pg(monkeypatch):
    """chapter_passages over CHAPTERS (``table`` may be edited first); records each call."""
    state = {"asked": [], "table": dict(CHAPTERS)}

    async def chapter_passages(book_id, chapter):
        state["asked"].append((book_id, chapter))
        return [dict(p) for p in state["table"].get((book_id, chapter), [])]
    monkeypatch.setattr(routes.postgres, "chapter_passages", chapter_passages)
    return state


def _others(n: int, book: str = "rom", score: float = 0.9) -> tuple[list[dict], dict]:
    hits = [cand(f"ps:{book}.{i}.1", book=book, chapter=i, start_key=f"{book}.{i}.1",
                 end_key=f"{book}.{i}.5") for i in range(1, n + 1)]
    return hits, {c["id"]: score - 0.01 * i for i, c in enumerate(hits)}


def _ids(ranked: list[dict]) -> list[str]:
    return [c["id"] for c in ranked]


def _without_blocks(monkeypatch, **kwargs) -> list[str]:
    """The same request with the chapter-block step switched off."""
    with monkeypatch.context() as m:
        m.setattr(router, "_CHAPTER_BLOCK_ROUTES", ())
        ranked, _ = run(**kwargs)
    return _ids(ranked)


def _ask(question: str, **extra) -> dict:
    return {"query": question, "verse_refs": parse_verse_references(question), **extra}


# --- the block ------------------------------------------------------------------------------

def test_a_block_is_the_chapter_under_its_own_kind_and_id():
    found = [_ps("1co.12.1", "1co.12.11", "屬靈的恩賜", "**1** 弟兄們"),
             _ps("1co.12.12", "1co.12.31", "一個身體有許多肢體", "**12** 就如身子"),
             _ps("1co.12.31b", "1co.12.31b", "愛", "**31** 我現在把最妙的道指示你們。")]

    b = chapter_blocks.block(found)

    assert (b["id"], b["kind"], ids.parse(b["id"]).kind) == ("1co.12", "chapter", "chapter")
    assert (b["start_key"], b["end_key"], b["verse_range"]) == ("1co.12.1", "1co.12.31b", "1-31")
    assert b["member_ids"] == ["ps:1co.12.1", "ps:1co.12.12", "ps:1co.12.31b"]
    assert b["content"] == ("【屬靈的恩賜】\n**1** 弟兄們\n\n【一個身體有許多肢體】\n**12** 就如身子"
                            "\n\n【愛】\n**31** 我現在把最妙的道指示你們。")
    assert b["source_strategy"] == "chapter_block" and b["passage_id"] is None
    with pytest.raises(ids.IdError):  # why the block is no vr: record
        ids.verse_range_id(b["start_key"], b["end_key"])


def test_the_block_header_names_the_chapter_and_the_span_it_covers():
    b = chapter_blocks.block(CHAPTERS[("rev", 2)])

    assert build_context_blocks([b])[0].startswith(
        "[1] 啟示錄 第2章 (1-29節)\n【給以弗所教會的信】\ntext rev.2.1\n\ntext rev.2.8\n\n")


def test_a_one_verse_chapter_spans_that_verse():
    assert chapter_blocks.block([_ps("gen.1.1", "gen.1.1")])["verse_range"] == "1"


def test_a_chapter_over_the_character_cap_is_no_block():
    fits = [_ps("rom.8.1", "rom.8.39", text="字" * chapter_blocks.MAX_CHARS)]
    over = [_ps("rom.9.1", "rom.9.33", text="字" * (chapter_blocks.MAX_CHARS + 1))]

    blocks, too_long = chapter_blocks.plan({("rom", 8): fits, ("rom", 9): over, ("rom", 10): []})

    assert _ids(blocks) == ["rom.8"] and too_long == [("rom", 9)]


@pytest.mark.parametrize("refs, chapters", [
    ([VerseRef("rev", "啟示錄", 2, chapter_end=3)], [("rev", 2), ("rev", 3)]),
    ([VerseRef("amo", "阿摩司書", 7, chapter_end=9)], [("amo", 7), ("amo", 8), ("amo", 9)]),
    ([VerseRef("lev", "利未記", 1, chapter_end=7)], []),
    ([VerseRef("jhn", "約翰福音", 3, 16, 16), VerseRef("rom", "羅馬書", 8)], [("rom", 8)]),
    ([VerseRef("rom", "羅馬書", c) for c in range(1, 8)], [("rom", c) for c in range(1, 6)]),
])
def test_the_scope_is_every_chapter_of_ranges_up_to_three_at_most_k(refs, chapters):
    assert chapter_blocks.scoped_chapters(refs, k=5) == chapters


def test_a_block_and_its_members_reach_the_api_source():
    b = chapter_blocks.block(CHAPTERS[("rev", 3)])

    source = query._source(b, None, "b20261008_1bb6912e")

    assert (source.id, source.kind, source.verse_range) == ("rev.3", "chapter", "1-22")
    assert source.member_ids == ["ps:rev.3.1", "ps:rev.3.7", "ps:rev.3.14"]
    assert source.score is None and source.strategy == "chapter_block"


# --- R2 ---------------------------------------------------------------------------------------

def test_a_chapter_range_becomes_one_block_per_chapter_ahead_of_the_ranked_rest(
        active, scores, pg, monkeypatch):
    others, table = _others(6)
    fake_dense(monkeypatch, hits=[*others, passage("rev.2.8", "semantic", 0.6)])
    scores.update({**table, "ps:rev.2.8": 0.99})
    question = "啟示錄第2-3章中，七個教會分別得到什麼稱讚或責備？"

    ranked, stats = run(**_ask(question, top_k=5))

    assert stats["route_used"] == "R2"
    assert _ids(ranked) == ["rev.2", "rev.3", "ps:rom.1.1", "ps:rom.2.1", "ps:rom.3.1"]
    assert ranked[0]["member_ids"] == [p["id"] for p in CHAPTERS[("rev", 2)]]
    assert "rerank_score" not in ranked[0] and "fused_score" not in ranked[0]
    assert stats["strategies_used"] == ["sql_chapter", "semantic", "chapter_block"]
    assert stats["reranked_top_k"] == 5
    assert pg["asked"] == [("rev", 2), ("rev", 2), ("rev", 3)]  # the route's lookup, then ours


def test_a_named_chapter_the_top_k_misses_passages_of_becomes_a_block(active, scores, pg,
                                                                      monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    question = "根據羅馬書第8章，保羅如何描述信徒在患難中仍有盼望的原因？"
    before = _without_blocks(monkeypatch, **_ask(question, top_k=3))

    ranked, stats = run(**_ask(question, top_k=3))

    assert before == ["ps:rom.8.1", "ps:rom.8.18", "ps:rom.1.1"]  # the pin's two of three
    assert _ids(ranked) == ["rom.8", "ps:rom.1.1", "ps:rom.2.1"]
    assert stats["strategies_used"][-1] == "chapter_block"


def test_a_named_chapter_already_whole_in_the_top_k_changes_nothing(active, scores, pg,
                                                                   monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    question = "根據馬太福音第6章，耶穌如何教導正確的敬虔生活？"

    ranked, stats = run(**_ask(question, top_k=5))

    assert _ids(ranked) == _without_blocks(monkeypatch, **_ask(question, top_k=5))
    assert {"ps:mat.6.1", "ps:mat.6.5"} <= set(_ids(ranked))
    assert "chapter_block" not in stats["strategies_used"] and stats["strategy_errors"] == {}


@pytest.mark.parametrize("question, blocked", [
    ("但以理書1-3章記載了什麼？", True),
    ("但以理書1-4章記載了什麼？", False),
])
def test_a_range_over_three_chapters_keeps_the_old_top_k(active, scores, pg, monkeypatch,
                                                          question, blocked):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)

    ranked, _ = run(**_ask(question, top_k=5))

    if blocked:
        assert _ids(ranked)[:3] == ["dan.1", "dan.2", "dan.3"]
    else:
        assert _ids(ranked) == _without_blocks(monkeypatch, **_ask(question, top_k=5))
        assert pg["asked"] == [("dan", 1)] * 2  # the route's lookup only, in both runs
        assert all(c["kind"] != "chapter" for c in ranked)


def test_a_chapter_too_long_for_a_block_competes_as_sql_chapter_and_is_pinned(
        active, scores, pg, monkeypatch):
    long = [_ps(f"rom.2.{v}", f"rom.2.{v + 9}", text="字" * 1500) for v in (1, 11, 21)]
    pg["table"].update({("rom", 1): [_ps("rom.1.1", "rom.1.32")], ("rom", 2): long})
    others, table = _others(6, book="heb")
    fake_dense(monkeypatch, hits=others)
    scores.update(table)

    ranked, _ = run(**_ask("羅馬書1-2章如何論證世人都伏在罪的權下？", top_k=5))

    assert _ids(ranked) == ["rom.1", "ps:rom.2.1", "ps:rom.2.11", "ps:heb.1.1", "ps:heb.2.1"]
    assert {(c["source_strategy"], c["weight"]) for c in ranked[1:3]} == {("sql_chapter", 1.0)}


def test_a_too_long_chapter_held_only_by_dense_is_raised_to_sql_chapter_and_pinned(
        active, scores, pg, monkeypatch):
    long = [_ps(f"rom.2.{v}", f"rom.2.{v + 9}", text="字" * 1500) for v in (1, 11, 21)]
    pg["table"].update({("rom", 1): [_ps("rom.1.1", "rom.1.32")], ("rom", 2): long})
    others, table = _others(6, book="heb")
    dense_copies = [passage(p["start_key"], "semantic", 0.6) for p in long]
    fake_dense(monkeypatch, hits=[*others, *dense_copies])
    scores.update({**table, **{c["id"]: 0.1 for c in dense_copies}})

    ranked, _ = run(**_ask("羅馬書1-2章如何論證世人都伏在罪的權下？", top_k=5))

    rom2 = [c for c in ranked if c.get("chapter_num") == 2 and c["book_id"] == "rom"]
    assert _ids(ranked)[0] == "rom.1" and len(rom2) == 2
    assert all(c["weight"] == 1.0 and c["source_strategy"] == "sql_chapter" and
               len(c["found_by"]) == 2 and c["found_by"][-1] == "sql_chapter" for c in rom2)


def test_a_range_whose_chapters_are_all_too_long_still_pins_each_chapter(active, scores, pg,
                                                                        monkeypatch):
    pg["table"].update({("rom", ch): [_ps(f"rom.{ch}.{v}", f"rom.{ch}.{v + 9}", text="字" * 1500)
                                      for v in (1, 11, 21)] for ch in (1, 2)})
    others, table = _others(6, book="heb")
    fake_dense(monkeypatch, hits=others)
    scores.update(table)

    ranked, stats = run(**_ask("羅馬書1-2章如何論證世人都伏在罪的權下？", top_k=5))

    chapters = [c["chapter_num"] for c in ranked if c["book_id"] == "rom"]
    assert sorted(chapters) == [1, 1, 2, 2] and all(c["kind"] != "chapter" for c in ranked)
    assert stats["strategies_used"][-1] == "chapter_block"


def test_a_failed_chapter_lookup_is_recorded_and_the_top_k_stays(active, scores, pg,
                                                                  monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    question = "啟示錄第2-3章中，七個教會分別得到什麼稱讚或責備？"
    before = _without_blocks(monkeypatch, **_ask(question, top_k=5))
    lookup = routes.postgres.chapter_passages

    async def flaky(book_id, chapter):
        if (book_id, chapter) == ("rev", 3):
            raise ConnectionError("pg down")
        return await lookup(book_id, chapter)
    monkeypatch.setattr(routes.postgres, "chapter_passages", flaky)

    ranked, stats = run(**_ask(question, top_k=5))

    assert _ids(ranked) == before and "pg down" in stats["strategy_errors"]["chapter_block"]


# --- R5 ---------------------------------------------------------------------------------------

def test_blocks_count_as_present_books_for_the_multi_book_anchor_gate(active, scores, pg,
                                                                       monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others,
               hits_by_book={"jhn": [passage("jhn.3.1", weight=0.6)],
                             "gen": [passage("gen.3.1", weight=0.6)]})
    scores.update({**table, "ps:jhn.3.1": 0.0, "ps:gen.3.1": 0.0})
    question = "約翰福音1章如何呼應創世記1章的創造敘事？"

    ranked, stats = run(**_ask(question, top_k=5))

    assert stats["route_used"] == "R5"
    assert _ids(ranked) == ["jhn.1", "gen.1", "ps:rom.1.1", "ps:rom.2.1", "ps:rom.3.1"]


def test_the_event_lane_counts_a_block_s_members_as_covered(active, scores, pg, monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    fetched = []

    async def anchor(record_id):
        fetched.append(record_id)
        return cand(record_id, "x", 0.0)
    monkeypatch.setattr(router.postgres, "get_content_by_id", anchor)
    question = "使徒行傳9章和加拉太書1章記載保羅歸主的經過有何不同？"

    ranked, stats = run(**_ask(question, top_k=5))

    assert stats["route_used"] == "R5" and stats["event_registry_events"] == ["ev0002"]
    assert _ids(ranked)[:2] == ["act.9", "gal.1"] and len(ranked) == 5
    assert fetched == []  # ps:act.9.1 and ps:act.9.3b are both members of act.9


# --- untouched paths --------------------------------------------------------------------------

UNITS = {"jhn.3.16": content.VersePiece("jhn.3.16", "16", 16, 16, "present", "神愛世人")}
OWNER = _ps("jhn.3.16", "jhn.3.21", "神愛世人")


@pytest.fixture
def verse_pg(pg, monkeypatch):
    """The verse lookup's own SQL for 約翰福音3:16 (chapter lookups go through ``pg``)."""
    p = verse_retriever.postgres

    async def verse_slots(slots):
        return [UNITS[s] for s in slots]

    async def owner_passages(units):
        return {u: {"passage_id": OWNER["id"], "split_passage_ids": []} for u in units}

    async def fetch_sources(passage_ids, chunk_ids=()):
        return {pid: dict(OWNER) for pid in passage_ids}

    async def book_name(book_id):
        return NAMES[book_id]

    for name, fn in (("verse_slots", verse_slots), ("owner_passages", owner_passages),
                     ("fetch_sources", fetch_sources), ("book_name", book_name)):
        monkeypatch.setattr(p, name, fn)
    pg["table"][("rom", 1)] = [_ps("rom.1.1", "rom.1.17"), _ps("rom.1.18", "rom.1.32")]
    pg["table"][("rom", 2)] = [_ps("rom.2.1", "rom.2.29")]
    return pg


def test_an_r1_question_that_also_names_a_chapter_range_keeps_r1_s_lookup(
        active, scores, verse_pg, monkeypatch):
    others, table = _others(5, book="heb")
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    question = "約翰福音3:16和羅馬書1-2章怎麼說神的愛？"
    before = _without_blocks(monkeypatch, **_ask(question, top_k=5))
    verse_pg["asked"].clear()

    ranked, stats = run(**_ask(question, top_k=5))

    assert stats["route_used"] == "R1"
    assert _ids(ranked) == before == ["vs:jhn.3.16", "ps:rom.1.1", "ps:rom.1.18", "ps:jhn.3.16",
                                      "ps:heb.1.1"]
    assert verse_pg["asked"] == [("rom", 1)]  # the verse lookup's first chapter, nothing more
    assert "chapter_block" not in stats["strategies_used"]


def test_semantic_only_never_looks_at_chapters(active, scores, pg, monkeypatch):
    others, table = _others(5)
    fake_dense(monkeypatch, hits=others)
    scores.update(table)
    question = "啟示錄第2-3章中，七個教會分別得到什麼稱讚或責備？"

    ranked, stats = run(**_ask(question, top_k=5, semantic_only=True))

    assert stats["route_used"] == "semantic_only" and pg["asked"] == []
    assert _ids(ranked) == [c["id"] for c in others]


def test_the_pin_keeps_serving_first_chapters_left_unblocked_and_chapters_too_long():
    refs = [VerseRef("lev", "利未記", 1, chapter_end=7), VerseRef("rom", "羅馬書", 1, chapter_end=3)]

    assert chapter_blocks.pin_targets(refs, blocked={("rom", 1), ("rom", 3)},
                                      too_long=[("rom", 2)]) == [("lev", 1), ("rom", 2)]

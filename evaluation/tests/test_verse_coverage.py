"""Verse-level coverage metric tests.

Ground anchors used here are corpus facts verified against
output/chapters.jsonl: 創世記 1 章 = 31 節, 馬太福音 5-7 章 = 111 節.
"""

from src.models import SourceInfo
from src.reference_parser import parse_reference
from src.verse_coverage import (
    _chapter_table,
    expand_refs_to_anchors,
    expand_refs_to_verses,
    expand_source_to_verses,
    verse_level_metrics,
)


def _src(book: str, chapter: int, verse_range: str, sid: str = "x") -> SourceInfo:
    return SourceInfo(id=sid, book=book, chapter=chapter, verse_range=verse_range)


# ---------- chapter table ----------

def test_chapter_table_loads_corpus():
    table = _chapter_table()

    assert table["gen"][1] == 31
    assert len(table) == 66


# ---------- GT reference expansion ----------

def test_expand_single_verse():
    verses = expand_refs_to_verses(parse_reference("約翰福音 3:16"))

    assert verses == {("jhn", 3, 16)}


def test_expand_chapter_range_matches_known_verse_count():
    """馬太福音 5-7 章 = 111 verses (EVENT_011 的分母)."""
    verses = expand_refs_to_verses(parse_reference("馬太福音 5-7章"))

    assert len(verses) == 111


def test_expand_whole_book_uses_all_chapters():
    verses = expand_refs_to_verses(parse_reference("約拿書"))
    table = _chapter_table()["jon"]

    assert len(verses) == sum(table.values())
    assert {ch for (_, ch, _) in verses} == set(table)


def test_expand_cross_chapter_range():
    """約拿書 1:17-2:10 → ch1 v17..end + ch2 v1-10."""
    verses = expand_refs_to_verses(parse_reference("約拿書 1:17-2:10"))
    ch1_total = _chapter_table()["jon"][1]

    expected = {("jon", 1, v) for v in range(17, ch1_total + 1)}
    expected |= {("jon", 2, v) for v in range(1, 11)}
    assert verses == expected


def test_expand_clamps_out_of_range_verses():
    # 創世記 1 章只有 31 節;50 節的 spec 需被夾住而非產生幽靈經節
    verses = expand_refs_to_verses(parse_reference("創世記 1:28-50"))

    assert verses == {("gen", 1, v) for v in range(28, 32)}


# ---------- anchor expansion ----------

def test_anchors_one_per_chapter_in_range():
    anchors = expand_refs_to_anchors(parse_reference("馬太福音 5-7章"))

    assert len(anchors) == 3
    assert [a[1] for a in anchors] == [5, 6, 7]


def test_anchors_multi_book():
    anchors = expand_refs_to_anchors(parse_reference("創世記 1章; 出埃及記 2章"))

    assert len(anchors) == 2
    assert {(a[0], a[1]) for a in anchors} == {("gen", 1), ("exo", 2)}


# ---------- source expansion ----------

def test_source_verse_range_forms():
    assert expand_source_to_verses(_src("約翰福音", 3, "16")) == {("jhn", 3, 16)}
    assert expand_source_to_verses(_src("約翰福音", 3, "1-3")) == {
        ("jhn", 3, 1), ("jhn", 3, 2), ("jhn", 3, 3)
    }


def test_source_empty_verse_range_is_whole_chapter():
    verses = expand_source_to_verses(_src("創世記", 1, ""))

    assert len(verses) == 31


def test_source_unknown_book_or_chapter_is_empty():
    assert expand_source_to_verses(_src("不存在的書", 1, "1-3")) == set()
    assert expand_source_to_verses(
        SourceInfo(id="x", book="創世記", chapter=None, verse_range="1-3")
    ) == set()


# ---------- end-to-end metric ----------

def test_perfect_single_verse_hit():
    refs = parse_reference("約翰福音 3:16")
    sources = [_src("約翰福音", 3, "16")]

    verse_recall, anchor_cov = verse_level_metrics(refs, sources)

    assert (verse_recall, anchor_cov) == (1.0, 1.0)


def test_event_011_shape_chapter_range_inflation_fixed():
    """登山寶訓題型:GT 要 111 節,只撈到 6 節 → verse_recall ≈ 0.054,
    unit-level recall 給 1.0 的灌水在這裡不再發生。"""
    refs = parse_reference("馬太福音 5-7章")
    sources = [_src("馬太福音", 5, "1-2"), _src("馬太福音", 5, "13-16")]

    verse_recall, anchor_cov = verse_level_metrics(refs, sources)

    assert abs(verse_recall - 6 / 111) < 1e-4
    assert abs(anchor_cov - 1 / 3) < 1e-4  # 只中第 5 章這個 anchor(回傳值四捨五入到小數 4 位)


def test_irrelevant_sources_score_zero():
    refs = parse_reference("約翰福音 3:16")
    sources = [_src("創世記", 1, "1-5")]

    assert verse_level_metrics(refs, sources) == (0.0, 0.0)


def test_empty_refs_score_zero():
    assert verse_level_metrics([], [_src("創世記", 1, "1-5")]) == (0.0, 0.0)


def test_multi_anchor_partial_coverage():
    refs = parse_reference("創世記 1章; 出埃及記 2章")
    sources = [_src("創世記", 1, "")]  # 只覆蓋第一個 anchor

    verse_recall, anchor_cov = verse_level_metrics(refs, sources)

    assert anchor_cov == 0.5
    gen1 = _chapter_table()["gen"][1]
    exo2 = _chapter_table()["exo"][2]
    assert abs(verse_recall - gen1 / (gen1 + exo2)) < 1e-4

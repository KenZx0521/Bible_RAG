"""question_refs reads the looser wording of a question without reading more numbers as verses."""

import json
import time

import pytest

from test_verse_parser import LEGACY, LEGACY_MISSED, _retrieval_view
from utils.question_refs import find_verse_references
from utils.verse_parser import VerseRef

# The one GT question worded so that utils.verse_parser loses a reference at 「與」.
SECOND_REFERENCE_READ = {
    "詩篇32篇與51篇如何描寫認罪與赦免的經歷？": [("psa", 51, None, None)],
}


def _view(text):
    return [(r.book_id, r.chapter, r.verse_start, r.verse_end, r.chapter_end)
            for r in find_verse_references(text).refs]


@pytest.mark.parametrize("text", [
    "《約翰福音》3:16說了什麼？", "「約翰福音」3章16節說了什麼？", "約翰福音的3:16說了什麼？",
    "約翰福音中第3章第16節說了什麼？", "約翰福音裡三章十六節說了什麼？", "約翰福音第三章的十六節說了什麼？",
    "約翰福音3.16說了什麼？", "《約翰福音》的3.16說了什麼？"])
def test_natural_wording_around_a_verse_reference_is_read(text):
    assert _view(text) == [("jhn", 3, 16, 16, None)]


@pytest.mark.parametrize("text, expected", [
    ("路加福音的第15章", [("luk", 15, None, None, None)]),
    ("路加福音中第15章的比喻", [("luk", 15, None, None, None)]),
    ("《羅馬書》八章講什麼？", [("rom", 8, None, None, None)]),
    ("在羅馬書裡第8章講什麼？", [("rom", 8, None, None, None)]),
    ("詩篇的第23篇說了什麼？", [("psa", 23, None, None, None)]),
    ("《詩篇》23篇說了什麼？", [("psa", 23, None, None, None)]),
    ("馬太福音的5-7章有哪些教導？", [("mat", 5, None, None, 7)]),
    ("哥林多前書的13:4-7怎樣描寫愛？", [("1co", 13, 4, 7, None)]),
    ("創世紀1:1說了什麼？", [("gen", 1, 1, 1, None)]),
])
def test_natural_wording_around_chapters_and_ranges_is_read(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("約翰福音3章和5章", [("jhn", 3, None, None, None), ("jhn", 5, None, None, None)]),
    ("羅馬書8章與9章", [("rom", 8, None, None, None), ("rom", 9, None, None, None)]),
    ("創世記第1章和第2章的記載", [("gen", 1, None, None, None), ("gen", 2, None, None, None)]),
    ("約翰福音3:16和4:14", [("jhn", 3, 16, 16, None), ("jhn", 4, 14, 14, None)]),
    ("馬太福音5章與約翰福音3:16的關係", [("mat", 5, None, None, None), ("jhn", 3, 16, 16, None)]),
])
def test_and_between_references_keeps_every_reference(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("出埃及記20章十誡的內容是什麼？", [("exo", 20, None, None, None)]),
    ("馬太福音5章八福是什麼？", [("mat", 5, None, None, None)]),
])
def test_a_chinese_numeral_after_a_chapter_that_is_no_verse_keeps_the_chapter(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text", [
    "馬太福音12門徒有誰？", "出埃及記10災是什麼？", "啟示錄7封信的對象", "約翰福音7大神蹟",
    "羅馬書中3個人", "約翰福音的3天", "創世記中第1天", "馬太福音的5大講論", "羅馬書和3個門徒",
    "三章和五章的差別", "耶穌在曠野40天，約3天後"])
def test_numbers_that_count_things_are_not_references(text):
    assert _view(text) == []


@pytest.mark.parametrize("text, expected", [
    ("馬太福音28:19大使命是什麼？", [("mat", 28, 19, 19, None)]),
    ("羅馬書1:16 福音的大能", [("rom", 1, 16, 16, None)]),
    ("創世記1:26樣式是什麼意思？", [("gen", 1, 26, 26, None)]),
    ("馬太福音5:3-12福份有哪些", [("mat", 5, 3, 12, None)]),
    ("馬太福音5-7大綱", [("mat", 5, None, None, 7)]),
    ("詩篇23大衛的信心", [("psa", 23, None, None, None)]),
    ("羅馬書8福音的核心", [("rom", 8, None, None, None)]),
])
def test_a_word_that_merely_starts_like_a_count_keeps_the_reference(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("出埃及記20章10誡的內容是什麼？", [("exo", 20, None, None, None)]),
    ("馬太福音10章12門徒的名單", [("mat", 10, None, None, None)]),
    ("哥林多前書12章9種恩賜", [("1co", 12, None, None, None)]),
])
def test_a_count_after_a_chapter_keeps_the_chapter(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text", [
    "詩篇中七篇悔罪詩是哪些？", "詩篇的十五篇上行之詩是什麼？", "哥林多前書中兩章談到復活嗎？", "猶大書的一節經文提到以諾"])
def test_a_chinese_numeral_after_of_or_in_that_counts_is_no_reference(text):
    assert _view(text) == []


@pytest.mark.parametrize("text, expected", [
    ("羅馬書8章的一節經文說萬事互相效力", [("rom", 8, None, None, None)]),
    ("約翰福音3章的兩節經文最常被引用", [("jhn", 3, None, None, None)]),
    ("馬太福音5章的八節經文都是八福嗎", [("mat", 5, None, None, None)]),
    ("羅馬書8章的28節", [("rom", 8, 28, 28, None)]),
])
def test_verses_counted_after_a_chapter_keep_the_chapter(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("詩篇23篇和一篇感恩詩有什麼不同？", [("psa", 23, None, None, None)]),
    ("羅馬書8章與一節經文對比", [("rom", 8, None, None, None)]),
])
def test_and_before_a_count_adds_no_reference(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("羅馬書8章和17章", [("rom", 8, None, None, None)]),
    ("約翰福音3:16與3:40", [("jhn", 3, 16, 16, None)]),
])
def test_a_second_reference_that_does_not_exist_keeps_the_first(text, expected):
    assert _view(text) == expected


@pytest.mark.parametrize("text", [
    "讀完創世記2.5小時夠嗎？", "創世記2.5億年", "馬太福音1.2版本的差異", "約翰福音2.0版本"])
def test_a_decimal_after_a_book_is_no_reference(text):
    assert _view(text) == []


@pytest.mark.parametrize("text", [
    "約翰福音" + "1, " * 200 + "x", "約翰福音" + "1 - " * 200 + "x", "約翰福音3章和" + "1, " * 200 + "x",
    "約翰福音" + " " * 3000 + "x", "約翰福音" + "第 " * 500 + "x"])
def test_long_lists_are_read_in_linear_time(text):
    start = time.perf_counter()

    find_verse_references(text)

    assert time.perf_counter() - start < 0.5


def test_a_rejected_reference_reports_the_words_of_the_question():
    found = find_verse_references("《約翰福音》3:99說什麼？")

    assert found.refs == ()
    assert [r.raw for r in found.rejected] == ["約翰福音》3:99"]


def test_every_gt_question_reads_as_the_legacy_fixture_but_for_the_listed_one():
    rows = json.loads(LEGACY.read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 500

    for row in rows:
        legacy = [_retrieval_view(VerseRef(r[0], "", *r[1:])) for r in row["refs"]]
        expected = LEGACY_MISSED.get(row["text"], legacy) + SECOND_REFERENCE_READ.get(row["text"], [])
        assert [_retrieval_view(r) for r in find_verse_references(row["text"]).refs] == expected, row["text"]

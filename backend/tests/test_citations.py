"""Block numbers written as chapter numbers (utils.citations, rewrite 2-C) and the byte-token merge."""

import pytest

from utils.citations import fix_block_chapters
from utils.llm.ollama_client import merge_byte_tokens


def _src(book_id, name, chapter, verses):
    return {"book_id": book_id, "book_name": name, "chapter_num": chapter, "verse_range": verses}


# block [3] is John 14; John 3 is no chapter of the passages
SOURCES = [_src("rom", "羅馬書", 5, "1-11"), _src("jhn", "約翰福音", 1, "1-18"),
           _src("jhn", "約翰福音", 14, "15-21")]


@pytest.mark.parametrize("answer, fixed", [
    ("耶穌說：「你們若愛我」（約翰福音 3:16）。", "耶穌說：「你們若愛我」（約翰福音 14:16）。"),
    ("見約翰福音第3章第17節。", "見約翰福音第14章第17節。"),
    ("見約 3:15。", "見約 14:15。"),
    ("約翰福音說……[3:18]", "約翰福音說……[14:18]"),
    ("[3:20] 這是應許。", "[14:20] 這是應許。"),
    ("見羅馬書第5章第3節，與約翰福音 2:3。", "見羅馬書第5章第3節，與約翰福音 1:3。"),
])
def test_a_block_number_cited_as_the_chapter_gets_the_block_s_chapter(answer, fixed):
    assert fix_block_chapters(answer, SOURCES) == fixed


@pytest.mark.parametrize("answer", [
    "太初有道（約翰福音 1:1）。",            # a chapter of the passages
    "見約翰福音 3:30。",                     # verse 30 is not in block 3 (15-21)
    "見約翰福音第3章。",                     # no verse to check
    "見羅馬書 3:16。",                       # block 3 is another book
    "羅馬書說……[3:18]",                      # a bare citation after another book
    "見約翰福音（3:16）。",                  # bare in parentheses: not rewritten
    "見約翰福音 7:16。",                     # no block 7
    "見[3]。",                               # a block reference, not a chapter claim
])
def test_other_citations_are_left_alone(answer):
    assert fix_block_chapters(answer, SOURCES) == answer


@pytest.mark.parametrize("answer, fixed", [
    ("見約翰福音 第3章 16-17節。", "見約翰福音 第14章 16-17節。"),            # a verse range
    ("見約翰福音 第3章 第16-18節。", "見約翰福音 第14章 第16-18節。"),
    ("見約翰福音 第3章 16、18、20節。", "見約翰福音 第14章 16、18、20節。"),  # a verse list
    ("見約翰福音 第3章：16。", "見約翰福音 第14章：16。"),                    # 第N章：V
    ("見約翰福音 第3章:16。", "見約翰福音 第14章:16。"),
    ("（約翰福音 第1章 1節；第3章 16節）", "（約翰福音 第1章 1節；第14章 16節）"),  # the book carried over
    ("（約翰福音 第1章 1節；第3章 16-17節）", "（約翰福音 第1章 1節；第14章 16-17節）"),
    ("（約翰福音 1:1；3:16）", "（約翰福音 1:1；14:16）"),
    ("（約翰福音 1:1，3:16-18）", "（約翰福音 1:1，14:16-18）"),
    ("（約翰福音 1:1、第3章 16節）", "（約翰福音 1:1、第14章 16節）"),
    ("（約翰福音 1:1； 第3章：17）", "（約翰福音 1:1； 第14章：17）"),
    ("見約翰福音 第3章 16節至4章2節。", "見約翰福音 第14章 16節至4章2節。"),  # 4章2節 names no book
])
def test_ranges_lists_colons_and_a_carried_over_book_are_rewritten(answer, fixed):
    assert fix_block_chapters(answer, SOURCES) == fixed


@pytest.mark.parametrize("answer", [
    "見約翰福音 第3章 16-30節。",            # verse 30 is not in block 3 (15-21)
    "見約翰福音 第3章 16、30節。",
    "見約翰福音 第3章：30。",
    "（約翰福音 1:1；3:30）",
    "（約翰福音 1:1；3:16-30）",
    "（羅馬書 5:1；3:16）",                  # the carried-over book is not block 3's
    "（羅馬書 第5章 1節；第3章 16節）",
    "約翰福音提到，耶穌在第3章 16節說",       # no separator right before 第N章
    "（約翰福音 1:1；第3章）",               # no verse to check
    "（3:16；第3章 17節）",                  # no book named before
])
def test_new_forms_still_need_the_book_and_the_verse_to_match_the_block(answer):
    assert fix_block_chapters(answer, SOURCES) == answer


def test_chapters_the_question_or_the_card_names_are_left_alone():
    answer = "見約翰福音 3:17。"

    assert fix_block_chapters(answer, SOURCES, question="約翰福音第3章怎麼說？") == answer
    assert fix_block_chapters(answer, SOURCES, question="約翰福音3:17怎麼說？") == answer
    assert fix_block_chapters(answer, SOURCES, evidence=("jhn.3.17",)) == answer
    assert fix_block_chapters(answer, SOURCES, question="羅馬書第3章") == "見約翰福音 14:17。"


@pytest.mark.parametrize("question", [
    "約翰福音1-3章說什麼？", "約翰福音2-3章", "約翰福音3章怎麼說？", "約翰福音第三章怎麼說？"])
def test_chapter_ranges_and_other_question_forms_are_protected_too(question):
    """The question's chapters come from ragcommon.refs as well (ranges, no 第, numerals)."""
    assert fix_block_chapters("見約翰福音 3:17。", SOURCES, question=question) == "見約翰福音 3:17。"


def test_several_citations_in_one_answer_are_each_judged():
    answer = "見約翰福音 3:16 與羅馬書 5:3，又見約翰福音第3章第21節。"

    assert fix_block_chapters(answer, SOURCES) == (
        "見約翰福音 14:16 與羅馬書 5:3，又見約翰福音第14章第21節。")


def test_without_sources_the_answer_is_unchanged():
    assert fix_block_chapters("見約翰福音 3:16。", []) == "見約翰福音 3:16。"
    assert fix_block_chapters("", SOURCES) == ""


def test_byte_token_runs_decode_as_utf8():
    assert merge_byte_tokens("耶和華是我的牧者<0xE7><0xA5><0x9E>。") == "耶和華是我的牧者神。"
    assert merge_byte_tokens("a<0x41><0x42>b <0xe4><0xbd><0xa0>") == "aABb 你"
    assert merge_byte_tokens("<0xE7><0xA5>") == "�"
    assert merge_byte_tokens("0xE7 與 <0xZZ> 不是") == "0xE7 與 <0xZZ> 不是"

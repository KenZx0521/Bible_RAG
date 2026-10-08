"""Source book names resolve through ragcommon.books: full names and recorded variants only."""

import pytest

from src.book_names import book_id_of
from src.models import ParsedReference, SourceInfo
from src.relevance_judge import binary_relevance


@pytest.mark.parametrize("name, book_id", [
    ("尼希米記", "neh"), ("尼西米記", "neh"), ("約翰福音", "jhn"), (" 創世記 ", "gen"),
])
def test_full_names_and_variants_resolve(name, book_id):
    assert book_id_of(name) == book_id


@pytest.mark.parametrize("name", ["尼", "約", "撒母耳記", "不存在的書", "", None])
def test_abbreviations_ambiguous_and_unknown_names_do_not(name):
    assert book_id_of(name) is None


def test_a_legacy_nehemiah_source_still_matches_its_gold():
    gold = [ParsedReference(book_name="尼希米記", book_id="neh", chapters=[8])]
    for name in ("尼希米記", "尼西米記"):
        source = SourceInfo(id="x", book=name, chapter=8, verse_range="1-12")
        assert binary_relevance(source, gold)

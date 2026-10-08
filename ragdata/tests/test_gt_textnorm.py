"""GT v2 text helpers: CJK-only normalisation, clause spans and quote regions."""

from __future__ import annotations

import pytest

from ragdata.gt.textnorm import QuoteError, clause_spans, norm, quote_clause_spans


def test_norm_keeps_only_han_characters():
    assert norm("耶和華－以色列的上帝，1起初‧Abc「神」") == "耶和華以色列的上帝起初神"


def test_clauses_split_on_punctuation_and_keep_raw_offsets():
    text = "神愛世人，甚至將他的獨生子賜給他們；叫一切信他的"
    spans = clause_spans(text)
    assert [s.text for s in spans] == ["神愛世人", "甚至將他的獨生子賜給他們", "叫一切信他的"]
    assert all(text[s.start:s.end] == s.text for s in spans)


def test_a_dash_or_digit_inside_a_clause_does_not_split_it():
    assert [s.text for s in clause_spans("指著耶和華－以色列的上帝起誓：1起初")] == \
        ["指著耶和華－以色列的上帝起誓", "1起初"]


def test_quote_clauses_cover_nested_quotes_and_the_text_around_them():
    text = "彼得前書引用：「因為經上記著說：『你們要聖潔，因為我是聖潔的。』」又說「阿們」。"
    assert [s.text for s in quote_clause_spans(text)] == \
        ["因為經上記著說", "你們要聖潔", "因為我是聖潔的", "阿們"]


def test_text_outside_quotes_is_not_a_quote():
    assert quote_clause_spans("沒有引號的句子，只是轉述。") == ()


@pytest.mark.parametrize("text", ["「未關閉", "多了」", "「錯配』", "『外「內』」"])
def test_unbalanced_or_crossed_quotes_raise(text):
    with pytest.raises(QuoteError):
        quote_clause_spans(text)

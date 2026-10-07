"""Rule-based edits of GT answer fields: errata words, spellings, interpuncts, clauses."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gt.changes import apply_edits
from ragdata.gt.corpus import ServiceText
from ragdata.gt.forms import FORMS, find_forms
from ragdata.gt.mechanical import MechanicalError, mechanical_edits, project
from ragdata.gt.rules import RuleError, errata_edits, form_edits, gloss_edits, interpunct_edits
from ragdata.store import read_layer


def _corpus(tmp_path, change=None) -> ServiceText:
    files = mini_build.text_layer()
    files["errata_applied"][0]["evidence"] = {"word": "蹚過"}
    units = files["verse_units"]
    units[10]["text"] = units[10]["text_pdf"] = "在凱撒利亞‧腓立比有一個人名叫哥尼流，他照着上帝的話。"
    files["name_spans"][6].update(surface="凱撒利亞‧腓立比", end=files["name_spans"][6]["start"] + 8)
    units[13]["text"] = units[13]["text_pdf"] = "不要惹兒女的氣；塞魯士問甚麼，就帶着鎖鍊。"
    if change is not None:
        change(files)
    text, _ = mini_build.write_layers(tmp_path, text=files)
    return ServiceText.from_layer(read_layer(text.path))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> ServiceText:
    return _corpus(tmp_path_factory.mktemp("store"))


def _apply(value, edits):
    return apply_edits("Q", "reference_answer", value, edits, rule="r")[0]


def test_errata_words_take_the_corrected_word_backed_by_a_gold_unit(corpus):
    edits = errata_edits("掃羅詵過小河", corpus, gold=("act.9.3",))
    assert _apply("掃羅詵過小河", edits) == "掃羅蹚過小河"
    assert edits[0].evidence_slot == "act.9.3"


def test_cunp_spellings_and_glosses_become_the_corpus_form(corpus):
    text = "大流士（大利烏）年間，該撒下令；古列王"
    text = _apply(text, gloss_edits(text))
    assert text == "大流士年間，該撒下令；古列王"
    edits = form_edits(text, corpus, rule="cunp_spelling", gold=())
    assert _apply(text, edits) == "大流士年間，凱撒下令；塞魯士王"


def test_orthography_keeps_the_zhu_of_famous_and_authored(corpus):
    text = "他帶著稱呼馬可的約翰，又帶著鎖鏈；著名的先知著有一書，有什麼顯著的事在那裡"
    edits = form_edits(text, corpus, rule="corpus_orthography", gold=())
    assert _apply(text, edits) == "他帶着稱呼馬可的約翰，又帶着鎖鍊；著名的先知著有一書，有甚麼顯著的事在那裏"
    assert all(e.evidence_slot is None for e in edits)


def test_interpunct_restores_dotted_names_whose_bare_form_the_corpus_never_writes(corpus):
    text = "耶穌到了凱撒利亞腓立比，又到凱撒利亞"
    edits = interpunct_edits(text, corpus, gold=())
    assert _apply(text, edits) == "耶穌到了凱撒利亞‧腓立比，又到凱撒利亞"
    assert edits[0].evidence_slot == "act.10.1"


def test_a_dotted_name_whose_bare_form_the_corpus_also_writes_is_left_alone(tmp_path):
    def bare_too(files):
        files["verse_units"][11]["text"] = files["verse_units"][11]["text_pdf"] = "凱撒利亞腓立比。"
    corpus = _corpus(tmp_path, bare_too)
    assert interpunct_edits("凱撒利亞腓立比", corpus, gold=()) == []


def test_mechanical_clauses_become_service_text_and_keep_raw_punctuation(corpus):
    text = "他照著神的話，1起初－不在經文裏的話也照著做。"
    edits = mechanical_edits(text, corpus, gold=("act.10.1",))
    assert _apply(text, edits) == "他照着上帝的話，1起初－不在經文裏的話也照著做。"
    assert edits[0].evidence_slot == "act.10.1"


def test_a_clause_already_in_the_corpus_is_not_touched(corpus):
    assert mechanical_edits("他照着上帝的話。", corpus, gold=()) == []


def test_project_carries_non_han_characters_over():
    assert project("耶和華－以色列的神", "耶和華以色列的神", "耶和華以色列的上帝") == \
        "耶和華－以色列的上帝"
    with pytest.raises(MechanicalError):
        project("神－著", "神著", "上着")


def test_a_form_whose_replacement_the_corpus_lacks_is_refused(tmp_path):
    def no_chains(files):
        files["verse_units"][13]["text"] = files["verse_units"][13]["text_pdf"] = "不要惹兒女的氣。"
    with pytest.raises(RuleError, match="鍊"):
        form_edits("鐵鏈", _corpus(tmp_path, no_chains), rule="corpus_orthography", gold=())


def test_every_form_is_absent_from_its_own_replacement():
    for form in FORMS:
        assert find_forms(form.corpus_form, (form,)) == []

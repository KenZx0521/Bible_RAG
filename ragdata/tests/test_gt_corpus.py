"""The service-text index GT v2 aligns answers to (verse_units.text, text_pdf at errata)."""

from __future__ import annotations

import pytest

import mini_build
from ragdata.gt.corpus import CorpusError, ServiceText
from ragdata.store import read_layer


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> ServiceText:
    text, _ = mini_build.write_layers(tmp_path_factory.mktemp("store"))
    return ServiceText.from_layer(read_layer(text.path))


def test_it_knows_the_layer_version_and_slot_statuses(corpus):
    assert corpus.version.startswith("text@")
    assert corpus.slot_status["mat.18.3"] == "omitted_variant"
    assert corpus.slot_status["eph.6.3"] == "merged"
    assert corpus.slot_status["mat.18.4"] == "present"


def test_clauses_match_across_verses_of_a_chapter_but_not_across_chapters(corpus):
    assert corpus.contains("溪水我的心渴想上帝")
    assert not corpus.contains("飲食願他用口")


def test_errata_positions_accept_the_pdf_glyph_as_well(corpus):
    assert corpus.contains("蹚過小河")
    assert corpus.contains("詵過小河")
    assert not corpus.contains("趟過小河")


def test_locate_names_the_slot_where_a_clause_starts(corpus):
    assert corpus.locate("這是第一條帶應許的誡命") == "eph.6.2"
    assert corpus.locate("沒有這句話") is None


def test_local_text_is_the_text_of_the_given_slots_only(corpus):
    local = corpus.local(("mat.18.1", "mat.18.2", "eph.6.1"))
    assert "天國裏誰是最大的" in local
    assert "要在主裏聽從父母" in local
    assert "凡自己謙卑" not in local
    assert corpus.locate("要在主裏聽從父母", within=("mat.18.1", "eph.6.1")) == "eph.6.1"
    assert corpus.locate("要在主裏聽從父母", within=("mat.18.1",)) is None


def test_local_text_of_an_omitted_slot_is_empty(corpus):
    assert corpus.local(("mat.18.3",)) == ""


def test_count_counts_raw_service_text_with_punctuation(corpus):
    assert corpus.count("大馬士革") == 2
    assert corpus.count("詵") == 0


def test_errata_words_and_dotted_names_come_from_the_layer(tmp_path):
    files = mini_build.text_layer()
    files["errata_applied"][0]["evidence"] = {"word": "蹚過"}
    files["verse_units"][10]["text"] = files["verse_units"][10]["text_pdf"] = \
        "在凱撒利亞‧腓立比有一個人名叫哥尼流。"
    files["name_spans"][6]["surface"] = "凱撒利亞‧腓立比"
    files["name_spans"][6]["end"] = files["name_spans"][6]["start"] + 8
    text, _ = mini_build.write_layers(tmp_path, text=files)
    corpus = ServiceText.from_layer(read_layer(text.path))
    assert corpus.errata_words == (("詵過", "蹚過", ("act.9.3",)),)
    assert corpus.dotted_names == ("凱撒利亞‧腓立比",)


def test_a_slot_whose_unit_is_missing_is_refused(tmp_path):
    files = mini_build.text_layer()
    files["verse_slots"][0]["unit_key"] = "psa.42.9"
    text, _ = mini_build.write_layers(tmp_path, text=files)
    with pytest.raises(CorpusError, match="psa.42.9"):
        ServiceText.from_layer(read_layer(text.path))


def test_only_a_text_layer_is_accepted(tmp_path):
    _, struct = mini_build.write_layers(tmp_path)
    with pytest.raises(CorpusError, match="text layer"):
        ServiceText.from_layer(read_layer(struct.path))


def test_local_text_runs_on_across_verses_of_one_chapter(corpus):
    local = corpus.local(("psa.42.1", "psa.42.2", "eph.6.1"))
    assert "溪水我的心渴想上帝" in local
    assert corpus.locate("溪水我的心渴想", within=("psa.42.1", "psa.42.2")) == "psa.42.1"
    assert corpus.locate("渴想上帝", within=("psa.42.1", "psa.42.2")) == "psa.42.2"


def test_contains_can_insist_on_the_service_text(corpus):
    assert corpus.contains("詵過小河")
    assert not corpus.contains("詵過小河", accept_pdf=False)


def test_local_pdf_text_has_the_pdf_glyphs_at_errata_positions(corpus):
    slots = ("act.9.2", "act.9.3")
    assert "蹚過小河" in corpus.local(slots) and "詵過小河" not in corpus.local(slots)
    assert "詵過小河" in corpus.local(slots, pdf=True)
    assert len(corpus.local(slots, pdf=True)) == len(corpus.local(slots))

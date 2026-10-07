"""Structured refs and gold slots of a GT reference, on the mini text layer."""

from __future__ import annotations

import pytest

import mini_build
from ragcommon.refs import RefParseError
from ragdata.gt.corpus import ServiceText
from ragdata.gt.goldrefs import GoldError, derive_gold
from ragdata.store import read_layer


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> ServiceText:
    text, _ = mini_build.write_layers(tmp_path_factory.mktemp("store"))
    return ServiceText.from_layer(read_layer(text.path))


def _derive(reference, corpus):
    return derive_gold(reference, corpus, mini_build.versification())


def test_an_omitted_slot_is_listed_apart_and_is_not_gold(corpus):
    gold = _derive("馬太福音 18:1-4", corpus)
    assert gold.refs == ({"book_id": "mat", "ch": 18, "v_start": 1, "v_end": 4, "ch_end": 18},)
    assert gold.gold_slots == ("mat.18.1", "mat.18.2", "mat.18.4")
    assert gold.omitted_slots == ("mat.18.3",)


def test_merged_slots_are_gold_and_whole_chapters_have_null_verses(corpus):
    assert _derive("以弗所書 6:3", corpus).gold_slots == ("eph.6.3",)
    whole = _derive("詩篇 42篇", corpus)
    assert whole.refs[0]["v_start"] is None and whole.refs[0]["v_end"] is None
    assert whole.gold_slots == ("psa.42.1", "psa.42.2", "psa.42.3")


def test_external_verse_numbers_go_through_ref_aliases(corpus):
    gold = _derive("馬太福音 18:5", corpus)
    assert gold.gold_slots == ("mat.18.4",)
    assert gold.aliases_applied == ("mat.18.5->mat.18.4",)


def test_overlapping_refs_list_each_slot_once_in_order(corpus):
    gold = _derive("使徒行傳 9:2-3; 9:1-2; 10:1", corpus)
    assert gold.gold_slots == ("act.9.2", "act.9.3", "act.9.1", "act.10.1")


def test_a_reference_the_strict_parser_rejects_raises(corpus):
    with pytest.raises(RefParseError):
        _derive("馬太福音 18:9", corpus)


def test_a_reference_with_only_omitted_slots_has_no_gold(corpus):
    with pytest.raises(GoldError, match="no gold"):
        _derive("馬太福音 18:3", corpus)


def test_a_slot_outside_the_layer_raises(corpus):
    vers = mini_build.versification(grid={**mini_build.GRID, "sng": (2,)})
    with pytest.raises(GoldError, match="sng.1.2"):
        derive_gold("雅歌 1:1-2", corpus, vers)

import json

import pytest

from ragcommon import versification as vmod
from ragcommon.books import UnknownBookError
from ragcommon.versification import VersificationError

OMITTED = [
    "mat.18.11", "mat.23.14", "mrk.7.16", "mrk.15.28", "luk.17.36", "luk.23.17",
    "jhn.5.4", "act.8.37", "act.15.34", "act.24.7", "act.28.29",
]


@pytest.fixture(scope="module")
def vers():
    return vmod.default_versification()


def _raw():
    return json.loads(vmod.DATA_PATH.read_text(encoding="utf-8"))


def _write_json(tmp_path, doc, name="v.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def _write_aliases(tmp_path, records):
    path = tmp_path / "aliases.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


ALIAS = {"external_ref": "jhn.7.53", "relation": "contained_in", "target": "jhn.8.1",
         "note": "n", "provenance_class": "external_reference"}


def test_slot_universe_matches_pdf_counts(vers):
    assert vers.slot_count() == 31_103
    assert sum(vers.chapter_count(b) for b in vers.max_verses) == 1_189
    keys = list(vers.iter_slot_keys())
    assert len(keys) == 31_103 and keys[0] == "gen.1.1" and keys[-1] == "rev.22.21"


@pytest.mark.parametrize(
    "book_id, chapters",
    [("gen", 50), ("psa", 150), ("mal", 4), ("jon", 4), ("oba", 1), ("jud", 1), ("rev", 22)],
)
def test_chapter_counts(vers, book_id, chapters):
    assert vers.chapter_count(book_id) == chapters


@pytest.mark.parametrize(
    "book_id, chapter, top",
    [("jhn", 7, 52), ("luk", 17, 37), ("psa", 119, 176), ("3jn", 1, 15), ("eph", 6, 24),
     ("mat", 18, 35), ("jon", 1, 17), ("gen", 1, 31)],
)
def test_max_verse(vers, book_id, chapter, top):
    assert vers.max_verse(book_id, chapter) == top
    assert vers.has_slot(book_id, chapter, top)
    assert not vers.has_slot(book_id, chapter, top + 1)


def test_eleven_omitted_slots_point_at_previous_verse_footnote(vers):
    assert sorted(vers.omitted) == sorted(OMITTED)
    for key in OMITTED:
        assert vers.is_omitted(key)
        book, ch, v = key.split(".")
        assert vers.omitted[key].variant_in_footnote_of == f"{book}.{ch}.{int(v) - 1}"
    assert not vers.is_omitted("jhn.3.16")


def test_alias_jhn_7_53_contained_in_8_1(vers):
    alias = vers.alias("jhn.7.53")
    assert (alias.relation, alias.target) == ("contained_in", "jhn.8.1")
    assert vers.alias("jhn.3.16") is None


@pytest.mark.parametrize(
    "book_id, chapter, verse, slot, aliased",
    [("jhn", 7, 53, "jhn.8.1", True), ("luk", 17, 36, "luk.17.36", False),
     ("jhn", 3, 16, "jhn.3.16", False)],
)
def test_resolve_maps_external_refs_to_pdf_slots(vers, book_id, chapter, verse, slot, aliased):
    key, alias = vers.resolve(book_id, chapter, verse)
    assert key == slot
    assert (alias is not None) is aliased


@pytest.mark.parametrize("args", [("gen", 1, 32), ("gen", 51, 1), ("gen", 0, 1), ("jhn", 7, 54)])
def test_resolve_raises_when_pdf_has_no_slot(vers, args):
    with pytest.raises(VersificationError):
        vers.resolve(*args)


def test_max_verse_rejects_missing_chapter(vers):
    with pytest.raises(VersificationError):
        vers.max_verse("gen", 51)
    assert not vers.has_chapter("gen", 51)
    assert vers.has_chapter("gen", 50)
    with pytest.raises(UnknownBookError):
        vers.chapter_count("xyz")


def test_source_names_the_text_layer_it_was_derived_from(vers):
    assert vers.source["kind"] == "text_layer"
    assert vers.source["layer_version"].startswith("text@")


def test_load_ref_aliases_accepts_json_array(tmp_path, vers):
    path = _write_json(tmp_path, [ALIAS], name="aliases.json")
    loaded = vmod.load_versification(vmod.DATA_PATH, path)
    assert loaded.alias("jhn.7.53").target == "jhn.8.1"


@pytest.mark.parametrize(
    "record, message",
    [
        ({**ALIAS, "relation": "same_as"}, "relation"),
        ({**ALIAS, "external_ref": "jhn.7.52"}, "exists"),
        ({**ALIAS, "target": "jhn.8.99"}, "target"),
        ({**ALIAS, "target": "mat.18.11"}, "target"),
        ({**ALIAS, "external_ref": "jhn.7"}, "slot"),
        ({**ALIAS, "provenance_class": ""}, "provenance_class"),
        ({k: v for k, v in ALIAS.items() if k != "target"}, "target"),
    ],
)
def test_bad_aliases_are_rejected(tmp_path, record, message):
    path = _write_aliases(tmp_path, [record])
    with pytest.raises(VersificationError, match=message):
        vmod.load_versification(vmod.DATA_PATH, path)


def test_duplicate_alias_rejected(tmp_path):
    path = _write_aliases(tmp_path, [ALIAS, ALIAS])
    with pytest.raises(VersificationError, match="duplicate"):
        vmod.load_versification(vmod.DATA_PATH, path)


def _with_max(doc, book_id, value):
    return {**doc, "max_verse": {**doc["max_verse"], book_id: value}}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: {**d, "schema": "other"}, "schema"),
        (lambda d: {**d, "max_verse": {k: v for k, v in d["max_verse"].items() if k != "rev"}}, "rev"),
        (lambda d: _with_max(d, "xyz", [1]), "xyz"),
        (lambda d: _with_max(d, "gen", []), "gen"),
        (lambda d: _with_max(d, "gen", [0]), "gen"),
        (lambda d: _with_max(d, "gen", [True]), "gen"),
        (lambda d: {**d, "omitted_slots": [{"slot_key": "mat.18.99", "variant_in_footnote_of": "mat.18.10"}]},
         "mat.18.99"),
        (lambda d: {**d, "omitted_slots": d["omitted_slots"] * 2}, "duplicate"),
        (lambda d: {**d, "omitted_slots": [{"slot_key": "mat.18", "variant_in_footnote_of": "mat.18.10"}]},
         "not a slot key"),
        (lambda d: {**d, "omitted_slots": [{"slot_key": "mat.18.11", "variant_in_footnote_of": "x"}]},
         "variant"),
    ],
)
def test_bad_versification_rejected(tmp_path, mutate, message):
    path = _write_json(tmp_path, mutate(_raw()))
    with pytest.raises(VersificationError, match=message):
        vmod.load_versification(path, vmod.ALIASES_PATH)

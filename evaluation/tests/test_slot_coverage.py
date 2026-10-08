"""Verse coverage on the GT v2 slot universe: gold slots, anchors, and both arms' source maps.

Corpus facts used (text@ddb48c599861): 約翰福音 5 章第 4 節與馬太福音 18 章第 11 節
是缺號槽；約翰福音 7 章 52 節，7:53 經 ref_aliases 併入 8:1；路加福音 17 章有 37 個
節位（舊計數表只記 36）；馬太福音 5–7 章 111 節。
"""

import hashlib
import json

import pytest

from src.gt_v2 import GroundTruthItemV2
from src.models import SourceInfo
from src.slot_coverage import SlotCoverageError, build_ruler, gold_anchors, load_verse_index

UNIVERSE = "text@ddb48c599861"
LEGACY = "legacy-20261004"
BUILD = "b20261008_0000abcd"


def _item(refs, gold, omitted=()):
    return GroundTruthItemV2(
        question_id="Q", question="q", question_type="VERSE_LOOKUP", book_name="b",
        refs=[dict(zip(("book_id", "ch", "v_start", "v_end", "ch_end"), r)) for r in refs],
        gold_slots=list(gold), omitted_slots=list(omitted))


def _src(book, chapter, verse_range="", **kw):
    return SourceInfo(id=kw.pop("id", "s"), book=book, chapter=chapter, verse_range=verse_range, **kw)


def _slots(book, chapter, first, last, skip=()):
    return [f"{book}.{chapter}.{v}" for v in range(first, last + 1) if v not in skip]


JHN5 = _item([("jhn", 5, 1, 18, 5)], _slots("jhn", 5, 1, 18, skip={4}), ["jhn.5.4"])


@pytest.fixture(scope="module")
def legacy():
    return build_ruler(UNIVERSE, LEGACY, None)


# --- gold and anchors ----------------------------------------------------------

def test_anchors_split_chapter_ranges_and_cross_chapter_verse_ranges(legacy):
    mat = _item([("mat", 5, None, None, 7)],
                _slots("mat", 5, 1, 48) + _slots("mat", 6, 1, 34) + _slots("mat", 7, 1, 29))
    jon = _item([("jon", 1, 17, 10, 2)], _slots("jon", 1, 17, 17) + _slots("jon", 2, 1, 10))

    assert [len(a) for a in gold_anchors(mat, legacy.universe)] == [48, 34, 29]
    assert gold_anchors(jon, legacy.universe) == [frozenset({"jon.1.17"}),
                                                  frozenset(_slots("jon", 2, 1, 10))]


def test_an_anchor_with_only_an_omitted_slot_is_dropped(legacy):
    item = _item([("mat", 18, 10, 10, 18), ("mat", 18, 11, 11, 18)], ["mat.18.10"], ["mat.18.11"])

    assert gold_anchors(item, legacy.universe) == [frozenset({"mat.18.10"})]


# --- legacy arm: numbering straight onto the universe ----------------------------

@pytest.mark.parametrize("verse_range, expected", [
    ("1-18", (1.0, 1.0)),
    ("4", (0.0, 0.0)),          # the ghost verse lands on its omitted slot: never gold
    ("3-5", (round(2 / 17, 4), 1.0)),
])
def test_legacy_ghost_verses_map_to_omitted_slots(legacy, verse_range, expected):
    assert legacy.verse_metrics(JHN5, [_src("約翰福音", 5, verse_range)]) == expected


def test_a_chapter_source_takes_the_chapters_actual_slots(legacy):
    item = _item([("luk", 17, 37, 37, 17)], ["luk.17.37"])

    assert legacy.verse_metrics(item, [_src("路加福音", 17)]) == (1.0, 1.0)
    assert len(legacy.source_slots([_src("路加福音", 17)])) == 37


def test_a_verse_number_without_a_slot_goes_through_ref_aliases(legacy):
    item = _item([("jhn", 8, 1, 1, 8)], ["jhn.8.1"])

    assert legacy.verse_metrics(item, [_src("約翰福音", 7, "53")]) == (1.0, 1.0)


def test_the_old_nehemiah_name_maps(legacy):
    assert legacy.source_slots([_src("尼西米記", 8, "1-2")]) == {"neh.8.1", "neh.8.2"}


@pytest.mark.parametrize("source, message", [
    (_src("約翰福音", 3, "40"), "no slot"),
    (_src("約翰福音", 99, "1"), "no chapter"),
    (_src("不存在的書", 1, "1"), "book/chapter"),
    (_src("約翰福音", None, "1"), "book/chapter"),
    (_src("約翰福音", 3, "16, 18"), "verse_range"),
    (_src("約翰福音", 3, "18-16"), "verse_range"),
])
def test_a_source_the_ruler_cannot_map_raises(legacy, source, message):
    with pytest.raises(SlotCoverageError, match=message):
        legacy.source_slots([source])


@pytest.mark.parametrize("fields", [
    {"id": "ps:jhn.5.1"}, {"id": "jhn:5:0", "kind": "passage"},
    {"id": "jhn:5:0", "start_key": "jhn.5.1", "end_key": "jhn.5.18"},
])
def test_a_new_build_source_under_the_legacy_label_raises(legacy, fields):
    with pytest.raises(SlotCoverageError, match="--contracts-dir"):
        legacy.source_slots([_src("約翰福音", 5, "1-18", **fields)])


def test_no_sources_cover_nothing(legacy):
    assert legacy.verse_metrics(JHN5, []) == (0.0, 0.0)


# --- new build arm: the build's verse_index ----------------------------------------

def _slot(key, unit=None, status="present"):
    return {"slot_key": key, "unit_key": unit if unit is not None else key, "status": status}


INDEX = [_slot("gen.24.28"), _slot("gen.24.29", "gen.24.29-30", "merged"),
         _slot("gen.24.30", "gen.24.29-30", "merged"), _slot("gen.24.31"),
         _slot("jhn.5.3"), {"slot_key": "jhn.5.4", "unit_key": None, "status": "omitted_variant"},
         _slot("jhn.5.5"), _slot("jhn.7.52"), _slot("jhn.8.1")]


def _contracts(tmp_path, slots=INDEX, build_id=BUILD, schema="ragdata.contract.verse_index.v1",
               sha=None):
    data = json.dumps({"schema": schema, "slots": slots}).encode()
    (tmp_path / "verse_index.json").write_bytes(data)
    files = {"verse_index.json": sha or hashlib.sha256(data).hexdigest()}
    (tmp_path / "manifest.json").write_text(json.dumps({"build_id": build_id, "files": files}))
    return tmp_path


@pytest.fixture
def build(tmp_path):
    return build_ruler(UNIVERSE, BUILD, _contracts(tmp_path))


def _new(book, chapter, verse_range="", **kw):
    """A new build's source: a passage id of the ragcommon.ids grammar and its kind."""
    return _src(book, chapter, verse_range, **{"id": "ps:gen.24.28", "kind": "passage", **kw})


def test_build_sources_map_by_start_and_end_keys_with_whole_units(build):
    item = _item([("gen", 24, 30, 30, 24)], ["gen.24.30"])
    source = _new("創世記", 24, "28-29", start_key="gen.24.28b", end_key="gen.24.29")

    assert build.source_slots([source]) == {"gen.24.28", "gen.24.29", "gen.24.30"}
    assert build.verse_metrics(item, [source]) == (1.0, 1.0)


def test_build_sources_without_keys_map_by_number_with_whole_units(build):
    assert build.source_slots([_new("創世記", 24, "30")]) == {"gen.24.29", "gen.24.30"}
    assert build.source_slots([_new("約翰福音", 7, "53")]) == {"jhn.8.1"}


def test_a_unit_end_key_ends_at_its_last_slot(build):
    source = _new("創世記", 24, "", start_key="gen.24.28", end_key="gen.24.29-30")

    assert build.source_slots([source]) == {"gen.24.28", "gen.24.29", "gen.24.30"}


@pytest.mark.parametrize("fields", [
    {"id": "ps:gen.24.28", "kind": None}, {"id": "s", "kind": "passage"},
    {"id": "s", "kind": None, "start_key": "gen.24.28", "end_key": "gen.24.28"},
])
def test_any_new_build_mark_lets_a_source_map(build, fields):
    assert build.source_slots([_new("創世記", 24, "28", **fields)]) == {"gen.24.28"}


@pytest.mark.parametrize("source_id", ["jhn:5:3", "s"])
def test_a_legacy_source_under_a_new_build_label_raises(build, source_id):
    """Legacy answers labelled as a new build (BACKEND_URL left on prod) must not score."""
    with pytest.raises(SlotCoverageError, match=f"legacy source.*{BUILD}"):
        build.source_slots([_src("約翰福音", 5, "3", id=source_id)])


@pytest.mark.parametrize("keys, message", [
    ({"start_key": "gen.24.30", "end_key": "gen.24.28"}, "ascending"),
    ({"start_key": "gen.24.31", "end_key": "jhn.5.3"}, "ascending"),
    ({"start_key": "gen.24.28"}, "together"),
    ({"start_key": "ps:gen.24.28", "end_key": "gen.24.29"}, "not a verse key"),
    ({"start_key": "gen:24:28", "end_key": "gen.24.29"}, "prefix"),
    ({"start_key": "gen.24.1", "end_key": "gen.24.29"}, "not in the verse grid"),
])
def test_bad_keys_raise(build, keys, message):
    with pytest.raises(SlotCoverageError, match=message):
        build.source_slots([_new("創世記", 24, "", **keys)])


@pytest.mark.parametrize("change, message", [
    ({"build_id": "b20261008_ffffffff"}, "holds build"),
    ({"sha": "0" * 64}, "sha256"),
    ({"schema": "other"}, "schema"),
])
def test_contracts_that_are_not_this_builds_are_refused(tmp_path, change, message):
    with pytest.raises(SlotCoverageError, match=message):
        load_verse_index(_contracts(tmp_path, **change), BUILD)


def test_missing_contracts_are_refused(tmp_path):
    with pytest.raises(SlotCoverageError, match="cannot read"):
        load_verse_index(tmp_path, BUILD)
    (tmp_path / "manifest.json").write_text(json.dumps({"build_id": BUILD, "files": {}}))
    with pytest.raises(SlotCoverageError, match="cannot read"):
        load_verse_index(tmp_path, BUILD)


def test_a_new_build_needs_its_contracts_and_the_universe_must_match():
    with pytest.raises(SlotCoverageError, match="contracts"):
        build_ruler(UNIVERSE, BUILD, None)
    with pytest.raises(SlotCoverageError, match="slot_universe"):
        build_ruler("text@000000000000", LEGACY, None)


def test_every_frozen_gt_v2_item_is_fully_covered_by_its_own_chapters(legacy):
    """Gold slots and anchors of the committed GT v2 all lie on its slot universe."""
    from ragcommon import books
    from src.data_loader import load_gt

    gt = load_gt("v2")
    short = []
    for item in gt.items:
        chapters = {(r.book_id, ch) for r in item.refs for ch in range(r.ch, r.ch_end + 1)}
        sources = [_src(books.get_book(b).name, ch) for b, ch in sorted(chapters)]
        if legacy.verse_metrics(item, sources) != (1.0, 1.0):
            short.append(item.question_id)

    assert gt.slot_universe == UNIVERSE and short == []


# --- relevance under GT v2: a source is relevant when it holds a gold slot ----------

def _sample(item, sources):
    from src.models import EvalSample
    return EvalSample(question_id="Q", question="q", question_type="EVENT_QUESTION",
                      ground_truth=item, sources=sources)


def test_v2_relevance_is_a_gold_slot_not_a_reference_overlap(legacy):
    from src.metrics.retrieval import compute_retrieval_metrics, gold_flags
    from src.models import GroundTruthItem

    item = JHN5.model_copy(update={"reference": "約翰福音 5:1-18"})
    ghost, real = _src("約翰福音", 5, "4"), _src("約翰福音", 5, "1-3")
    v1 = GroundTruthItem(**item.model_dump(include=set(GroundTruthItem.model_fields)))

    assert gold_flags(_sample(item, [ghost, real]), [ghost, real], legacy) == [False, True]
    assert gold_flags(_sample(v1, [ghost, real]), [ghost, real]) == [True, True]
    metrics = {m.name: m.value for m in compute_retrieval_metrics(
        [_sample(item, [ghost, real])], k=5, ruler=legacy)["Q"]}
    assert (metrics["mrr"], metrics["hit_rate"]) == (0.5, 1.0)


def test_a_v2_item_without_a_ruler_and_a_v1_item_with_one_are_refused(legacy):
    from src.metrics.retrieval import gold_flags
    from src.models import GroundTruthItem

    v1 = GroundTruthItem(question_id="Q", question="q", question_type="T", book_name="b",
                         reference="約翰福音 5:1")
    with pytest.raises(ValueError, match="slot ruler"):
        gold_flags(_sample(JHN5, []), [], None)
    with pytest.raises(ValueError, match="slot ruler"):
        gold_flags(_sample(v1, []), [], legacy)

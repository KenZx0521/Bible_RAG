"""GT v2 build on the mini layer: what changes, what does not, and what refuses to build."""

from __future__ import annotations

import copy

import pytest

import gt_fixture
from ragdata.gt.build import BuildError, build_v2, encode_doc
from ragdata.gt.changes import apply_changes, revert_changes
from ragdata.gt.corpus import ServiceText
from ragdata.gt.curated import parse_curated
from ragdata.gt.rules import RuleError


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> ServiceText:
    return gt_fixture.corpus(tmp_path_factory.mktemp("store"))


@pytest.fixture(scope="module")
def built(corpus):
    return gt_fixture.build(corpus)


def _q(built, qid):
    return next(q for q in built.doc["questions"] if q["question_id"] == qid)


def test_the_header_keeps_v1_and_declares_universe_sources_and_changes(corpus, built):
    meta = built.doc["metadata"]
    assert meta["description"] == "mini" and meta["total_questions"] == 3
    assert (meta["gt_version"], meta["slot_universe"]) == ("v2", corpus.version)
    assert meta["v1"]["path"] == "ground_truth.json" and len(meta["v1"]["sha256"]) == 64
    assert meta["changes"]["count"] == len(built.changes)
    assert meta["kay_review"][0]["qid"] == "VERSE_LOOKUP_001"
    assert meta["quote_exempt"][0]["quote"] == "大馬士革路上"


def test_question_fields_are_v1_and_refs_slots_are_added(built):
    for v1q, v2q in zip(gt_fixture.V1["questions"], built.doc["questions"]):
        assert {k: v2q[k] for k in ("question_id", "question", "reference")} == \
            {k: v1q[k] for k in ("question_id", "question", "reference")}
    vl = _q(built, "VERSE_LOOKUP_001")
    assert vl["refs"] == [{"book_id": "mat", "ch": 18, "v_start": 1, "v_end": 4, "ch_end": 18}]
    assert (vl["gold_slots"], vl["omitted_slots"]) == (["mat.18.1", "mat.18.2", "mat.18.4"],
                                                        ["mat.18.3"])
    assert list(vl)[-4:] == ["family", "refs", "gold_slots", "omitted_slots"]


def test_answers_are_aligned_and_each_edit_is_logged_with_its_rule(built):
    assert _q(built, "VERSE_LOOKUP_001")["reference_answer"].endswith("他在天國裏就是最大的。」")
    event = _q(built, "EVENT_QUESTION_021")["reference_answer"]
    assert event.startswith("掃羅帶着文書往大馬士革去，「詵過小河") and "「大馬士革路上」" in event
    assert "要在主裏聽從父母" in _q(built, "TOPIC_QUESTION_021")["reference_answer"]
    rules = {(c.qid, c.rule) for c in built.changes}
    assert {("VERSE_LOOKUP_001", "mechanical_clause"), ("EVENT_QUESTION_021", "cunp_spelling"),
            ("EVENT_QUESTION_021", "corpus_orthography"),
            ("TOPIC_QUESTION_021", "quote_original"),
            ("VERSE_LOOKUP_001", "legacy_family")} <= rules
    fix = next(c for c in built.changes if c.rule == "quote_original")
    assert (fix.before, fix.after, fix.evidence_slot) == ("要聽從父母", "要在主裏聽從父母", "eph.6.1")


def test_the_log_replays_v1_into_v2_and_back(built):
    v2 = [{k: v for k, v in q.items() if k not in ("refs", "gold_slots", "omitted_slots")}
          for q in built.doc["questions"]]
    assert apply_changes(gt_fixture.V1["questions"], built.changes) == v2
    assert revert_changes(v2, built.changes) == gt_fixture.V1["questions"]


def test_the_build_is_deterministic(corpus, built):
    again = gt_fixture.build(corpus)
    assert encode_doc(again.doc) == encode_doc(built.doc)
    assert again.changes_bytes == built.changes_bytes


def test_a_reference_the_strict_parser_rejects_stops_the_build_and_names_it(corpus):
    v1 = gt_fixture.v1()
    v1["questions"][0]["reference"] = "馬太福音 18:9"
    with pytest.raises(BuildError, match="VERSE_LOOKUP_001"):
        gt_fixture.build(corpus, v1_doc=v1)


def _curated(**fix):
    curated = copy.deepcopy(gt_fixture.CURATED)
    curated["quote_fixes"][0].update(fix)
    return curated


@pytest.mark.parametrize("fix, message", [
    ({"before": "不在欄位裏"}, "occurs 0 times"),
    ({"after": "要在家裏聽從父母"}, "not service text"),
    ({"evidence_slot": "eph.6.9"}, "unknown slot"),
    ({"qid": "VERSE_LOOKUP_001"}, "occurs 0 times"),
    ({"field": "expected_answer_points[0]"}, "occurs 0 times"),
])
def test_a_quote_fix_that_does_not_fit_stops_the_build(corpus, fix, message):
    with pytest.raises(BuildError, match=message):
        gt_fixture.build(corpus, curated=_curated(**fix))


def test_a_quote_fix_for_a_missing_field_is_reported_unused(corpus):
    with pytest.raises(BuildError, match="never applied"):
        gt_fixture.build(corpus, curated=_curated(field="expected_answer_points[7]"))


def test_a_spelling_whose_corpus_form_the_layer_lacks_stops_the_build(corpus):
    v1 = gt_fixture.v1()
    v1["questions"][0]["reference_answer"] = "古列王下令。"
    with pytest.raises(RuleError, match="塞魯士"):
        build_v2(v1, corpus, gt_fixture.mini_build.versification(),
                 parse_curated(copy.deepcopy(gt_fixture.CURATED)), gt_fixture.PROV)

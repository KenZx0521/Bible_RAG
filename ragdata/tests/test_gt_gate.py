"""G-GT: a correct GT v2 passes; each kind of damage turns its check red."""

from __future__ import annotations

import copy

import pytest

import gt_fixture
import mini_build
from ragdata.gt.build import encode_doc, sha256
from ragdata.gt.changes import Change
from ragdata.gt.corpus import ServiceText
from ragdata.gt.gate import GtInputs, check_gt, freeze_record
from ragdata.store import read_layer


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> ServiceText:
    return gt_fixture.corpus(tmp_path_factory.mktemp("store"))


@pytest.fixture(scope="module")
def built(corpus):
    return gt_fixture.build(corpus)


def _inputs(corpus, built, doc=None, changes=None, freeze=None, v1=None) -> GtInputs:
    doc = copy.deepcopy(built.doc) if doc is None else doc
    v2_bytes = encode_doc(doc)
    return GtInputs(
        doc=doc, corpus=corpus, vers=mini_build.versification(),
        v1_doc=gt_fixture.v1() if v1 is None else v1, v1_sha256=sha256(gt_fixture.v1_bytes()),
        changes=tuple(built.changes) if changes is None else changes,
        changes_sha256=sha256(built.changes_bytes),
        freeze=freeze_record(built.doc, encode_doc(built.doc)) if freeze is None else freeze,
        v2_sha256=sha256(v2_bytes))


def _failed(report) -> set[str]:
    return {g.name for g in report.gates if g.hard and not g.passed}


def _gate(report, name):
    return next(g for g in report.gates if g.name == name)


def test_the_built_gt_passes_every_check(corpus, built):
    report = check_gt(_inputs(corpus, built))
    assert report.passed, [g.to_json() for g in report.gates if not g.passed]
    assert {g.name for g in report.gates} == {
        "G-GT.refs", "G-GT.gold", "G-GT.quote", "G-GT.spelling", "G-GT.v1", "G-GT.changes",
        "G-GT.freeze", "G-GT.locality"}
    assert {g.name for g in report.gates if not g.hard} == {"G-GT.locality"}
    assert all(g.passed for g in report.gates)


def _mutated(built, change):
    doc = copy.deepcopy(built.doc)
    change(doc["questions"])
    return doc


def _set(index, key, value):
    return lambda qs: qs[index].__setitem__(key, value)


CASES = {
    "refs differ from the reference": (_set(0, "refs", [{"book_id": "mat", "ch": 18, "v_start": 1,
                                                         "v_end": 2, "ch_end": 18}]),
                                       {"G-GT.refs"}),
    "refs are a string": (_set(0, "refs", "馬太福音 18:1-4"), {"G-GT.refs"}),
    "a ref lacks ch_end": (_set(0, "refs", [{"book_id": "mat", "ch": 18, "v_start": 1,
                                             "v_end": 4}]), {"G-GT.refs"}),
    "a ref with one null verse": (_set(0, "refs", [{"book_id": "mat", "ch": 18, "v_start": 1,
                                                    "v_end": None, "ch_end": 18}]),
                                  {"G-GT.refs"}),
    "an unclosed quote": (_set(2, "reference_answer", "保羅說：「你們作兒女的"),
                          {"G-GT.quote", "G-GT.changes"}),
    "omitted slot counted as gold": (_set(0, "gold_slots", ["mat.18.1", "mat.18.2", "mat.18.3",
                                                            "mat.18.4"]), {"G-GT.gold"}),
    "omitted slot not listed": (_set(0, "omitted_slots", []), {"G-GT.gold"}),
    "a quote that is not service text": (_set(2, "reference_answer", "保羅說：「要聽從父母」"),
                                         {"G-GT.quote", "G-GT.changes"}),
    "a CUNP spelling in an answer": (_set(1, "expected_answer_points", ["往大馬色去", "詵過小河"]),
                                     {"G-GT.spelling", "G-GT.changes"}),
    "question text changed": (_set(0, "question", "誰是最大的？"), {"G-GT.v1", "G-GT.changes"}),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_damage_is_caught_by_its_check(corpus, built, case):
    change, expected = CASES[case]
    report = check_gt(_inputs(corpus, built, doc=_mutated(built, change)))
    assert _failed(report) - {"G-GT.freeze"} == expected
    assert not report.passed


def test_a_question_text_spelling_is_exempt_from_the_spelling_check(corpus, built):
    v1 = gt_fixture.v1()
    v1["questions"][1]["question"] = "掃羅往大馬色去做甚麼？"
    doc = copy.deepcopy(built.doc)
    doc["questions"][1]["question"] = v1["questions"][1]["question"]
    assert "G-GT.spelling" not in _failed(check_gt(_inputs(corpus, built, doc=doc, v1=v1)))


def test_an_unused_quote_exemption_fails(corpus, built):
    doc = copy.deepcopy(built.doc)
    doc["metadata"]["quote_exempt"].append({"qid": "VERSE_LOOKUP_001", "field": "reference_answer",
                                            "quote": "不存在", "reason": "x"})
    assert "G-GT.quote" in _failed(check_gt(_inputs(corpus, built, doc=doc)))


def test_a_tampered_change_log_fails(corpus, built):
    changes = list(built.changes)
    changes[0] = Change(**{**changes[0].to_json(), "after": "竄改"})
    assert "G-GT.changes" in _failed(check_gt(_inputs(corpus, built, changes=tuple(changes))))


def test_a_stale_freeze_fails(corpus, built):
    freeze = {**freeze_record(built.doc, encode_doc(built.doc)), "sha256": "f" * 64}
    assert _failed(check_gt(_inputs(corpus, built, freeze=freeze))) == {"G-GT.freeze"}


def test_missing_inputs_fail_closed(corpus, built):
    inputs = _inputs(corpus, built)
    bare = GtInputs(doc=inputs.doc, corpus=corpus, vers=inputs.vers)
    assert _failed(check_gt(bare)) == {"G-GT.v1", "G-GT.changes", "G-GT.freeze"}


def test_a_slot_universe_other_than_the_corpus_fails(corpus, built):
    doc = copy.deepcopy(built.doc)
    doc["metadata"]["slot_universe"] = "text@000000000000"
    assert "G-GT.gold" in _failed(check_gt(_inputs(corpus, built, doc=doc)))


def test_a_layer_that_writes_a_listed_form_breaks_the_spelling_table(tmp_path, built):
    files = mini_build.text_layer()
    files["verse_units"][10]["text"] = files["verse_units"][10]["text_pdf"] = "在該撒利亞有一個人。"
    text, _ = mini_build.write_layers(tmp_path, text=files)
    corpus = ServiceText.from_layer(read_layer(text.path))
    report = check_gt(_inputs(corpus, built))
    spelling = next(g for g in report.gates if g.name == "G-GT.spelling")
    assert not spelling.passed
    assert any("該撒" in d for d in spelling.details)


def test_locality_lists_quotes_from_outside_the_gold_verses_without_failing_the_gt(corpus, built):
    doc = copy.deepcopy(built.doc)
    doc["questions"][2]["reference_answer"] += "又說：「你們作父親的，不要惹兒女的氣」，「飲食」。"
    report = check_gt(_inputs(corpus, built, doc=doc))
    locality = _gate(report, "G-GT.locality")
    assert not locality.hard and not locality.passed
    assert locality.details == (
        "TOPIC_QUESTION_021 reference_answer: 「你們作父親的」 → eph.6.4",
        "TOPIC_QUESTION_021 reference_answer: 「不要惹兒女的氣」 → eph.6.4")
    assert locality.observed == {"clauses": 2, "questions": 1, "unchecked": 0}
    assert _failed(report) == {"G-GT.changes", "G-GT.freeze"}


def test_locality_accepts_the_pdf_glyph_of_an_errata_position_inside_gold(corpus, built):
    answer = built.doc["questions"][1]["reference_answer"]
    assert "詵過小河" in answer
    assert _gate(check_gt(_inputs(corpus, built)), "G-GT.locality").observed["clauses"] == 0


@pytest.mark.parametrize("change", [
    _set(2, "reference_answer", "保羅說：「你們作兒女的"),
    _set(2, "gold_slots", ["eph.9.9"]),
])
def test_locality_reports_what_it_could_not_check(corpus, built, change):
    report = check_gt(_inputs(corpus, built, doc=_mutated(built, change)))
    locality = _gate(report, "G-GT.locality")
    assert locality.observed["unchecked"] == 1 and not locality.passed
    assert locality.details[0].startswith("TOPIC_QUESTION_021")

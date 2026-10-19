"""ragcommon.regnal's S4 guard (2026-10-19): ``View.alts`` holds the other book's age and reign
values from the layer's conflicts, and ``born_guard`` passes a seed's born_under answer only
when it keeps ≥ MIN_BORN_MARGIN years from both ends of the reign (G1) and every alternative
value, put in one at a time, names the same king with that margin (G3). born_under is not
changed. Synthetic layers only; the kings and numbers are made up."""

from __future__ import annotations

import copy

import pytest

from ragcommon import regnal

# Judah 甲 -> 乙 -> 丙 -> 丁 (the seed), reigns 40, 20, 10; 丁 comes to the throne at `age`.
REIGNS = {"J1": 40, "J2": 20, "J3": 10}
NAMES = {"J1": "甲", "J2": "乙", "J3": "丙", "J4": "丁"}


def _node(i: str, order: int, reign=None, age=None, **more) -> dict:
    fields = {}
    if reign is not None:
        fields["reign"] = [reign, f"2ki.{order}.1", "ki"]
    if age is not None:
        fields["age"] = [age, f"2ki.{order}.2", "ki"]
    for f, v in more.items():
        fields[f] = [v, f"2ki.{order}.3", "ki"]
    return {"id": i, "kingdom": "J", "name": NAMES.get(i, i), "aliases": [], "fields": fields,
            "evidence": [f"2ki.{order}.1"], "pending": False, "order": order, "created_by": "t",
            "has_acc": True}


def _conflict(i: str, field: str, kept, other) -> list:
    return [i, NAMES.get(i, i), field, [kept, "2ki.9.9", "ki"], [other, "2ch.9.9", "ch"]]


def _doc(age=15, conflicts=(), seed_fields=None, extra_nodes=()) -> dict:
    nodes = [_node(i, k, reign=REIGNS[i]) for k, i in enumerate(("J1", "J2", "J3"))]
    nodes.append(_node("J4", 3, reign=5, age=age, **(seed_fields or {})))
    nodes += list(extra_nodes)
    israel = _node("I1", 10, reign=12)
    israel["kingdom"] = "I"
    return {"policy": "occ", "fn_rule": "slot", "nodes": nodes + [israel],
            "edges": [["J1", "J2", "son", "1ki.1.1"], ["J2", "J3", "son", "1ki.1.2"],
                      ["J3", "J4", "son", "1ki.1.3"]],
            "fallback_edges": [], "syncs": [], "conflicts": [list(c) for c in conflicts], "log": [],
            "occ_alias": [], "union_classes": None}


def _view(**kw) -> regnal.View:
    return regnal.load(_doc(**kw))


def test_the_alts_hold_the_other_books_age_and_reign_values_only():
    ghost = {"id": "J9", "kingdom": "J", "name": "戊", "aliases": [], "fields": {}, "evidence": [],
             "pending": False, "order": 9, "created_by": "t", "has_acc": False}
    V = _view(conflicts=[_conflict("J4", "age", 15, 5), _conflict("J3", "reign", 10, 16),
                         _conflict("J3", "reign", 10, 8), _conflict("J4", "mother", "某", "某某"),
                         _conflict("J4", "father", "丙", "某"), _conflict("J4", "mother_desc", "某女", "女"),
                         _conflict("J9", "age", 1, 2)],
              extra_nodes=[ghost])
    assert V.alts == {("J4", "age"): [5], ("J3", "reign"): [16, 8]}


def test_a_layer_without_conflicts_has_no_alts():
    assert _view().alts == {}


def test_born_under_is_unchanged_by_the_alts():
    V = _view(conflicts=[_conflict("J4", "age", 15, 5)])
    assert regnal.born_under(V, "J4") == (("J2", 5.0), ["J3", "J2"])


def test_a_safe_answer_passes_the_guard():
    assert regnal.born_guard(_view(age=15), "J4") is None


@pytest.mark.parametrize("age, reason", [(10, "margin"), (29.5, "margin"), (11, None), (29, None)])
def test_the_birth_point_must_keep_a_year_from_both_ends_of_the_reign(age, reason):
    # rem = age − 10 years into 乙's 20: margin min(rem, 20 − rem); 1.0 is enough
    V = _view(age=age)
    assert regnal.born_under(V, "J4")[0][0] == "J2"
    assert regnal.born_guard(V, "J4") == reason


def test_the_guard_margin_is_one_year():
    assert regnal.MIN_BORN_MARGIN == 1.0


def test_a_seed_age_alternative_naming_another_king_blocks():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 5)])     # 5 falls in 丙's reign
    assert regnal.born_guard(V, "J4") == "alt:J4:age"


def test_a_seed_age_alternative_inside_the_margin_blocks():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 10)])    # 乙 again, but margin 0
    assert regnal.born_guard(V, "J4") == "alt:J4:age"


def test_a_seed_age_alternative_naming_the_same_king_passes():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 20)])    # 乙, margin 10
    assert regnal.born_guard(V, "J4") is None


def test_a_walked_reign_alternative_naming_another_king_blocks():
    V = _view(age=15, conflicts=[_conflict("J3", "reign", 10, 16)])  # 15 < 16: 丙 instead of 乙
    assert regnal.born_guard(V, "J4") == "alt:J3:reign"


def test_the_answering_kings_own_reign_alternative_is_read_too():
    V = _view(age=15, conflicts=[_conflict("J2", "reign", 20, 5.5)])  # 5 into 乙's 5.5: margin 0.5
    assert regnal.born_guard(V, "J4") == "alt:J2:reign"


def test_a_walked_reign_alternative_naming_the_same_king_passes():
    V = _view(age=15, conflicts=[_conflict("J3", "reign", 10, 8)])   # 乙, margin 7
    assert regnal.born_guard(V, "J4") is None


def test_a_reign_alternative_off_the_walked_path_is_not_read():
    V = _view(age=15, conflicts=[_conflict("J1", "reign", 40, 1)])
    assert regnal.born_under(V, "J4")[1] == ["J3", "J2"]
    assert regnal.born_guard(V, "J4") is None


def test_the_alternatives_go_in_one_at_a_time():
    # age 25 alone: 乙, margin 5; 丙 reigning 5 alone: 乙, margin 10; both at once would be 甲
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 25), _conflict("J3", "reign", 10, 5)])
    assert regnal.born_guard(V, "J4") is None


def test_every_alternative_of_a_field_is_tried():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 20), _conflict("J4", "age", 15, 9)])
    assert regnal.born_guard(V, "J4") == "alt:J4:age"


def test_mother_and_father_conflicts_are_not_read():
    V = _view(age=15, seed_fields={"mother": "某", "father": "丙"},
              conflicts=[_conflict("J4", "mother", "某", "某某"), _conflict("J4", "father", "丙", "某"),
                         _conflict("J3", "father", "乙", "某")])
    assert regnal.born_guard(V, "J4") is None


@pytest.mark.parametrize("age, doc_edit", [
    (None, None),                                                   # no accession age
    (100, None),                                                    # before the chain
    (15, lambda d: d["nodes"][1]["fields"].pop("reign")),           # 乙's reign unknown
])
def test_no_king_is_no_line_to_guard(age, doc_edit):
    doc = _doc(age=age)
    if doc_edit:
        doc_edit(doc)
    V = regnal.load(doc)
    assert regnal.born_guard(V, "J4") == "no_king"


def test_an_alternative_that_walks_off_the_chain_blocks():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 90)])
    assert regnal.born_under(V, "J4")[0] == ("J2", 5.0)
    assert regnal.born_guard(V, "J4") == "alt:J4:age"


def test_the_guard_does_not_change_the_view():
    V = _view(age=15, conflicts=[_conflict("J4", "age", 15, 5), _conflict("J3", "reign", 10, 16)])
    before = copy.deepcopy((V.nodes, V.chain, V.alts))
    regnal.born_guard(V, "J4")
    assert (V.nodes, V.chain, V.alts) == before

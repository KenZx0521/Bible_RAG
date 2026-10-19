"""The chronology card's S4 guard (2026-10-19): the engine writes a seed's born line (king at the
seed's birth) only when ``ragcommon.regnal.born_guard`` passes it; the rows born_under walked
stay on the card, the other lines are untouched, and ``guard=False`` is experiment A's engine.
Synthetic layers only; the kings and numbers are made up."""

from __future__ import annotations

import json

import pytest

from utils.regnal import engine
from utils.regnal.layer import parse_layer

# Judah 甲 -> 乙 -> 丙 -> 丁 -> 戊 -> 己 (己 the seed; 丁 -> 戊 a usurpation); Israel 子 -> 丑.
JUDAH = (("J1", "甲", 10), ("J2", "乙", 10), ("J3", "丙", 2), ("J4", "丁", 2), ("J5", "戊", 2), ("J6", "己", 3))
SEED = "J6"
BORN_HEAD = "猶大王己出生時在位的猶大王"


def _layer(age=9, conflicts=(), seed_fields=None):
    def node(i, kd, name, order, reign, **more):
        fields = {"reign": [reign, f"2ki.{order}.1", "ki"]}
        fields.update({f: [v, f"2ki.{order}.2", "ki"] for f, v in more.items()})
        return {"id": i, "kingdom": kd, "name": name, "aliases": [], "fields": fields,
                "evidence": [f"2ki.{order}.1"], "pending": False, "order": order, "created_by": "t",
                "has_acc": True}
    nodes = [node(i, "J", nm, k, r, **({"age": age, **(seed_fields or {})} if i == SEED and age else {}))
             for k, (i, nm, r) in enumerate(JUDAH)]
    nodes += [node("I1", "I", "子", 10, 12), node("I2", "I", "丑", 11, 22)]
    edges = [[a[0], b[0], "usurp" if a[0] == "J4" else "son", "1ki.1.1"] for a, b in zip(JUDAH, JUDAH[1:])]
    doc = {"policy": "occ", "fn_rule": "slot", "nodes": nodes,
           "edges": edges + [["I1", "I2", "son", "1ki.2.1"]], "fallback_edges": [], "syncs": [],
           "conflicts": [list(c) for c in conflicts], "log": [], "occ_alias": [], "union_classes": None}
    return parse_layer(json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")).view


def _conflict(i, field, kept, other):
    return [i, dict((x, n) for x, n, _r in JUDAH)[i], field, [kept, "2ki.9.9", "ki"], [other, "2ch.9.9", "ch"]]


def _born(card: dict) -> list[str]:
    return [p for (h, p) in card["lines"] if "出生時在位" in h]


def test_a_safe_birth_point_writes_the_born_line():
    card = engine.cards(_layer(age=9), [SEED])          # 9 − 6 = 3 years into 乙's 10: margin 3
    assert _born(card) == ["乙"]


def test_a_birth_point_within_a_year_of_the_reigns_end_writes_no_born_line():
    card = engine.cards(_layer(age=6), [SEED])          # 6 − 6 = 0 into 乙's 10: margin 0
    assert _born(card) == []
    assert _born(engine.cards(_layer(age=6), [SEED], guard=False)) == ["乙"]


def test_a_seed_age_alternative_naming_another_king_writes_no_born_line():
    V = _layer(age=9, conflicts=[_conflict(SEED, "age", 9, 5)])   # 5 − 4 = 1 into 丙's 2: 丙
    assert _born(engine.cards(V, [SEED])) == []


def test_a_walked_reign_alternative_naming_another_king_writes_no_born_line():
    V = _layer(age=9, conflicts=[_conflict("J3", "reign", 2, 6)])  # 9 − 4 = 5 < 6: 丙
    assert _born(engine.cards(V, [SEED])) == []


def test_an_alternative_naming_the_same_king_keeps_the_born_line():
    V = _layer(age=9, conflicts=[_conflict(SEED, "age", 9, 12), _conflict("J4", "reign", 2, 1)])
    assert _born(engine.cards(V, [SEED])) == ["乙"]


def test_mother_and_father_conflicts_do_not_touch_the_born_line():
    V = _layer(age=9, seed_fields={"mother": "某", "father": "戊"},
               conflicts=[_conflict(SEED, "mother", "某", "某某"), _conflict(SEED, "father", "戊", "某"),
                          _conflict("J5", "father", "丁", "某")])
    assert _born(engine.cards(V, [SEED])) == ["乙"]


def test_a_blocked_born_line_keeps_the_rows_it_walked():
    V = _layer(age=6)
    on, off = engine.cards(V, [SEED]), engine.cards(V, [SEED], guard=False)
    assert "J2" in on["rows_read"] and engine.distance(V, "J2", [SEED]) == 4   # read by the walk only
    assert on["rows_read"] == off["rows_read"] and on["rows"] == off["rows"]
    assert "猶大王乙" in on["g_block"]


@pytest.mark.parametrize("seeds", [[SEED], ["J3", SEED], [SEED, "I2"]])
def test_the_guard_takes_off_only_the_blocked_born_lines(seeds):
    V = _layer(age=6)
    read_on, lines_on, tags_on = engine.derive(V, seeds)
    read_off, lines_off, tags_off = engine.derive(V, seeds, guard=False)
    assert read_on == read_off
    kept = [(ln, t) for ln, t in zip(lines_off, tags_off) if t != ["born", SEED, None]]
    assert list(zip(lines_on, tags_on)) == kept and len(kept) == len(lines_off) - 1


def test_the_successor_usurper_and_gap_lines_stay():
    _read, _lines, tags = engine.derive(_layer(age=6), ["J3", SEED])
    assert {t[0] for t in tags} == {"succ", "usurper", "gap"}


def test_the_guard_is_on_by_default():
    V = _layer(age=6, conflicts=[_conflict("J3", "reign", 2, 6)])
    assert engine.cards(V, [SEED]) == engine.cards(V, [SEED], guard=True)
    assert engine.derive(V, [SEED]) == engine.derive(V, [SEED], guard=True)


def test_the_guard_changes_nothing_where_it_passes():
    V = _layer(age=9, conflicts=[_conflict("J4", "reign", 2, 1)])
    for seeds in ([SEED], ["J3", SEED], [SEED, "I2"]):
        assert engine.cards(V, seeds) == engine.cards(V, seeds, guard=False)


ROWS_J = ("猶大王乙：在位10年；繼位：子繼父", "猶大王丙：在位2年；繼位：子繼父",
          "猶大王丁：在位2年；繼位：子繼父", "猶大王戊：在位2年；繼位：篡位")
BEFORE_J6 = ("猶大王己之前第3位猶大王：丙（在位2年）", "猶大王己之前第2位猶大王：丁（在位2年）",
             "猶大王己之前第1位猶大王：戊（在位2年）")
# experiment A's engine (engine.py before the guard) printed these cards on the layers above
UNGUARDED = [
    ("margin", 6, None, ["J6"], (
        *ROWS_J, "猶大王己：在位3年；登基6歲；繼位：子繼父", "依上列資料推算：", *BEFORE_J6,
        "猶大王己出生時在位的猶大王（依登基6歲往回累加前任在位年數）：乙")),
    ("walked_reign", 9, ("J3", "reign", 2, 6), ["J3", "J6"], (
        "猶大王甲：在位10年", *ROWS_J, "猶大王己：在位3年；登基9歲；繼位：子繼父", "依上列資料推算：",
        "猶大王丙之前第2位猶大王：甲（在位10年）", "猶大王丙之前第1位猶大王：乙（在位10年）",
        "猶大王丙之後第1位猶大王：丁（在位2年）", "猶大王丙之後第2位猶大王：戊（在位2年）",
        "猶大王丙之後第3位猶大王：己（在位3年，登基9歲）", "猶大王丙之後第1個篡位者：戊（在位2年）",
        *BEFORE_J6, "猶大王己出生時在位的猶大王（依登基9歲往回累加前任在位年數）：乙",
        "猶大王丙到猶大王己相隔：3代王位")),
    ("passes", 9, None, ["J6", "I2"], (
        *ROWS_J, "猶大王己：在位3年；登基9歲；繼位：子繼父", "以色列王子：在位12年",
        "以色列王丑：在位22年；繼位：子繼父", "依上列資料推算：", *BEFORE_J6,
        "猶大王己出生時在位的猶大王（依登基9歲往回累加前任在位年數）：乙",
        "以色列王丑之前第1位以色列王：子（在位12年）")),
    ("seed_age", 9, ("J6", "age", 9, 5), ["J6"], (
        *ROWS_J, "猶大王己：在位3年；登基9歲；繼位：子繼父", "依上列資料推算：", *BEFORE_J6,
        "猶大王己出生時在位的猶大王（依登基9歲往回累加前任在位年數）：乙")),
]


@pytest.mark.parametrize("age, conflict, seeds, lines", [c[1:] for c in UNGUARDED], ids=[c[0] for c in UNGUARDED])
def test_without_the_guard_the_card_is_experiment_as(age, conflict, seeds, lines):
    V = _layer(age=age, conflicts=[_conflict(*conflict)] if conflict else [])
    assert engine.cards(V, seeds, guard=False)["g_block"] == "\n".join(lines)

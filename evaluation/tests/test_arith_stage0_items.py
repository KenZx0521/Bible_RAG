"""Ordered-chain arithmetic stage-0: the item builder (items_x.py, units_x.py; prereg §3, §5 干擾值, K0-1/K0-2).

Unit tests use made-up candidates, names and numbers. The store tests build the 52 items from the
reference layer v2, the r4 layer and the text layer and skip when the store is not mounted; they
assert counts, rules and checks only, never question text or gold values. Nothing writes the store
or calls an LLM.
"""

import collections
import random
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import x_common as X  # noqa: E402
import items_x as I  # noqa: E402
import units_x as U  # noqa: E402

needs_store = pytest.mark.skipif(not X.REF_V2.is_file() or not X.R4_LAYER.is_file()
                                 or not (X.TEXT / "verse_units.jsonl").is_file(),
                                 reason=f"store not mounted ({X.REF_V2})")


# ---------------------------------------------------------------- unit tests (no store)
def test_draw_meets_quotas_and_constraints():
    cands = [dict(s=s, v=v, a=a) for s in "ab" for v in range(6) for a in "xyz"]
    pick = I.draw(cands, random.Random(1), {"a": 3, "b": 2}, lambda c: c["s"],
                  distinct=lambda c: c["v"], cap=lambda c: c["a"], cap_n=2)
    assert collections.Counter(c["s"] for c in pick) == {"a": 3, "b": 2}
    assert len({c["v"] for c in pick}) == 5
    assert max(collections.Counter(c["a"] for c in pick).values()) <= 2
    again = I.draw(cands, random.Random(1), {"a": 3, "b": 2}, lambda c: c["s"],
                   distinct=lambda c: c["v"], cap=lambda c: c["a"], cap_n=2)
    assert again == pick


def test_draw_finds_the_only_solution_and_refuses_impossible():
    cands = [dict(s=2, a="p"), dict(s=2, a="p"), dict(s=3, a="p"), dict(s=3, a="q"), dict(s=2, a="q")]
    pick = I.draw(cands, random.Random(7), {2: 2, 3: 1}, lambda c: c["s"], cap=lambda c: c["a"], cap_n=2)
    assert sorted((c["s"], c["a"]) for c in pick) in ([(2, "p"), (2, "q"), (3, "p")],
                                                       [(2, "p"), (2, "q"), (3, "q")],
                                                       [(2, "p"), (2, "p"), (3, "q")])
    with pytest.raises(ValueError):
        I.draw(cands, random.Random(7), {2: 4}, lambda c: c["s"])


def test_answer_class_numbers():
    q = "甲到乙（含首尾）一共幾年？第二位王；創世記11章10節；以子生於某事之後二年"
    assert I.answer_class_numbers(q, ["Y"]) == [(2, "年")]
    assert I.answer_class_numbers("甲三十歲時乙幾歲", ["A", "Y"]) == [(30, "歲")]
    assert I.answer_class_numbers("在位40年又1,041年", ["Y"]) == [(40, "年"), (1041, "年")]
    assert I.answer_class_numbers("甲幾歲時，乙出生？", ["A", "Y"]) == []
    assert I.numbers_in_text("第三位，七十歲，12年") == [3, 70, 12]


def test_cn_value_matches_cards_common():
    for n in range(1, 1000):
        s = I.int2cn(n)
        assert I.cn_value(s) == n == X.cc.cn2int(s)
    assert I.cn_value("一百零五") == 105 and I.cn_value("十三") == 13 and I.cn_value("九百一十二") == 912


def test_distractor_list_dedupes_and_never_gold():
    ds = I.distractor_list(50, [(10, "component"), (40, "component"), (50, "drop_first"), (40, "drop_last"),
                                (0, "nonacc"), (49, "off_by_one"), (51, "off_by_one")])
    assert ds == [{"value": 10, "kind": "component"}, {"value": 40, "kind": "component"},
                  {"value": 49, "kind": "off_by_one"}, {"value": 51, "kind": "off_by_one"}]


def test_gen_display_names_homonyms_off_the_path(monkeypatch):
    nodes = [dict(id=f"G05.{i:02d}", name=n, chapter=5, order=i, fields={}) for i, n in enumerate("甲乙丙丁")]
    gen = {"nodes": nodes}
    monkeypatch.setattr(I, "GEN_HOMONYMS", ("乙",))
    assert I.gen_display(gen, "G05.01", "X") == "甲的兒子乙"
    assert I.gen_display(gen, "G05.01", "Y") == "丙的父親乙"
    assert I.gen_display(gen, "G05.02", "X") == "丙"


def test_units_node_and_edge():
    chains = {"I": ["a", "b", "c", "d", "e", "f", "g"]}
    segs = (("b", "d"), ("e", "g"))
    assert U.node_units(["b", "c", "d"], chains, segs) == (["b-d"], True)
    assert U.node_units(["c", "d", "e"], chains, segs) == (["b-d", "e-g"], False)
    assert U.node_units(["a"], chains, segs) == ([], False)
    gch = {5: ["p", "q", "r", "s", "t"]}
    gseg = (("p", "r"), ("r", "t"))
    assert U.edge_units(["p", "q", "r"], gch, gseg) == (["p-r"], True)
    assert U.edge_units(["q", "r", "s"], gch, gseg) == (["p-r", "r-t"], False)


# ---------------------------------------------------------------- store tests
@pytest.fixture(scope="module")
def doc():
    return I.build_items()


@pytest.fixture(scope="module")
def items(doc):
    return doc["items"]


def by_qtype(items, *qts):
    return [it for it in items if it["qtype"] in qts]


@needs_store
def test_counts_and_checks(doc, items):
    assert doc["seed"] == X.SEED and doc["n_items"] == len(items) == 52
    assert collections.Counter(it["family"] for it in items) == {"DYN": 14, "S6": 4, "SYNC": 16, "GEN": 18}
    assert collections.Counter(it["qtype"] for it in items) == {"S5": 14, "S6": 4, "SYNC2": 8, "SYNC3": 8,
                                                                 "F1": 12, "F3": 4, "F5": 2}
    assert all(v == [] for v in doc["checks"].values()), doc["checks"]
    assert doc["pools"] == I.POOLS
    assert len({it["id"] for it in items}) == 52


@needs_store
def test_every_gold_verified_and_k0_1(items):
    for it in items:
        assert I.verify_gold(it) == [], it["id"]
        if it["family"] != "GEN":
            assert I.k0_fields(it) == [], it["id"]


@needs_store
def test_verify_gold_catches_tampering(items):
    for qt in ("S5", "S6", "F1", "F3", "F5"):
        it = by_qtype(items, qt)[0]
        bad = dict(it, gold=it["gold"] + 1, keys=[dict(it["keys"][0], value=it["gold"] + 1)])
        assert I.verify_gold(bad), qt
    sy = by_qtype(items, "SYNC2")[0]
    assert I.verify_gold(dict(sy, gold={"Y": sy["gold"]["Z"], "Z": sy["gold"]["Y"]}))
    gen = by_qtype(items, "F1")[0]
    assert I.verify_gold(dict(gen, path_names=gen["path_names"][::-1]))
    s5 = by_qtype(items, "S5")[0]
    assert I.k0_fields(dict(s5, path=s5["path"][::-1]))


@needs_store
def test_s5_quotas_and_exclusions(items):
    s5 = by_qtype(items, "S5")
    assert collections.Counter((it["kingdom"], it["L"]) for it in s5) == I.S5_QUOTA
    assert len({it["gold"] for it in s5}) == 14
    for it in s5:
        assert not set(it["path_ref"]) & (set(I.PART_YEAR) | {I.ATHALIAH})
        assert it["seeds_ref"][0] not in I.JEROBOAM and it["seeds_ref"][1] not in I.JEROBOAM
        assert len(it["path"]) == it["L"] and it["seeds"] == [it["path"][0], it["path"][-1]]
    assert sum(not it["nested"] for it in s5) >= 10


@needs_store
def test_s6_pairs(items):
    assert sorted(tuple(it["seeds_ref"]) for it in by_qtype(items, "S6")) == sorted(I.S6_PAIRS)


@needs_store
def test_sync_quotas_and_exclusions(items):
    sy = by_qtype(items, "SYNC2", "SYNC3")
    assert collections.Counter(it["k"] for it in sy) == I.SYNC_QUOTA
    assert max(collections.Counter(it["z_ref"] for it in sy).values()) <= I.SYNC_MAX_PER_ANSWER
    for it in sy:
        assert it["path_ref"][-1] not in I.SYNC_BAD_TARGETS and I.ATHALIAH not in it["path_ref"]
        assert it["seeds_ref"][0] not in I.JEROBOAM and len(it["seeds"]) == 1
        assert not {it["gold"]["Y"], it["gold"]["Z"]} & set(I.SYNC_HOMONYM_ANSWERS)
        assert [k["role"] for k in it["keys"]] == ["Y", "Z"]
        assert all(it["gold"][k["role"]] in k["accept"] for k in it["keys"])


@needs_store
def test_gen_quotas_and_exclusions(items):
    import gen_layer as G
    gen = G.build()
    f1, f3, f5 = by_qtype(items, "F1"), by_qtype(items, "F3"), by_qtype(items, "F5")
    assert sum(it["chapter"] == 11 for it in f1) >= 6
    assert sum(it["pool"] == "c5m" for it in f1) >= 4
    assert all(2 <= len(it["path"]) - 1 <= 4 for it in f1)
    assert all(it["seeds"][0] in G.chain(gen, 11)[2:] and it["path"][0] == "G11.00" for it in f3)
    for it in f5:
        x, y = it["seeds"]
        assert len(it["path"]) - 1 >= 2 and G.node(gen, x)["name"] != I.ENOCH
        assert 0 < it["gold"] < G.total(gen, y)
        assert G.node(gen, x)["chapter"] == G.node(gen, y)["chapter"]
    for it in f1 + f3 + f5:
        assert it["gold"] < 1000 and it["gold"] not in I.FAMOUS
        assert it["keys"][0]["ordinal"] is (it["qtype"] == "F3")
    assert sum(not it["nested"] for it in f1 + f3 + f5) >= 7


@needs_store
def test_questions_carry_no_answer_class_number(items):
    for it in items:
        if it["family"] == "SYNC":
            continue
        found = I.answer_class_numbers(it["question"], it["keys"][0]["classes"])
        allowed = [(it["flood_offset"], "年")] if it["qtype"] == "F3" else []
        assert found == allowed, it["id"]
        assert it["gold"] not in I.numbers_in_text(it["question"]), it["id"]


@needs_store
def test_distractors_never_gold(items):
    for it in items:
        vals = [d["value"] for d in it["distractors"]]
        assert len(vals) == len(set(vals))
        assert it["gold"] not in vals
        assert it["family"] == "SYNC" or vals


@needs_store
def test_gen_homonyms_named_off_the_path(items):
    import gen_layer as G
    gen = G.build()
    for it in by_qtype(items, "F1", "F3", "F5"):
        path_names = {G.node(gen, z)["name"] for z in it["path"]}
        for nid, shown in zip(it["seeds"], it["seed_display"]):
            name = G.node(gen, nid)["name"]
            if name in I.GEN_HOMONYMS:
                helper = shown.split("的")[0]
                assert shown.endswith(name) and helper != name and helper not in path_names, it["id"]
            else:
                assert shown == name


@needs_store
def test_seeds_sources_and_units(items):
    V4 = X.r4_view()
    for it in items:
        assert len(it["seeds"]) == (1 if it["qtype"] in ("SYNC2", "SYNC3", "F3") else 2)
        assert len(it["sources"]) == 1 and it["context_from"] == it["sources"][0]["id"]
        if it["family"] == "GEN":
            assert it["context_from"] in ("ps:gen.5.1", "ps:gen.11.10")
        else:
            assert all(s in V4.nodes for s in it["seeds"] + it["path"])
            assert it["tcanon_complete"] in (True, False)
        assert isinstance(it["units_touched"], list) and isinstance(it["nested"], bool)


@needs_store
def test_deterministic(doc):
    assert I.items_sha256(I.build_items()) == I.items_sha256(doc)
    assert I.items_sha256(I.build_items(seed=X.SEED + 1)) != I.items_sha256(doc)


@needs_store
def test_write_refuses_the_repo_and_round_trips(doc, tmp_path):
    with pytest.raises(SystemExit):
        I.write(doc, _DIR / "items.json")
    p = I.write(doc, tmp_path / "items.json")
    assert I.load(p) == doc

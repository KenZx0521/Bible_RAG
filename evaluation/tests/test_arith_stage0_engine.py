"""Ordered-chain arithmetic stage-0, arms G and T-rows (engine_x.py; prereg §4, §6 K0-3 and K0-6).

The synthetic tests run on a small two-kingdom regnal layer, read the prod way (ragcommon.regnal.load)
and through experiment A's reference reader (load_ref), and on a small Genesis-shaped layer in the SPEC
schema; every name and number in them is made up. The store-backed tests read the r4 layer and the
reference layer v2 (and the store's gen_layer.json once it exists); they skip when the store is not
mounted, compute every expected value from the reference layer, and print no card text. Nothing here
calls Ollama.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import engine_x as E  # noqa: E402
import x_common as X  # noqa: E402

STORE_OK = X.REF_V2.is_file() and X.R4_LAYER.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({X.REF_V2})")
TEXT_OK = (X.TEXT / "verse_units.jsonl").is_file()
needs_gen = pytest.mark.skipif(not (STORE_OK and (X.GEN_LAYER.is_file() or TEXT_OK)),
                               reason=f"store not mounted ({X.TEXT})")

# ---------------------------------------------------------------- a synthetic regnal layer (made up)
# (reference id, r4 id, name, father, edge into this king, reign, accession age, primary sync (ref id, year))
ISRAEL = (("I01", "A11", "艾德", "老甲", None, 20, None, None),
          ("I02", "A12", "貝恩", "艾德", "son", 3, None, ("J01", 2)),
          ("I03", "A13", "柯林", "老乙", "usurp", 15, None, ("J02", 3)),
          ("I04", "A14", "艾德", "柯林", "son", 9, None, ("J03", 5)),       # same-kingdom homonym of I01
          ("I05", "A15", "戴森", "艾德", "son", 0.5, None, None),           # a part-year reign
          ("I06", "A16", "伊凡", "老丙", "usurp", 11, None, ("J04", 7)),
          ("I07", "A17", "法蘭", "伊凡", "son", 7, None, ("J06", 3)))
JUDAH = (("J01", "A21", "哈特", "老丁", None, 17, 41, None),
         ("J02", "A22", "艾文", "哈特", "son", 3, 20, ("I01", 18)),
         ("J03", "A23", "傑克", "艾文", "son", 25, 30, ("I01", 20)),
         ("J04", "A24", "凱爾", "傑克", "son", 8, 33, ("I04", 4)),
         ("J05", "A25", "藍道", "凱爾", "son", 1, 22, ("I06", 2)),
         ("J06", "A26", "馬丁", "老戊", "installed", 40, 7, ("I06", 8)),
         ("J07", "A27", "尼克", "馬丁", "son", 29, 25, ("I07", 2)))
ROWS = ISRAEL + JUDAH


def r4_doc(rows=ROWS) -> dict:
    """The rows as an r4-format regnal layer (nodes, edges, syncs; ids A..)."""
    r4 = {r[0]: r[1] for r in rows}
    nodes, edges, syncs, prev = [], [], [], {}
    for order, (rid, nid, name, father, edge, reign, age, sync) in enumerate(rows, 1):
        fields = {"reign": [reign, f"syn.{order}.1", "ki"], "father": [father, f"syn.{order}.2", "succ"]}
        if age is not None:
            fields["age"] = [age, f"syn.{order}.1", "ki"]
        nodes.append({"id": nid, "kingdom": rid[0], "name": name, "aliases": [], "order": order, "has_acc": True,
                      "created_by": "t", "pending": False, "evidence": [f"syn.{order}.1"], "fields": fields})
        if edge:
            edges.append([prev[rid[0]], nid, edge, f"syn.{order}.3"])
        if sync:
            syncs.append([nid, r4[sync[0]], sync[1], f"syn.{order}.1", "acc"])
        prev[rid[0]] = nid
    return {"nodes": nodes, "edges": edges, "fallback_edges": [], "syncs": syncs, "conflicts": []}


def ref_list(rows=ROWS) -> list[dict]:
    """The rows as a reference-layer file (experiment A's load_ref format; ids I.. / J..)."""
    out, prev = [], {}
    for order, (rid, _nid, name, father, edge, reign, age, sync) in enumerate(rows, 1):
        out.append({"id": rid, "kingdom": rid[0], "name": name, "father": [father, f"syn.{order}.2"],
                    "pred": [prev.get(rid[0]) if edge else None, edge or "founder", f"syn.{order}.3"],
                    "sync": [[sync[0], sync[1], f"syn.{order}.1", "primary"]] if sync else [],
                    "reign": [str(reign), reign, f"syn.{order}.1"], "age": [age, f"syn.{order}.1"] if age else None,
                    "mother": None, "mother_desc": None, "death": None, "aliases": [], "alt": []})
        prev[rid[0]] = rid
    return out


def load_ref_rows(tmp: Path, rows=ROWS):
    from regnal import load_ref
    p = tmp / "ref.json"
    p.write_text(json.dumps(ref_list(rows), ensure_ascii=False), encoding="utf-8")
    return load_ref(p)


@pytest.fixture(scope="module")
def syn(tmp_path_factory):
    return SimpleNamespace(V=X.backend().regnal.load(r4_doc()), R=load_ref_rows(tmp_path_factory.mktemp("ref")))


def item(seeds, family="DYN", gold=None, classes=None, **kw) -> dict:
    keys = [{"type": "arith", "value": gold, "classes": classes}] if classes else []
    return {"id": "T", "family": family, "seeds": list(seeds), "gold": gold, "keys": keys, **kw}


def texts(c) -> list[str]:
    return [E.line_text(h, p) for h, p in c["lines"]]


# ---------------------------------------------------------------- rendering

def test_the_header_is_experiment_As_and_the_backends():
    import engine as a_engine
    assert E.DERIVED_HEADER == a_engine.DERIVED_HEADER == X.backend().engine.DERIVED_HEADER
    assert E.render(["r1", "r2"], [("頭", "值"), ("", "整行")]) == f"r1\nr2\n{E.DERIVED_HEADER}\n頭：值\n整行"
    assert E.render(["r1"], []) == "r1"


def test_dynasty_rows_are_the_prod_row_text(syn):
    c = E.card(item(["A22", "A25"]), r4=syn.V)
    eng = X.backend().engine
    assert c["t_block"] == "\n".join(eng.row_text(syn.V, y) for y in c["rows"])
    assert c["g_block"].startswith(c["t_block"] + "\n" + E.DERIVED_HEADER + "\n")
    row = eng.row_text(syn.V, "A24")
    assert row in c["t_block"] and row.endswith("於以色列王艾德（柯林的兒子）第4年登基")  # the primary sync


# ---------------------------------------------------------------- dynasty lines and windows

def test_two_seeds_window_and_lines(syn):
    c = E.card(item(["A25", "A22"]), r4=syn.V)          # seed order does not matter
    assert c["rows"] == ["A21", "A22", "A23", "A24", "A25", "A26"]
    assert c["protected_rows"] == ["A22", "A23", "A24", "A25"]
    assert texts(c) == [
        "猶大王艾文到猶大王藍道（含首尾，共4位）在位年數首尾相接合計：37年",
        "猶大王艾文到猶大王藍道之間王位交接3次",
        "猶大王艾文之後第1位猶大王：傑克；傑克登基時對方國在位：艾德（老甲的兒子）（傑克於艾德第20年登基）",
        "猶大王艾文之後第2位猶大王：凱爾；凱爾登基時對方國在位：艾德（柯林的兒子）（凱爾於艾德第4年登基）",
        "猶大王艾文之後第3位猶大王：藍道；藍道登基時對方國在位：伊凡（藍道於伊凡第2年登基）",
        "猶大王藍道之後第1位猶大王：馬丁；馬丁登基時對方國在位：伊凡（馬丁於伊凡第8年登基）",
        "猶大王藍道之後第2位猶大王：尼克；尼克登基時對方國在位：法蘭（尼克於法蘭第2年登基）"]
    assert c["dropped_rows"] == c["dropped_lines"] == 0 and not c["over_cap"]
    assert c["chars_g"] == len(c["g_block"]) and c["chars_t"] == len(c["t_block"])
    assert [t["kind"] for t in c["tags"]] == ["sum", "handover"] + ["succ"] * 5


def test_father_age_line_only_for_an_adjacent_son_edge(syn):
    c = E.card(item(["A23", "A24"], family="S6"), r4=syn.V)
    assert "猶大王傑克生猶大王凱爾時：30歲＋25年−33歲＝22歲" in texts(c)
    assert texts(c)[:2] == ["猶大王傑克到猶大王凱爾（含首尾，共2位）在位年數首尾相接合計：33年",
                            "猶大王傑克到猶大王凱爾之間王位交接1次"]
    for seeds in (["A25", "A26"], ["A22", "A24"]):      # installed edge; not adjacent
        assert not any(t["kind"] == "father_age" for t in E.card(item(seeds), r4=syn.V)["tags"])


def test_no_sum_line_over_a_part_year_reign(syn):
    c = E.card(item(["A14", "A16"]), r4=syn.V)
    kinds = [t["kind"] for t in c["tags"]]
    assert "sum" not in kinds and kinds[0] == "handover"
    assert texts(c)[0] == "以色列王艾德（柯林的兒子）到以色列王伊凡之間王位交接2次"


def test_one_seed_window_and_successor_lines(syn):
    c = E.card(item(["A12"], family="SYNC"), r4=syn.V)
    assert c["rows"] == ["A11", "A12", "A13", "A14", "A15", "A16"]       # X-1 .. X+4
    assert c["protected_rows"] == ["A12", "A13", "A14", "A15"]           # X .. X+3
    assert texts(c) == [
        "以色列王貝恩之後第1位以色列王：柯林；柯林登基時對方國在位：艾文（柯林於艾文第3年登基）",
        "以色列王貝恩之後第2位以色列王：艾德（柯林的兒子）；艾德登基時對方國在位：傑克（艾德於傑克第5年登基）",
        "以色列王貝恩之後第3位以色列王：戴森"]                               # no primary sync: the name only
    assert [t["value"] for t in c["tags"]] == [{"Y": "柯林", "Z": "艾文"}, {"Y": "艾德", "Z": "傑克"},
                                               {"Y": "戴森", "Z": None}]


def test_windows_are_clipped_at_the_chain_ends(syn):
    c = E.card(item(["A16"], family="SYNC"), r4=syn.V)
    assert c["rows"] == ["A15", "A16", "A17"] and c["protected_rows"] == ["A16", "A17"]
    assert texts(c) == ["以色列王伊凡之後第1位以色列王：法蘭；法蘭登基時對方國在位：馬丁（法蘭於馬丁第3年登基）"]
    c = E.card(item(["A21", "A23"]), r4=syn.V)
    assert c["rows"] == ["A21", "A22", "A23", "A24"]


@pytest.mark.parametrize("seeds", [["A21", "A22", "A23"], ["A21", "A12"], ["A21", "A21"], []])
def test_bad_dynasty_seeds_raise(syn, seeds):
    with pytest.raises(ValueError):
        E.card(item(seeds), r4=syn.V)


def test_covered(syn):
    assert E.card(item(["A22", "A25"], gold=37, classes=["Y"]), r4=syn.V)["covered"]
    assert not E.card(item(["A22", "A25"], gold=38, classes=["Y"]), r4=syn.V)["covered"]
    assert not E.card(item(["A22", "A25"], gold=3, classes=["Y"]), r4=syn.V)["covered"]   # a hand-over count
    assert E.card(item(["A23", "A24"], family="S6", gold=22, classes=["A", "Y"]), r4=syn.V)["covered"]
    assert E.card(item(["A12"], family="SYNC", gold={"Y": "艾德", "Z": "傑克"}), r4=syn.V)["covered"]
    assert not E.card(item(["A12"], family="SYNC", gold={"Y": "艾德", "Z": "艾文"}), r4=syn.V)["covered"]


def test_cap_drops_successor_lines_largest_k_first_then_outer_rows(syn):
    it = item(["A22", "A25"])
    full = E.card(it, r4=syn.V)
    order, c = [], full
    for _ in range(12):
        nxt = E.card(it, r4=syn.V, cap=c["chars_g"] - 1)
        gone_lines = [t for t in texts(c) if t not in texts(nxt)]
        gone_rows = [y for y in c["rows"] if y not in nxt["rows"]]
        if not gone_lines and not gone_rows:
            break
        order.append(gone_lines[0][:10] if gone_lines else gone_rows[0])
        assert len(gone_lines) + len(gone_rows) == 1
        assert nxt["t_block"] == E.render([X.backend().engine.row_text(syn.V, y) for y in nxt["rows"]], [])
        c = nxt
    assert order == ["猶大王艾文之後第3位", "猶大王藍道之後第2位", "猶大王艾文之後第2位",
                     "猶大王藍道之後第1位", "猶大王艾文之後第1位", "A26", "A21"]
    tiny = E.card(it, r4=syn.V, cap=1)
    assert tiny["rows"] == tiny["protected_rows"] == ["A22", "A23", "A24", "A25"]
    assert [t["kind"] for t in tiny["tags"]] == ["sum", "handover"]
    assert tiny["over_cap"] and tiny["dropped_rows"] == 2 and tiny["dropped_lines"] == 5
    assert any("chars" in p for p in E.check_card(it, tiny, cap=1)) and E.check_card(it, tiny) == []


# ---------------------------------------------------------------- dynasty checks

def test_check_lines_and_card_pass_on_clean_cards(syn):
    for seeds, fam in ((["A22", "A25"], "DYN"), (["A23", "A24"], "S6"), (["A12"], "SYNC"), (["A16"], "SYNC"),
                       (["A14", "A16"], "DYN"), (["A11", "A13"], "DYN")):
        it = item(seeds, family=fam)
        c = E.card(it, r4=syn.V)
        assert E.check_lines(it, c, ref=syn.R, r4=syn.V) == [], seeds
        assert E.check_card(it, c) == [], seeds


def _plant(c, i, old, new):
    """The card with old -> new in line i's rendered text (head and payload split again at the first 「：」)."""
    c = copy.deepcopy(c)
    h, p = c["lines"][i]
    text = E.line_text(h, p)
    assert old in text
    text = text.replace(old, new)
    c["lines"][i] = list(text.partition("：")[::2]) if h else ["", text]
    return c


PLANTED = [  # (seeds, line index, old, new)
    (["A22", "A25"], 0, "37年", "38年"), (["A22", "A25"], 0, "共4位", "共5位"),
    (["A22", "A25"], 1, "交接3次", "交接4次"), (["A22", "A25"], 1, "猶大王藍道", "猶大王馬丁"),
    (["A22", "A25"], 2, "傑克", "凱爾"), (["A22", "A25"], 2, "艾德（老甲", "柯林（老甲"),
    (["A22", "A25"], 2, "老甲的兒子", "柯林的兒子"), (["A22", "A25"], 2, "第20年", "第21年"),
    (["A22", "A25"], 2, "第1位", "第2位"), (["A22", "A25"], 2, "猶大王：", "以色列王："),
    (["A23", "A24"], 2, "＝22歲", "＝23歲"), (["A23", "A24"], 2, "30歲＋25年−33歲＝22歲", "31歲＋25年−33歲＝23歲"),
    (["A12"], 2, "戴森", "伊凡"), (["A12"], 1, "艾德（柯林的兒子）；", "艾德（老甲的兒子）；"),
]


@pytest.mark.parametrize("seeds,i,old,new", PLANTED)
def test_check_lines_catches_planted_errors(syn, seeds, i, old, new):
    it = item(seeds)
    bad = _plant(E.card(it, r4=syn.V), i, old, new)
    assert E.check_lines(it, bad, ref=syn.R, r4=syn.V)


def test_check_lines_catches_missing_extra_and_unsynced_lines(syn):
    it = item(["A22", "A25"])
    c = E.card(it, r4=syn.V)
    gone = copy.deepcopy(c)
    del gone["lines"][0], gone["tags"][0]
    assert any("missing" in p for p in E.check_lines(it, gone, ref=syn.R, r4=syn.V))
    extra = copy.deepcopy(c)
    extra["lines"].append(["", "胡亂寫的一行"])
    extra["tags"].append(dict(extra["tags"][0]))
    assert E.check_lines(it, extra, ref=syn.R, r4=syn.V)
    nosync = copy.deepcopy(c)
    nosync["lines"][2][1] = "傑克"
    assert E.check_lines(it, nosync, ref=syn.R, r4=syn.V)
    short = copy.deepcopy(c)
    del short["tags"][-1]
    assert E.check_lines(it, short, ref=syn.R, r4=syn.V)


def test_check_lines_catches_a_reference_disagreement(syn, tmp_path):
    rows = tuple(r if r[0] != "J03" else r[:5] + (26,) + r[6:] for r in ROWS)    # reign 25 -> 26 in the gold
    R = load_ref_rows(tmp_path, rows)
    for seeds in (["A22", "A25"], ["A23", "A24"]):
        it = item(seeds)
        assert E.check_lines(it, E.card(it, r4=syn.V), ref=R, r4=syn.V)
    it = item(["A22", "A25"], seeds_ref=["J02", "J06"])
    assert any("seeds_ref" in p for p in E.check_lines(it, E.card(it, r4=syn.V), ref=syn.R, r4=syn.V))


def test_check_card_catches_structure_errors(syn):
    it = item(["A22", "A25"], gold=37, classes=["Y"])
    c = E.card(it, r4=syn.V)
    for mutate in (lambda d: d["rows"].remove("A23"), lambda d: d.update(t_block=d["t_block"] + "x"),
                   lambda d: d["lines"].pop(), lambda d: d.update(covered=False), lambda d: d.update(chars_g=1)):
        bad = copy.deepcopy(c)
        mutate(bad)
        assert E.check_card(it, bad)


# ---------------------------------------------------------------- a synthetic Genesis layer (made up)
# (id, name, begetting age, remaining years, stated lifespan); G05.06 is the SPEC id of the taken one
CH5 = (("G05.00", "阿岡", 100, 800, 900), ("G05.01", "巴頓", 90, 700, 790), ("G05.02", "卡洛", 80, 600, 680),
       ("G05.03", "丹恩", 70, 50, 120), ("G05.04", "厄文", 60, 500, 560), ("G05.05", "費爾", 50, 700, 750),
       ("G05.06", "葛雷", 65, 235, 300), ("G05.07", "賀伯", 400, None, 800))
CH11 = (("G11.00", "伊安", 90, 400, None), ("G11.01", "杰德", 30, 300, None), ("G11.02", "柯特", 25, 200, None),
        ("G11.03", "路克", 35, 100, None), ("G11.04", "麥斯", 20, None, 150))


def gen_doc(derived_patch=None) -> dict:
    nodes, edges, derived = [], [], {}
    for ch, rows in ((5, CH5), (11, CH11)):
        for order, (gid, name, b, r, t) in enumerate(rows):
            f = {"beget": [b, f"syn.{ch}.{3 * order}"]}
            if r is not None:
                f["remain"] = [r, f"syn.{ch}.{3 * order + 1}"]
            if t is not None:
                f["total"] = [t, f"syn.{ch}.{3 * order + 2}"]
            elif r is not None:
                derived[gid] = b + r
            nodes.append({"id": gid, "name": name, "chapter": ch, "order": order, "fields": f,
                          "flood_offset": [2, "syn.11.0"] if gid == "G11.00" else None})
        edges += [[a[0], b[0], "son", f"syn.{ch}.{3 * i}"] for i, (a, b) in enumerate(zip(rows, rows[1:]))]
    nodes[7]["sons"] = ["伊安", "伊凡", "伊森"]           # a begetting of several sons, the first on the chain
    derived.update(derived_patch or {})
    return {"schema": "arith.gen_layer.v1", "text_digest": "syn", "nodes": nodes, "edges": edges,
            "conflict_edges": [["G05.07", "G11.00", "son", "syn.5.21"]],   # across the chapters: never used
            "flood": {"noah_age": [450, "syn.7.6"]}, "derived": {"total": derived}, "checks": {}}


@pytest.fixture(scope="module")
def gen():
    return gen_doc()


def gitem(seeds, gold=None, classes=None) -> dict:
    return item(seeds, family="GEN", gold=gold, classes=classes)


def test_genesis_rows(gen):
    c = E.card(gitem(["G11.01", "G11.03"]), gen=gen)
    assert c["rows"] == ["G11.00", "G11.01", "G11.02", "G11.03", "G11.04"]      # from the anchored row
    assert c["protected_rows"] == ["G11.00", "G11.01", "G11.02", "G11.03"]
    assert c["t_block"].split("\n") == [
        "伊安：90歲生杰德；杰德生於洪水後2年；生杰德後又活400年",                  # the flood anchor; no derived total
        "杰德：30歲生柯特；生柯特後又活300年", "柯特：25歲生路克；生路克後又活200年",
        "路克：35歲生麥斯；生麥斯後又活100年", "麥斯：20歲生子；共活150歲"]          # no son on the chain
    c = E.card(gitem(["G05.05", "G05.07"]), gen=gen)
    assert c["rows"] == ["G05.04", "G05.05", "G05.06", "G05.07"]                 # never into chapter 11
    assert c["t_block"].split("\n")[0] == "厄文：60歲生費爾；生費爾後又活500年；共活560歲"
    assert c["t_block"].split("\n")[-1] == "賀伯：400歲生伊安；共活800歲"   # several sons: the chain son only (§4)
    assert E.son_name(gen, "G05.07") == "伊安" and E.son_name(gen, "G11.04") is None
    assert "伊凡" not in c["g_block"] and "伊森" not in c["g_block"]


def _row_planted(c, old, new):
    """The card with old -> new in its rows (T-rows and G blocks alike)."""
    assert old in c["t_block"]
    return dict(copy.deepcopy(c), t_block=c["t_block"].replace(old, new), g_block=c["g_block"].replace(old, new))


@pytest.mark.parametrize("old,new", [
    ("賀伯：400歲生伊安", "賀伯：400歲生伊安、伊凡、伊森"),        # every son of the verse, not the chain son only
    ("賀伯：400歲生伊安", "賀伯：400歲生伊凡"),                    # another son
    ("葛雷：65歲生賀伯", "葛雷：66歲生賀伯"),                      # another age
    ("費爾：50歲生葛雷", "費爾：生葛雷"),                          # the begetting field left out
])
def test_genesis_check_lines_checks_the_begetting_field_of_every_row(gen, old, new):
    it = gitem(["G05.05", "G05.07"])
    c = E.card(it, gen=gen)
    assert E.check_lines(it, c, gen) == []
    assert any("begetting field" in p for p in E.check_lines(it, _row_planted(c, old, new), gen))


def test_genesis_check_lines_refuses_a_begetting_the_layer_does_not_have():
    doc = gen_doc()
    y = next(n for n in doc["nodes"] if n["id"] == "G11.04")
    del y["fields"]["beget"]
    it = gitem(["G11.03"])
    c = E.card(it, gen=doc)
    assert c["t_block"].split("\n")[-1] == "麥斯：共活150歲" and E.check_lines(it, c, doc) == []
    bad = _row_planted(c, "麥斯：共活150歲", "麥斯：20歲生子；共活150歲")
    assert any("does not have" in p for p in E.check_lines(it, bad, doc))


GEN_CASES = [  # (seeds, rows, lines)
    (["G05.00", "G05.02"], ["G05.00", "G05.01", "G05.02", "G05.03"],
     ["卡洛出生時阿岡的年齡：190歲", "阿岡的總壽數：900歲", "卡洛在阿岡去世前30年已去世"]),           # M >= T_Y
    (["G05.01", "G05.04"], ["G05.00", "G05.01", "G05.02", "G05.03", "G05.04", "G05.05"],
     ["厄文出生時巴頓的年齡：240歲", "巴頓的總壽數：790歲", "巴頓去世時厄文的年齡：550歲"]),           # 0 < M < T_Y
    (["G05.03", "G05.05"], ["G05.02", "G05.03", "G05.04", "G05.05", "G05.06"],
     ["丹恩的總壽數：120歲", "丹恩在費爾出生前10年去世"]),                                         # M <= 0
    (["G05.06", "G05.07"], ["G05.05", "G05.06", "G05.07"],
     ["賀伯出生時葛雷的年齡：65歲", "葛雷的總壽數：300歲", "葛雷在300歲時被取去"]),                   # X taken
    (["G05.04", "G05.06"], ["G05.03", "G05.04", "G05.05", "G05.06", "G05.07"],
     ["葛雷出生時厄文的年齡：110歲", "厄文的總壽數：560歲", "葛雷在厄文去世前150年已被取去"]),         # Y taken
    (["G11.01", "G11.03"], ["G11.00", "G11.01", "G11.02", "G11.03", "G11.04"],
     ["路克出生時杰德的年齡：55歲", "杰德的總壽數：330歲", "路克在杰德去世前140年已去世",
      "杰德在洪水之後2年出生", "路克在洪水之後57年出生"]),
    (["G11.03", "G11.04"], ["G11.00", "G11.01", "G11.02", "G11.03", "G11.04"],
     ["麥斯出生時路克的年齡：35歲", "路克的總壽數：135歲", "路克去世時麥斯的年齡：100歲",
      "路克在洪水之後57年出生", "麥斯在洪水之後92年出生"]),
    (["G11.00", "G11.02"], ["G11.00", "G11.01", "G11.02", "G11.03"],
     ["柯特出生時伊安的年齡：120歲", "伊安的總壽數：490歲", "柯特在伊安去世前145年已去世",
      "柯特在洪水之後32年出生"]),                                                                 # no flood line for the anchor
    (["G11.03"], ["G11.00", "G11.01", "G11.02", "G11.03", "G11.04"], ["路克在洪水之後57年出生"]),   # F3: anchor .. X+1
    (["G11.00"], ["G11.00", "G11.01"], []),
]


@pytest.mark.parametrize("seeds,rows,lines", GEN_CASES)
def test_genesis_windows_and_lines(gen, seeds, rows, lines):
    it = gitem(seeds)
    c = E.card(it, gen=gen)
    assert c["rows"] == rows and texts(c) == lines
    assert E.check_lines(it, c, gen) == [] and E.check_card(it, c) == []


@pytest.mark.parametrize("total_y,line", [(550, "厄文在巴頓去世前0年已去世"), (551, "巴頓去世時厄文的年齡：550歲")])
def test_genesis_death_line_at_the_lifespan_boundary(total_y, line):
    doc = gen_doc()
    y = next(n for n in doc["nodes"] if n["id"] == "G05.04")
    y["fields"].update(total=[total_y, "syn.5.14"], remain=[total_y - 60, "syn.5.13"])   # M = 550 for 巴頓 -> 厄文
    it = gitem(["G05.01", "G05.04"])
    c = E.card(it, gen=doc)
    assert texts(c)[2] == line and E.check_lines(it, c, doc) == []


def test_genesis_covered(gen):
    assert E.card(gitem(["G05.01", "G05.04"], 240, ["A", "Y"]), gen=gen)["covered"]          # F1
    assert E.card(gitem(["G05.01", "G05.04"], 550, ["A", "Y"]), gen=gen)["covered"]          # F5
    assert not E.card(gitem(["G05.01", "G05.04"], 551, ["A", "Y"]), gen=gen)["covered"]
    assert E.card(gitem(["G11.03"], 57, ["Y"]), gen=gen)["covered"]                          # F3
    assert not E.card(gitem(["G11.03"], 57, ["A"]), gen=gen)["covered"]


@pytest.mark.parametrize("seeds", [["G05.07", "G11.00"], ["G05.01", "G05.02", "G05.03"], ["G05.01", "G05.01"]])
def test_bad_genesis_seeds_raise(gen, seeds):
    with pytest.raises(ValueError):
        E.card(gitem(seeds), gen=gen)


GEN_PLANTED = [  # (seeds, line index or "g", old, new)
    (["G05.01", "G05.04"], 0, "240歲", "241歲"), (["G05.01", "G05.04"], 1, "790歲", "791歲"),
    (["G05.01", "G05.04"], 2, "550歲", "549歲"), (["G05.01", "G05.04"], 2, "550歲", "600歲"),
    (["G05.01", "G05.04"], 0, "時巴頓", "時阿岡"), (["G05.00", "G05.02"], 2, "已去世", "已被取去"),
    (["G05.04", "G05.06"], 2, "已被取去", "已去世"), (["G05.06", "G05.07"], 2, "300歲時", "301歲時"),
    (["G11.01", "G11.03"], 4, "57年", "58年"), (["G11.01", "G11.03"], 3, "杰德在", "伊安在"),
    (["G05.03", "G05.05"], 1, "前10年", "前11年"),
]


@pytest.mark.parametrize("seeds,i,old,new", GEN_PLANTED)
def test_genesis_check_lines_catches_planted_errors(gen, seeds, i, old, new):
    it = gitem(seeds)
    assert E.check_lines(it, _plant(E.card(it, gen=gen), i, old, new), gen)


def test_genesis_check_lines_catches_case_swaps_missing_lines_and_ages_over_lifespan(gen):
    it = gitem(["G05.00", "G05.02"])
    c = E.card(it, gen=gen)
    swapped = copy.deepcopy(c)                     # the M >= T_Y case written as an age at the death
    swapped["lines"][2] = ["阿岡去世時卡洛的年齡", "30歲"]
    swapped["tags"][2] = dict(swapped["tags"][2], kind="death_age")
    assert E.check_lines(it, swapped, gen)
    gone = copy.deepcopy(c)
    del gone["lines"][2], gone["tags"][2]
    assert any("missing" in p for p in E.check_lines(it, gone, gen))
    it = gitem(["G05.01", "G05.04"])
    c = E.card(it, gen=gen)
    old = c["g_block"]
    assert "丹恩：70歲生厄文" in old
    over = dict(copy.deepcopy(c), g_block=old.replace("丹恩：70歲生厄文", "丹恩：170歲生厄文"))
    assert any("lifespan" in p for p in E.check_lines(it, over, gen))


def test_genesis_check_lines_catches_a_wrong_derived_lifespan():
    bad = gen_doc({"G11.01": 331})                 # beget + remain is 330
    it = gitem(["G11.01", "G11.03"])
    assert E.check_lines(it, E.card(it, gen=bad), bad)


# ---------------------------------------------------------------- the store: r4 rows, ref_v2 gold

@pytest.fixture(scope="module")
def real():
    return SimpleNamespace(V=X.r4_view(), R=X.ref_v2_view())


def _whole(r) -> bool:
    return r is not None and r >= 1 and float(r).is_integer()


def s5_candidates(R) -> list[tuple[str, list[str]]]:
    """prereg §3.1: L=3..6 consecutive same-kingdom kings, whole-year reigns, no J07."""
    out = []
    for kd in ("I", "J"):
        ch = R.chain[kd]
        for L in range(3, 7):
            out += [(kd, ch[i:i + L]) for i in range(len(ch) - L + 1)
                    if all(_whole(R.nodes[z]["reign"]) for z in ch[i:i + L]) and "J07" not in ch[i:i + L]]
    return out


def r4_of(real, rid) -> str:
    kd = real.R.nodes[rid]["kingdom"]
    x = real.V.chain[kd][real.R.chain[kd].index(rid)]
    assert real.V.nodes[x]["name"] == real.R.nodes[rid]["name"]
    return x


@needs_store
def test_store_s5_candidates_sum_lines_and_cap(real):
    cands = s5_candidates(real.R)
    assert len(cands) == 56 and sum(kd == "I" for kd, _ in cands) == 24
    for kd, iv in cands:
        gold = sum(real.R.nodes[z]["reign"] for z in iv)
        it = item([r4_of(real, iv[0]), r4_of(real, iv[-1])], gold=gold, classes=["Y"], seeds_ref=[iv[0], iv[-1]])
        c = E.card(it, r4=real.V)
        tag = next(t for t in c["tags"] if t["kind"] == "sum")
        assert tag["value"] == gold and c["covered"]
        assert c["protected_rows"] == [r4_of(real, z) for z in iv]
        assert set(c["protected_rows"]) <= set(c["rows"])
        assert c["dropped_rows"] == c["dropped_lines"] == 0 and c["chars_g"] <= X.CAP_CHARS
        assert E.check_lines(it, c) == [] and E.check_card(it, c) == []


@needs_store
def test_store_s6_clean_pairs(real):
    for f, s in (("J08", "J09"), ("J11", "J12"), ("J13", "J14"), ("J14", "J15")):
        nf, ns = real.R.nodes[f], real.R.nodes[s]
        gold = nf["age"] + nf["reign"] - ns["age"]
        it = item([r4_of(real, f), r4_of(real, s)], family="S6", gold=gold, classes=["A", "Y"], seeds_ref=[f, s])
        c = E.card(it, r4=real.V)
        tag = next(t for t in c["tags"] if t["kind"] == "father_age")
        assert tag["value"] == gold and c["covered"]
        line = texts(c)[c["tags"].index(tag)]
        assert line.endswith(f"：{nf['age']}歲＋{nf['reign']}年−{ns['age']}歲＝{gold}歲")
        assert E.check_lines(it, c) == [] and E.check_card(it, c) == []


@needs_store
def test_store_successor_lines_match_the_reference_syncs(real):
    for kd in ("I", "J"):
        for rid in real.R.chain[kd]:
            it = item([r4_of(real, rid)], family="SYNC")
            c = E.card(it, r4=real.V)
            assert E.check_lines(it, c) == [] and E.check_card(it, c) == [], rid
            for t in c["tags"]:
                y = real.R.succ(rid, t["k"])
                prim = [(o, yr) for (n, o, yr, _v, p) in real.R.syncs if n == y and p]
                assert t["value"]["Y"] == real.R.nodes[y]["name"]
                assert t["value"]["Z"] == (real.R.nodes[prim[0][0]]["name"] if prim else None)
                if prim:
                    assert f"第{prim[0][1]}年登基）" in texts(c)[c["tags"].index(t)]


@needs_store
def test_store_planted_errors_are_caught(real):
    kd, iv = s5_candidates(real.R)[0]
    it = item([r4_of(real, iv[0]), r4_of(real, iv[-1])])
    c = E.card(it, r4=real.V)
    i = next(n for n, t in enumerate(c["tags"]) if t["kind"] == "sum")
    v = c["tags"][i]["value"]
    assert E.check_lines(it, _plant(c, i, f"：{v}年", f"：{v + 1}年"))
    j = next(n for n, t in enumerate(c["tags"]) if t["kind"] == "succ" and t["value"]["Z"])
    z = c["tags"][j]["value"]["Z"]
    other = next(real.V.nodes[x]["name"] for x in real.V.chain["J" if kd == "I" else "I"]
                 if real.V.nodes[x]["name"] != z)
    assert E.check_lines(it, _plant(c, j, f"對方國在位：{z}", f"對方國在位：{other}"))


@needs_store
def test_store_g_block_sizes(real):
    sizes = []
    for kd, iv in s5_candidates(real.R):
        sizes.append(E.card(item([r4_of(real, iv[0]), r4_of(real, iv[-1])]), r4=real.V)["chars_g"])
    for kd in ("I", "J"):
        sizes += [E.card(item([x], family="SYNC"), r4=real.V)["chars_g"] for x in real.V.chain[kd]]
    assert max(sizes) <= X.CAP_CHARS


# ---------------------------------------------------------------- the store: Genesis layer and the items
# The store's gen_layer.json / items.json when they exist, else built in memory from the store (read only).

@pytest.fixture(scope="module")
def real_gen():
    if X.GEN_LAYER.is_file():
        return X.read_json(X.GEN_LAYER)
    import gen_layer
    return gen_layer.build()


@needs_gen
def test_store_genesis_cards_check_clean(real_gen):
    doc = real_gen
    assert doc["nodes"][[n["id"] for n in doc["nodes"]].index(E.TAKEN_ID)]["fields"]["remain"][1] == "gen.5.22"
    for ch in (5, 11):
        chain = E.gen_chain(doc, ch)
        seeds = [[x] for x in chain] + [[chain[i], chain[j]] for i in range(len(chain))
                                         for j in range(i + 2, min(i + 5, len(chain)))]
        for s in seeds:
            it = gitem(s)
            c = E.card(it, gen=doc)
            assert E.check_lines(it, c, doc) == [] and E.check_card(it, c) == [], s
            assert c["chars_g"] <= X.CAP_CHARS and c["dropped_rows"] == c["dropped_lines"] == 0


@needs_gen
def test_store_items_are_covered_and_check_clean(real_gen):
    """K0-3 a = 1.0 and no contradiction, K0-6 on every item's card (prereg §6)."""
    if X.ITEMS.is_file():
        items = X.read_json(X.ITEMS)["items"]
    else:
        import items_x
        items = items_x.build_items(gen=real_gen)["items"]
    assert len(items) == 52
    for it in items:
        c = E.card(it, gen=real_gen)
        assert c["covered"], it["id"]
        assert E.check_lines(it, c, real_gen) == [] and E.check_card(it, c) == [], it["id"]
        assert c["dropped_rows"] == c["dropped_lines"] == 0

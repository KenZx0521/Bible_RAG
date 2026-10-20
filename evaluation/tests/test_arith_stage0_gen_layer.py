"""Ordered-chain arithmetic stage-0: the Genesis layer (gen_layer.py, prereg §2 創世記層, K0-2).

Synthetic tests run on a made-up text layer (names 甲乙丙…, invented numbers, the formula words only, so
that this file shares no 8-character window with any verse of the store's text layer: prereg §1, checked
below); the store tests rebuild the real layer from the text layer and skip when the store is not mounted.
Nothing here writes the store or calls an LLM.
"""

import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import gen_layer as G  # noqa: E402
import x_common as X  # noqa: E402

needs_store = pytest.mark.skipif(not (X.TEXT / "verse_units.jsonl").is_file(),
                                 reason=f"store not mounted ({X.TEXT})")
WINDOW = 8                                           # appendix_x.WINDOW: the leak window of prereg §1

# made-up chains: chapter 5 甲→乙→丙→丁 (丁 plays the flood patriarch), chapter 11 戊→辛→壬
FAKE = [
    (5, 1, "以下是甲這一家的名冊。"),
    (5, 3, "甲活到一百零一歲生了一個兒子，甲為他起名叫乙。"),
    (5, 4, "甲生乙之後又在世七百年。"),
    (5, 5, "甲共活了八百零一歲就死了。"),
    (5, 6, "乙活到八十八歲，生了丙。"),
    (5, 7, "乙生丙之後與上帝同行七百一十二年。"),
    (5, 8, "乙共活了八百歲。"),
    (5, 9, "丙活到九十九歲生了一個兒子，"),
    (5, 10, "給他起名叫丁，說：「某某。」"),
    (5, 11, "丙生丁之後又活了六百年。"),
    (5, 12, "丙共活了六百九十九歲就死了。"),
    (5, 13, "丁四百歲生了戊、己、庚。"),
    (7, 6, "洪水來到的時候，丁整五百歲。"),
    (9, 28, "洪水以後，丁又活了二百年。"),
    (9, 29, "丁共活了七百歲就死了。"),
    (11, 10, "以下是戊這一家的名冊。洪水以後三年，戊九十歲生了辛。"),
    (11, 11, "戊生辛之後又活了四百年。"),
    (11, 12, "辛活到四十歲，生了壬。"),
    (11, 13, "辛生壬之後又活了三百零五年。"),
    (11, 14, "壬活到六十歲，生了癸、子、丑。"),
    (11, 15, "壬共活了二百歲，就死在某地。"),
    (35, 28, "寅共活了一百歲。"),
]
FAKE_EXPECT = {"nodes": 7, "beget": 7, "remain": 5, "total": 5, "total_eq": 3, "son_match": 5, "derived": 2}


def write_text(root: Path, rows=FAKE) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "verse_units.jsonl").open("w", encoding="utf-8") as f:
        for i, (c, v, t) in enumerate(rows):
            f.write(json.dumps({"unit_key": f"gen.{c}.{v}", "book_id": "gen", "chapter": c, "v_start": v,
                                "v_end": v, "ord": i, "text": t}, ensure_ascii=False) + "\n")
    return root


@pytest.fixture
def fake(tmp_path):
    return G.build(write_text(tmp_path / "text"))


def test_fake_nodes_fields_and_ids(fake):
    by = {n["id"]: n for n in fake["nodes"]}
    assert list(by) == ["G05.00", "G05.01", "G05.02", "G05.03", "G11.00", "G11.01", "G11.02"]
    assert [by[i]["name"] for i in by] == ["甲", "乙", "丙", "丁", "戊", "辛", "壬"]
    assert by["G05.00"]["fields"] == {"beget": [101, "gen.5.3"], "remain": [700, "gen.5.4"],
                                      "total": [801, "gen.5.5"]}
    assert by["G05.01"]["fields"]["remain"] == [712, "gen.5.7"]            # the 與上帝同行 verb
    assert by["G05.02"]["sons"] == ["丁"]                                   # 起名叫 in the next verse
    assert by["G05.00"]["sons"] == ["乙"]                                   # 起名叫 in the same verse
    assert by["G05.03"]["fields"] == {"beget": [400, "gen.5.13"], "total": [700, "gen.9.29"]}
    assert by["G05.03"]["sons"] == ["戊", "己", "庚"]
    assert by["G11.00"]["flood_offset"] == [3, "gen.11.10"]
    assert by["G11.02"]["fields"] == {"beget": [60, "gen.11.14"], "total": [200, "gen.11.15"]}
    assert all(by[i]["flood_offset"] is None for i in by if i != "G11.00")
    assert [(n["chapter"], n["order"]) for n in fake["nodes"]][:2] == [(5, 0), (5, 1)]


def test_fake_edges_flood_derived_checks(fake):
    assert fake["edges"] == [["G05.00", "G05.01", "son", "gen.5.3"], ["G05.01", "G05.02", "son", "gen.5.6"],
                             ["G05.02", "G05.03", "son", "gen.5.9"], ["G11.00", "G11.01", "son", "gen.11.10"],
                             ["G11.01", "G11.02", "son", "gen.11.12"]]
    assert [e[:3] for e in fake["conflict_edges"]] == [["G05.03", "G11.00", "son"]]
    assert fake["flood"] == {"noah_age": [500, "gen.7.6"]}
    assert fake["derived"] == {"total": {"G11.00": 490, "G11.01": 345}}
    assert fake["checks"] == {"total_eq": [3, 3], "son_match": [5, 5], "noah_no_remain": True,
                              "counts": {"nodes": 7, "beget": 7, "remain": 5, "total": 5, "derived": 2}}
    assert G.check(fake, FAKE_EXPECT) == []
    assert G.check(fake) != []                       # the real-layer expectations do not hold here


def test_fake_years(fake):
    born = {i: G.born_year(fake, i) for i in ("G05.00", "G05.01", "G05.02", "G05.03", "G11.00", "G11.01", "G11.02")}
    assert born == {"G05.00": 0, "G05.01": 101, "G05.02": 189, "G05.03": 288,
                    "G11.00": 701, "G11.01": 791, "G11.02": 831}  # flood 288+500=788, 辛 788+3
    assert G.flood_year(fake) == 788
    assert G.death_year(fake, "G05.00") == 801 and G.death_year(fake, "G11.00") == 1191
    assert G.total(fake, "G11.01") == 345 and G.total(fake, "G05.03") == 700
    assert G.chain(fake, 11) == ["G11.00", "G11.01", "G11.02"]
    assert G.by_name(fake, "丙") == "G05.02"
    assert G.age_at_birth(fake, "G05.00", "G05.03") == 101 + 88 + 99


def test_fake_problems_are_reported(tmp_path):
    rows = [r if r[:2] != (5, 7) else (5, 7, "乙生某之後又活了七百一十二年。") for r in FAKE]
    rows = [r for r in rows if r[:2] != (9, 28)] + [(5, 14, "丁生戊之後，又活了二百一十三年。")]
    doc = G.build(write_text(tmp_path / "t2", rows))
    probs = G.check(doc, FAKE_EXPECT)
    assert any("son_match" in p for p in probs)
    assert any("noah" in p for p in probs)


def test_write_and_load_roundtrip(fake, tmp_path):
    p = G.write(fake, tmp_path / "gen_layer.json")
    assert G.load(p) == fake
    assert G.sha256(fake) == X.sha256_file(p)


def test_write_refuses_the_repo(fake):
    with pytest.raises(SystemExit):
        G.write(fake, _DIR / "gen_layer.json")


@needs_store
def test_this_file_shares_no_window_with_a_verse():
    """repo 不放任何經節字串 (prereg §1): no 8-character window of this file, the made-up verses included, is
    in a verse of the text layer (only counts are reported)."""
    src = Path(__file__).read_text(encoding="utf-8")
    mine = {src[i:i + WINDOW] for i in range(len(src) - WINDOW + 1)}
    assert all(t in src for _c, _v, t in FAKE)
    hits = sum(any(v[i:i + WINDOW] in mine for i in range(len(v) - WINDOW + 1))
               for v in (r["text"] for r in X.jsonl(X.TEXT / "verse_units.jsonl")))
    assert hits == 0, f"{hits} verses share an {WINDOW}-character window with this file"


@needs_store
def test_real_layer_k0_2():
    doc = G.build()
    assert G.check(doc) == []
    assert doc["checks"]["total_eq"] == [9, 9] and doc["checks"]["son_match"] == [17, 17]
    assert doc["checks"]["noah_no_remain"] is True
    assert doc["text_digest"] == X.TEXT_DIGEST and doc["schema"] == "arith.gen_layer.v1"
    ids = [n["id"] for n in doc["nodes"]]
    assert ids == [f"G05.{i:02d}" for i in range(10)] + [f"G11.{i:02d}" for i in range(9)]
    noah, shem = G.node(doc, "G05.09"), G.node(doc, "G11.00")
    assert set(noah["fields"]) == {"beget", "total"}
    assert shem["flood_offset"][1] == "gen.11.10"
    assert sorted(doc["derived"]["total"]) == [f"G11.{i:02d}" for i in range(8)]
    assert G.build() == doc                                  # deterministic


@needs_store
def test_real_layer_years_consistent():
    doc = G.build()
    for ch in (5, 11):
        ids = G.chain(doc, ch)
        for a, b in zip(ids, ids[1:]):
            assert G.born_year(doc, b) == G.born_year(doc, a) + G.node(doc, a)["fields"]["beget"][0]
    for n in doc["nodes"]:
        assert G.death_year(doc, n["id"]) - G.born_year(doc, n["id"]) == G.total(doc, n["id"])
    shem = G.node(doc, "G11.00")
    assert G.born_year(doc, "G11.01") == G.flood_year(doc) + shem["flood_offset"][0]
    assert G.flood_year(doc) == G.born_year(doc, "G05.09") + doc["flood"]["noah_age"][0]

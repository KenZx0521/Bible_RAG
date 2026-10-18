"""Experiment A confirmation set, core CPU tools (A/confirm: segments, support, alias_table, items_c, k1).

confirm_A.md §9 tests 1, 2, 3 and 6, plus an items_c round trip on synthetic questions built from the
segment candidates (template wording, no question text of the real set). Nothing launches an agent
or calls Ollama; every test needs the store's reference layer and skips when it is absent.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-18_kg_cards" / "A" / "confirm"
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import c_common as C  # noqa: E402

needs_store = pytest.mark.skipif(not C.LAYER_REF.is_file() or not C.LAYER_AUTO.is_file(),
                                 reason=f"store not mounted ({C.LAYER_REF})")
pytestmark = needs_store

EXPECTED = {
    "I1": ["I01", "I02", "I03"], "I2": ["I03", "I04", "I05"], "I3": ["I05", "I06", "I07"],
    "I4": ["I07", "I08", "I09"], "I5": ["I09", "I10", "I11"], "I6": ["I11", "I12", "I13"],
    "I7": ["I13", "I14", "I15"], "I8": ["I15", "I16", "I17"], "I9": ["I17", "I18", "I19"],
    "J1": ["J02", "J03", "J04", "J05", "J06"], "J2": ["J08", "J09", "J10", "J11", "J12"],
    "J3": ["J12", "J13", "J14", "J15", "J16"], "J4": ["J16", "J17", "J18"], "J5": ["J18", "J19", "J20"],
}
CN = {1: "一", 2: "二", 3: "三", 4: "四"}


@pytest.fixture(scope="module")
def mods():
    import importlib
    return {m: importlib.import_module(m) for m in ("support", "segments", "alias_table", "items_c", "k1")}


@pytest.fixture(scope="module")
def layers():
    from regnal import load_auto, load_ref
    return load_auto(C.LAYER_AUTO), load_ref(C.LAYER_REF)


@pytest.fixture(scope="module")
def segdoc(mods):
    return mods["segments"].build()


# ---------------------------------------------------------------- test 1: segmentation
def test_1_segments_reproduce_fourteen(segdoc):
    assert segdoc["ref_layer_sha256"] == C.FROZEN_SHA["ref_layer.json"]
    assert {s["id"]: s["kings"] for s in segdoc["segments"]} == EXPECTED
    assert segdoc["n_segments"] == 14 and segdoc["n_by_kingdom"] == {"I": 9, "J": 5}
    assert segdoc["n_candidates"] == {"S1a": 29, "S1b": 7, "S1c": 4, "S4": 4, "total": 44}
    # I6 backward: 耶羅波安's required tag 「（約阿施的兒子）」 names the intermediate king → not writable
    assert [(d["segment"], d["seed"], d["answer"], d["reason"]) for d in segdoc["dropped"]] == [
        ("I6", "I13", "I11", "homonym_tag_on_chain")]
    assert segdoc["sensitivity"] == {"athaliah_gap": 14, "no_gaps": 16, "tibni_and_athaliah_gaps": 13}
    seg = {s["id"]: s for s in segdoc["segments"]}
    assert seg["I2"]["range"] == ["1ki.15.27", "1ki.16.15"] and seg["I2"]["n_verses"] == 23
    assert seg["J1"]["range"] == ["1ki.14.31", "2ki.9.29"] and seg["J1"]["n_verses"] == 537
    assert all(not ({"J07"} & set(s["kings"])) for s in segdoc["segments"])     # 亞她利雅's edges are gaps
    s4 = sorted((q["seed"], q["answer"]) for s in segdoc["segments"] for q in s["candidates"] if q["qtype"] == "S4")
    assert s4 == [("J05", "J03"), ("J12", "J10"), ("J16", "J14"), ("J18", "J16")]


def test_1_slot_plan_and_pilot(segdoc):
    assert segdoc["n_slots"] == 35
    assert segdoc["slots_by_type"] == {"S1a": 14, "S1a_rev": 10, "S1c": 4, "S1b": 3, "S4": 4}
    assert next(s for s in segdoc["segments"] if s["id"] == "I6")["slots"] == ["S1a"]
    assert [(p["segment"], p["qtype"]) for p in segdoc["pilot"]] == [
        ("J5", "S1a"), ("J4", "S4"), ("I4", "S1a"), ("I6", "S1a"), ("I2", "S1c"), ("I8", "S1a"), ("J1", "S1b"),
        ("I7", "S1a"), ("I9", "S1a"), ("I1", "S1a"), ("I3", "S1a"), ("J2", "S1a")]
    pilot = segdoc["pilot"]
    assert len(pilot) == 12 and len({p["segment"] for p in pilot}) == 12
    assert sorted(p["qtype"] for p in pilot) == ["S1a"] * 9 + ["S1b", "S1c", "S4"]
    assert all(p["qtype"] == next(s for s in segdoc["segments"] if s["id"] == p["segment"])["slots"][p["slot"] - 1]
               for p in pilot)


def test_1_segments_independent_of_hash_seed():
    code = "import json,hashlib,segments;print(hashlib.sha256(json.dumps(segments.build(),ensure_ascii=False).encode()).hexdigest())"
    outs = {subprocess.run([sys.executable, "-B", "-c", code], cwd=_DIR, capture_output=True, text=True, check=True,
                           env=dict(os.environ, PYTHONHASHSEED=h)).stdout for h in ("0", "1")}
    assert len(outs) == 1


# ---------------------------------------------------------------- test 2: genealogy shortcut
def test_2_genealogy_shortcut(mods):
    S = mods["support"]
    assert "1ch.3.12" in S.genealogy_shortcut(("J09", "J10", "J11"))
    assert S.genealogy_shortcut(("J11", "J10", "J09")) == S.genealogy_shortcut(("J09", "J10", "J11"))
    assert S.genealogy_shortcut(("J09", "J10", "J11", "J12")) == ()             # k=3 spans two verses
    assert S.genealogy_shortcut(("I02", "I03", "I04")) == ()                     # not all son
    assert S.genealogy_passage(("J09", "J10", "J11", "J12"))                     # hidden flag only


# ---------------------------------------------------------------- test 3: names, segment check, facts
def test_3_resolve_names(mods):
    S = mods["support"]
    assert S.resolve_king("耶羅波安（約阿施的兒子）", None, "以色列") == "I13"
    assert S.resolve_king("約阿施的兒子耶羅波安", None, "I") == "I13"
    assert S.resolve_king("耶羅波安", "尼八", "以色列") == "I01"
    assert S.resolve_king("以色列王耶羅波安(約阿施的兒子)") == "I13"
    assert S.resolve_king("耶羅波安", None, "以色列") is None                     # homonym without father
    assert S.resolve_king("約哈斯", None, "猶大") == "J17"                        # main name beats J06's alias
    assert S.resolve_king("烏西雅", None, "猶大") == "J10"
    assert S.resolve_king("約蘭", None, None) is None                            # two kingdoms
    assert S.resolve_king("大衛", None, "猶大") is None


def _q(seg, qtype, chain, **kw):
    q = {"id": "X", "segment": seg, "qtype": qtype, "kingdom": kw.pop("kingdom", "以色列"), "question": "",
         "seeds": [{"name": chain[0][0], "father": chain[0][1]}],
         "answer": {"kind": "name", "text": chain[-1][0], "accept": []},
         "chain": [{"king": k, "father": f, "role": r, "fact": "", "basis": []}
                   for (k, f), r in zip(chain, ["seed"] + ["step"] * (len(chain) - 2) + ["answer"])]}
    q.update(kw)
    return q


def test_3_seg_check_and_facts(mods, segdoc):
    S, segs = mods["support"], segdoc["segments"]
    ok = S.support_record(_q("I2", "S1a", [("巴沙", None), ("以拉", None), ("心利", None)]), segs)
    assert ok["errors"] == [] and ok["path"] == ["I03", "I04", "I05"]
    assert ok["support"] == [["E", "I03", "I04"], ["E", "I04", "I05"]] and ok["boundary_kings"] == ["I03", "I05"]
    cross = S.support_record(_q("I2", "S1a", [("以拉", None), ("心利", None), ("暗利", None)]), segs)
    assert cross["errors"] == ["seg_cross"]
    gap = S.support_record(_q("J1", "S1a", [("亞哈謝", None), ("亞她利雅", None), ("約阿施", None)], kingdom="猶大"), segs)
    assert gap["errors"] == ["seg_cross"]
    bad = S.support_record(_q("I6", "S1a", [("約哈斯", None), ("約阿施", None), ("耶羅波安", None)]), segs)
    assert bad["errors"] == ["name_unresolved", "seg_cross"] and bad["unresolved"] == ["耶羅波安"]
    skip = S.support_record(_q("I2", "S1a", [("巴沙", None), ("心利", None)]), segs)
    assert skip["hidden"]["ref_disagree"] and skip["errors"] == []
    s4 = S.support_facts("S4", ["J16", "J15", "J14"])
    assert s4 == [["A", "J16"], ["R", "J14"], ["R", "J15"], ["E", "J14", "J15"], ["E", "J15", "J16"]]
    assert S.extra_kings("以色列王耶羅波安（約阿施的兒子）之前的第二位以色列王是誰？", ["I13"]) == []
    assert S.extra_kings("猶大王亞撒利雅之後，經過約坦，第二位猶大王是誰？", ["J10"]) == ["約坦"]
    seg = next(s for s in segs if s["id"] == "I2")
    assert S.in_range(seg, "1ki.16.8") and not S.in_range(seg, "1ki.16.29") and not S.in_range(seg, "1ch.3.12")


def test_alias_table(mods):
    doc = mods["alias_table"].build()
    assert doc["n_kings"] == 39 and doc["ref_layer_sha256"] == C.FROZEN_SHA["ref_layer.json"]
    j06 = next(k for k in doc["kings"] if k["id"] == "J06")
    assert j06["not_accepted"] == ["約哈斯", "亞撒利雅"]
    j17 = next(k for k in doc["kings"] if k["id"] == "J17")
    assert "沙龍" in j17["accept"]                                              # other kingdom's 沙龍 stays
    assert doc["units"] == {"S1b": "次|代|任|位"} and "所羅門" in doc["lexicon"]


def test_frozen_inputs_match():
    assert C.frozen_mismatches() == []


# ---------------------------------------------------------------- test 6: K1 on stage-0 templates
def test_6_k1_reproduces_stage0_gold_seed_hits(mods, layers):
    VA, VR = layers
    items = C.read_json(C.ST0_ITEMS)["items"]
    rows = mods["k1"].k1_rows(items, VA, VR)
    hits = [r["id"] for r in rows if r["hit"]]
    assert hits == C.read_json(C.ST0 / "dry_run/summary.json")["a_hit_gold_seeds"]
    assert all(r["hit"] for r in rows if r["id"].startswith("T_"))              # 24/24 template items
    v = mods["k1"].verdict(rows)
    assert (v["n_pass"], v["n_hit"], v["stop"]) == (30, 27, False)
    assert mods["k1"].verdict(rows[:9])["stop"] and "通過題數" in mods["k1"].verdict(rows[:9])["wording"]


def test_6_k1_stop_wording(mods):
    rows = [{"hit": i < 9, "ref_hit": True} for i in range(12)]
    v = mods["k1"].verdict(rows)
    assert v["stop"] and v["wording"] == "依事先規則停止（K1＝9/12），不構成無效證據；盲集未跑"
    assert not mods["k1"].verdict([{"hit": i < 10, "ref_hit": True} for i in range(12)])["stop"]


# ---------------------------------------------------------------- items_c round trip
def synth_questions(segs, VR):
    """One §2.8 question per segment candidate, template wording (stage-0 style)."""
    from engine import homonym
    from items_a import seed_desc
    out = []
    for s in segs:
        kn, ch = C.KNAME[s["kingdom"]], s["kings"]
        for i, c in enumerate(s["candidates"]):
            a, b = (c["a"], c["b"]) if c["qtype"] == "S1b" else (c["seed"], c["answer"])
            ia, ib = ch.index(a), ch.index(b)
            path = ch[ia:ib + 1] if ia <= ib else ch[ib:ia + 1][::-1]
            if c["qtype"] == "S1a":
                text = f"{seed_desc(VR, a)}之{'後' if c['k'] > 0 else '前'}的第{CN[abs(c['k'])]}位{kn}王是誰？"
            elif c["qtype"] == "S1b":
                text = f"從{seed_desc(VR, a)}到{seed_desc(VR, b)}，王位一共交接了幾次？"
            elif c["qtype"] == "S1c":
                text = f"{seed_desc(VR, a)}之後第{CN[c['n']]}個篡位得國的{kn}王是誰？"
            else:
                text = f"{seed_desc(VR, a)}出生時，在位的{kn}王是誰？"
            fa = lambda x: VR.nodes[x]["father"] if homonym(VR, x) else None  # noqa: E731
            seeds = [a, b] if c["qtype"] == "S1b" else [a]
            ans = ({"kind": "count", "text": f"{c['value']}次", "accept": [], "value": c["value"], "unit": "次"}
                   if c["qtype"] == "S1b" else {"kind": "name", "text": VR.nodes[b]["name"], "accept": []})
            out.append({"id": f"Z_{s['id']}_{i:02d}", "segment": s["id"], "qtype": c["qtype"], "kingdom": kn,
                        "question": text, "pilot": i == 0,
                        "seeds": [{"name": VR.nodes[x]["name"], "father": fa(x)} for x in seeds],
                        "k": c.get("k"), "n": c.get("n"), "answer": ans,
                        "chain": [{"king": VR.nodes[x]["name"], "father": fa(x),
                                   "role": "seed" if j == 0 else ("answer" if j == len(path) - 1 else "step"),
                                   "fact": "", "basis": [VR.nodes[x]["prov"].get("pred") or ""]}
                                  for j, x in enumerate(path)]})
    return out


def test_items_c_round_trip(mods, segdoc, layers, tmp_path):
    from keys_a import item_ctx, king_lexicon, score_line
    VA, VR = layers
    I = mods["items_c"]
    qs = synth_questions(segdoc["segments"], VR)
    src = {"id": "ps:x", "book": "列王紀上", "chapter": "1", "title": "t", "verse_range": "1-2",
           "context": "[1] 列王紀上 第1章 - t (1-2節)\n**1** 甲"}
    doc = I.build_items(qs, {q["id"]: {"sources": [src]} for q in qs}, segdoc["segments"], VR)
    p = tmp_path / "items.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back == doc and back["n_items"] == 44 and back["n_units"] == 14
    import cards_common as cc
    it = next(x for x in back["items"] if x["qtype"] == "S1a" and x["seeds"] == ["I15"] and x["gold"] == ["I13"])
    assert it["asked"] == ["succ", -2] and it["kingdom"] == "I" and it["unit"] == "I7"
    assert it["keys"][0]["accept"] == ["耶羅波安"] and set(it["exempt"]) >= {"沙龍", "撒迦利雅", "耶羅波安"}
    assert it["exempt_template"] == ["沙龍", "耶羅波安"]                          # own main name kept (homonym)
    assert cc.build_context(it["sources"]) == src["context"]
    ctx = item_ctx(it, VR, king_lexicon(VR))
    assert score_line(ctx, "耶羅波安")["score"] == 1.0 and score_line(ctx, "撒迦利雅")["score"] == 0.0
    cnt = next(x for x in back["items"] if x["qtype"] == "S1b")
    assert cnt["keys"][0] == {"type": "number", "value": cnt["keys"][0]["value"], "unit": "次|代|任|位",
                              "basis": cnt["keys"][0]["basis"]} and cnt["gold"] == []
    assert score_line(item_ctx(cnt, VR), f"{cnt['keys'][0]['value']}次")["score"] == 1.0
    with pytest.raises(ValueError):
        I.to_item(dict(qs[0], segment="J5"), [], VR, segdoc["segments"])       # seg_cross
    with pytest.raises(ValueError):
        I.build_items(qs[:1], {}, segdoc["segments"], VR)                       # no frozen context


def test_k1_engine_covers_every_candidate(mods, segdoc, layers):
    VA, VR = layers
    qs = synth_questions(segdoc["segments"], VR)
    items = [mods["items_c"].to_item(q, [], VR, segdoc["segments"]) for q in qs]
    rows = mods["k1"].k1_rows(items, VA, VR)
    assert [r["id"] for r in rows if not r["hit"]] == []
    pilot = mods["k1"].pilot_items(qs, segdoc["segments"], VR)
    assert len(pilot) == 14

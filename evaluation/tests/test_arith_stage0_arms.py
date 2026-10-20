"""Ordered-chain arithmetic stage-0, arm blocks and jobs (arms_x.py; prereg §1 順序, §4 臂, §6 K0-6).

The synthetic tests use made-up items, passages and blocks (王甲, 甲書, 列一 …): no question of the
experiment and no scripture. The store-backed test builds the 52 items and their cards in memory (read
only) and skips when the store is not mounted. Nothing here calls Ollama.
"""
from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_arith_stage0"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import arms_x as A  # noqa: E402
import engine_x as E  # noqa: E402
import x_common as X  # noqa: E402

cc = X.cc
STORE_OK = X.REF_V2.is_file() and X.R4_LAYER.is_file() and (X.TEXT / "verse_units.jsonl").is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({X.REF_V2})")
SRC = [{"id": "ps:x.1.1", "book_name": "甲書", "chapter_num": 1, "title": "假段", "verse_range": "1-2",
        "content": "假內容甲乙丙"}]


def item(iid: str, family: str, gold: int = 5) -> dict:
    return {"id": iid, "family": family, "qtype": {"DYN": "S5", "S6": "S6", "SYNC": "SYNC2", "GEN": "F1"}[family],
            "question": f"王甲到王丙一共幾{iid}？", "sources": SRC, "nested": False, "units_touched": ["u1"],
            "seed_names": [["I", "王甲"]], "tc_basis": ["x.1.1"], "tcanon_complete": True, "tcanon_missing": [],
            "gold": gold, "keys": [{"type": "arith", "value": gold, "classes": ["Y"], "ordinal": False}]}


def card(gold: int = 5, tc: str | None = "窗一\n窗二") -> dict:
    lines = [["王甲到王丙合計", f"{gold}年"]]
    t = "列一\n列二"
    g = E.render(["列一", "列二"], lines)
    return {"rows": ["r1", "r2"], "lines": lines, "g_block": g, "t_block": t, "covered": True, "dropped_rows": 0,
            "dropped_lines": 0, "chars_g": len(g), "chars_t": len(t), "protected_rows": ["r1"], "window": ["r1", "r2"],
            "over_cap": False, "tags": [{"kind": "sum", "seeds": ["r1", "r2"], "k": None, "value": gold, "unit": "Y"}],
            "tcanon": None if tc is None else {"block": tc, "verses": ["x.1.1"], "centers": ["x.1.1"]}}


@pytest.fixture
def syn():
    items = [item("D1", "DYN"), item("D2", "S6"), item("D3", "SYNC"), item("G1", "GEN"), item("G2", "GEN")]
    cards = {it["id"]: card(tc=None if it["family"] == "GEN" else "窗一\n窗二") for it in items}
    return items, cards


def test_arms_and_counts(syn):
    items, cards = syn
    jobs, meta = A.build_arms(items, cards)
    assert A.arm_order("DYN") == ("G", "T-rows", "T-canon", "B0")
    assert A.arm_order("GEN") == ("G", "T-rows", "B0", "B0p")
    assert len(jobs) == A.n_expected(items) == 3 * 4 * 3 + 2 * (3 * 3 + 1)
    assert A.job_problems(items, jobs) == []
    by = Counter((j["item"], j["arm"]) for j in jobs)
    assert by[("G1", "B0p")] == 1 and by[("G1", "G")] == 3 and ("G1", "T-canon") not in by and by[("D1", "T-canon")] == 3
    assert all(j["job_id"] == f"X|{j['item']}|{j['arm']}|{j['rep']}" and j["exp"] == "X" and j["kind"] == "gen"
               and j["system"] == cc.SYSTEM_PROMPT for j in jobs)
    assert set(meta) == {it["id"] for it in items}


def test_order_rep_item_arm_rotated_by_item_index(syn):
    items, cards = syn
    jobs = A.arm_jobs(items, cards)
    first = [(j["item"], j["arm"]) for j in jobs if j["rep"] == 1]
    assert first[:4] == [("D1", a) for a in ("G", "T-rows", "T-canon", "B0")]           # index 0: no rotation
    assert first[4:8] == [("D2", a) for a in ("T-rows", "T-canon", "B0", "G")]          # index 1
    assert first[12:16] == [("G1", a) for a in ("B0p", "G", "T-rows", "B0")]           # index 3 of 4 arms
    rep2 = [(j["item"], j["arm"]) for j in jobs if j["rep"] == 2 and j["item"] == "G1"]
    assert rep2 == [("G1", a) for a in ("G", "T-rows", "B0")]                          # 3 arms: 3 % 3 = 0
    reps = [j["rep"] for j in jobs]
    assert reps == sorted(reps)                                                         # rep → item → arm


def test_prompts_per_arm(syn):
    items, cards = syn
    jobs = {(j["item"], j["arm"], j["rep"]): j for j in A.arm_jobs(items, cards)}
    q, ctx = items[0]["question"], cc.build_context(SRC)
    g, t, tc, b0 = (jobs[("D1", a, 1)]["user"] for a in ("G", "T-rows", "T-canon", "B0"))
    assert g == cc.build_user(ctx, q, cards["D1"]["g_block"]) and cc.AUX_LABEL in g
    assert cards["D1"]["g_block"] in g and "依上列資料推算：" in g
    assert cards["D1"]["t_block"] in t and "依上列資料推算：" not in t
    assert "窗一" in tc and "列一" not in tc
    assert b0 == cc.build_user(ctx, q, None) and cc.AUX_LABEL not in b0 and "假內容甲乙丙" in b0
    b0p = jobs[("G1", "B0p", 1)]["user"]
    assert b0p == cc.build_user("", items[3]["question"], "") and "假內容甲乙丙" not in b0p and cc.AUX_LABEL not in b0p
    for arm in ("G", "T-rows", "T-canon"):                        # the auxiliary label never names the arm
        assert arm not in jobs[("D1", arm, 1)]["user"].replace(q, "")


def test_meta(syn):
    items, cards = syn
    _, meta = A.build_arms(items, cards)
    m = meta["D1"]
    assert m["block_chars"] == {"G": len(cards["D1"]["g_block"]), "T-rows": len(cards["D1"]["t_block"]),
                                "T-canon": len("窗一\n窗二"), "B0": 0}
    assert len(set(m["prompt_sha256"].values())) == 4 and m["covered"] and m["tcanon_agrees"] is True
    assert meta["G1"]["tcanon"] is None and meta["G1"]["tcanon_agrees"] is None and "B0p" in meta["G1"]["block_chars"]


def test_card_problems(syn):
    items, cards = syn
    _, meta = A.build_arms(items, cards)
    assert A.card_problems(items, cards, meta) == {}
    bad = copy.deepcopy(cards)
    bad["D1"]["tcanon"]["block"] = "窗" * (X.CAP_CHARS + 1)
    bad["D2"]["tcanon"]["block"] = ""
    bad["D3"]["tcanon"]["verses"] = []                                  # misses the basis verse items_x saw
    bad["G1"]["protected_rows"] = ["r9"]                                # engine_x.check_card: a core row dropped
    _, bm = A.build_arms(items, bad)
    probs = A.card_problems(items, bad, bm)
    assert set(probs) == {"D1", "D2", "D3", "G1"}
    assert any("T-canon block" in p for p in probs["D1"]) and any("empty" in p for p in probs["D2"])
    assert any("misses" in p for p in probs["D3"]) and any("core row" in p for p in probs["G1"])


def test_job_problems(syn):
    items, cards = syn
    jobs = A.arm_jobs(items, cards)
    assert A.job_problems(items, jobs[:-1])
    assert A.job_problems(items, jobs + [jobs[0]])
    other = [dict(j, system="另一個") if i == 3 else j for i, j in enumerate(jobs)]
    assert A.job_problems(items, other) == ["a job with another system prompt"]
    assert A.prompts_sha256(jobs) != A.prompts_sha256(jobs[::-1])


@needs_store
def test_store_items_588_jobs_and_k0_6():
    import gen_layer as G
    import items_x as I
    gen = G.build()
    items = I.build_items(gen=gen)["items"]
    cards = A.build_cards(items, gen)
    jobs, meta = A.build_arms(items, cards)
    assert len(jobs) == 588 and A.job_problems(items, jobs) == [] and A.card_problems(items, cards, meta) == {}
    by = Counter(j["arm"] for j in jobs)
    assert by == {"G": 156, "T-rows": 156, "B0": 156, "T-canon": 102, "B0p": 18}
    assert all(m["covered"] for m in meta.values())
    assert all(m["tcanon_agrees"] for m in meta.values() if m["family"] != "GEN")
    assert max(n for m in meta.values() for n in m["block_chars"].values()) <= X.CAP_CHARS
    assert A.prompts_sha256(A.build_arms(items, A.build_cards(items, gen))[0]) == A.prompts_sha256(jobs)

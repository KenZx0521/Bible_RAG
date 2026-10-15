"""book_anchor ablation checks (experiments/2026-10-15_book_anchor/_ba_checks.py).

prereg §4, §6 and §10 test_ba_checks: synthetic retrieval records pass every invariant;
each of I0–I4 detects its failures; subsets, freeze hashes, the gen_plan shuffle and
judge_order are deterministic; an arm whose context equals ctrl's is not generated; the
four D_off mechanism tags; the eval3c overlap; the smoke expectations of §6; the frozen
eval3c reference built from eval3c's raw responses.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EXP = _REPO / "evaluation" / "experiments" / "2026-10-15_book_anchor"
if str(_EXP) not in sys.path:
    sys.path.insert(0, str(_EXP))

import _ba_checks as ck  # noqa: E402

FP = {"embedder": {"tokenizer_sha": "e" * 64, "unk_count": 3},
      "reranker": {"tokenizer_sha": "r" * 64, "unk_count": 2}}
BACKEND = {f: hashlib.sha256(f.encode()).hexdigest() for f in ck.BACKEND_FILES}
EXP = {"ba_driver.py": "1" * 64, "ba_arms.py": "2" * 64, "_ba_io.py": "3" * 64}
SETTINGS = {"rag_env": "prod", "rag_build_id": ck.BUILD_ID, "rag_rank_fusion_enabled": True,
            "rag_rank_fusion_alpha": 0.3, "rag_use_graph": True,
            "rag_graph_strategies": ["event_registry"], "ollama_model": ck.GEN_MODEL,
            "llm_temperature": 0.1, "llm_max_tokens": 10000, "default_top_k": 5}


def meta(**over):
    base = {"kind": "meta", "mode": "retrieve", "build_id": ck.BUILD_ID,
            "handshake": {"ok": True, "build_id": ck.BUILD_ID, "mismatches": []},
            "encoder_fingerprint": FP, "torch_threads": 24, "llm_health": True,
            "settings": dict(SETTINGS), "call": dict(ck.EXPECT_CALL),
            "backend_sha256": dict(BACKEND), "exp_sha256": dict(EXP),
            "env": {"RAG_ENV": "prod", "RAG_BUILD_ID": ck.BUILD_ID}}
    return {**base, **over}


EXP_META = {"image_id": ck.IMAGE_PREFIX + "e48be2274c24",
            "ollama_digests": {ck.GEN_MODEL: "d" * 64, ck.JUDGE_MODEL: "j" * 64},
            "refusal_v2_sha256": ck.REFUSAL_SHA_PREFIX + "0" * 56}


def i0(metas=None, exp_meta=EXP_META, exp=EXP):
    return ck.check_i0(metas or [meta()], backend_expected=BACKEND, exp_expected=exp,
                       encoder_expected=FP, exp_meta=exp_meta)


# ---------------------------------------------------------------- synthetic records

def res(pid, strategy="hybrid_hybrid", score=0.5, book="isa"):
    return {"id": pid, "source_strategy": strategy, "fused_score": score, "rerank_score": score,
            "book_id": book}


def pool_entry(pid, strategy="hybrid_hybrid", weight=0.65, rr=0.5):
    return {"id": pid, "source_strategy": strategy, "weight": weight, "rerank_score": rr,
            "semantic_score": 0.4, "book_id": "isa"}


def arm(core, aux=(), pool=None, pins=(), route="R5", ba_calls=1, errors=None, books=("isa",),
        strategies=None):
    strategies = strategies or {}
    results = [res(p, strategies.get(p, "hybrid_hybrid")) for p in core] + \
              [res(p, "event_registry", None) for p in aux]
    ids = list(core) + list(aux)
    return {"results": results, "ids": ids, "n_core": len(core),
            "ctx_sha": hashlib.sha256("|".join(ids).encode()).hexdigest(),
            "stats": {"route_used": route, "strategy_errors": dict(errors or {}), "use_graph": True,
                      "graph_strategies": ["event_registry"],
                      "fusion_alpha": None if route == "R1" else 0.3},
            "pool": pool if pool is not None else [pool_entry(p) for p in core],
            "pins": list(pins), "ba_calls": ba_calls,
            "signals": {"detected_book_ids": list(books), "multi_book": len(books) > 1}}


def row(qid, ctrl, nopin=None, off=None, skipped=None, forced=False, intent_ok=True):
    return {"kind": "q", "qid": qid, "question": qid, "forced": forced, "arms_skipped": skipped,
            "intent_ok": intent_ok, "intent_attempts": 1, "arm_attempts": 1,
            "arms": {"ctrl": ctrl, "nopin": nopin, "off": off}}


D = [f"ps:isa.{i}.1" for i in range(1, 8)]
BA = {"ps:isa.50.1": "book_anchor", "ps:isa.51.1": "book_anchor", "ps:rev.1.1": "book_anchor",
      "ps:isa.60.1": "book_anchor"}


def ba_pool(core, extra):
    return [pool_entry(p, BA.get(p, "hybrid_hybrid"), 0.9 if p in BA else 0.65)
            for p in list(dict.fromkeys(list(core) + list(extra)))]


def rows():
    out = {}
    # QA single-book pins: ctrl pins two anchors; nopin and off give the natural order
    ctrl = arm(["ps:isa.50.1", "ps:isa.51.1", *D[:3]], strategies=BA,
               pool=ba_pool(D[:5], ["ps:isa.50.1", "ps:isa.51.1"]),
               pins=[{"book_gate": False, "pinned": ["ps:isa.50.1", "ps:isa.51.1"], "called": True}])
    nat = arm(D[:5], pool=ba_pool(D[:5], ["ps:isa.50.1", "ps:isa.51.1"]),
              pins=[{"book_gate": False, "pinned": [], "called": False}])
    off = arm(D[:5], pool=ba_pool(D[:5], []), pins=[{"book_gate": False, "pinned": [],
                                                    "called": True}])
    out["QA"] = row("QA", ctrl, nat, off)
    # QB multi-book pin (book_gate): nopin keeps it, off loses it
    pin_m = [{"book_gate": True, "pinned": ["ps:rev.1.1"], "called": True}]
    ctrl = arm(["ps:rev.1.1", *D[:4]], strategies=BA, pool=ba_pool(D[:5], ["ps:rev.1.1"]),
               pins=pin_m, books=("isa", "rev"))
    out["QB"] = row("QB", ctrl, copy.deepcopy(ctrl),
                    arm(D[:5], pool=ba_pool(D[:5], []), books=("isa", "rev")))
    # QC an anchor in the core by its prior (no pin): off swaps in D[5]
    ctrl = arm([*D[:4], "ps:isa.60.1"], strategies=BA, pool=ba_pool(D[:6], ["ps:isa.60.1"]))
    out["QC"] = row("QC", ctrl, copy.deepcopy(ctrl), arm([*D[:4], D[5]], pool=ba_pool(D[:6], [])))
    # QD an anchor in the pool only: nothing changes
    ctrl = arm(D[:5], pool=ba_pool(D[:5], ["ps:isa.60.1"]))
    out["QD"] = row("QD", ctrl, copy.deepcopy(ctrl), arm(D[:5], pool=ba_pool(D[:5], [])))
    # QE not in C, forced: three equal arms
    ctrl = arm(D[:5])
    out["QE"] = row("QE", ctrl, copy.deepcopy(ctrl), copy.deepcopy(ctrl), forced=True)
    # QF not in C, _book_anchor never called: skipped (M1)
    out["QF"] = row("QF", arm(D[:5], ba_calls=0), skipped="book_anchor_not_invoked")
    # QG R1, forced
    ctrl = arm(["vs:jhn.3.16"], route="R1", ba_calls=0, pool=[])
    out["QG"] = row("QG", ctrl, copy.deepcopy(ctrl), copy.deepcopy(ctrl), forced=True)
    return out


def eval3c_of(rws):
    return {q: {"route_used": r["arms"]["ctrl"]["stats"]["route_used"],
                "sources": [{"id": x["id"], "score": x["fused_score"]}
                            for x in r["arms"]["ctrl"]["results"]]}
            for q, r in rws.items()}


# ---------------------------------------------------------------- all pass

def test_synthetic_records_pass_every_invariant():
    rws = rows()
    subs = ck.subsets(rws)
    assert subs == {"C": ["QA", "QB", "QC", "QD"], "P_s": ["QA"], "P_m": ["QB"],
                    "D_nopin": ["QA"], "D_off": ["QA", "QB", "QC"], "U": ["QA", "QB", "QC"]}
    assert i0() == []
    assert ck.check_i1(rws, eval3c_of(rws))["ok"]
    assert ck.check_i2(rws)["ok"] and ck.check_i2(rws)["checked"] == ["QE", "QG"]
    assert ck.check_i3(subs)["ok"]
    assert ck.check_i4(rws)["ok"]
    assert ck.check_i5(rws)["exceptions"] == []


# ---------------------------------------------------------------- I0

@pytest.mark.parametrize("over", [
    {"build_id": "b20261008_6daa4f31"},
    {"encoder_fingerprint": {**FP, "reranker": {"tokenizer_sha": "x"}}},
    {"torch_threads": 12},
    {"llm_health": False},
    {"handshake": {"ok": False}},
    {"settings": {**SETTINGS, "rag_rank_fusion_alpha": 0.0}},
    {"settings": {**SETTINGS, "rag_rank_fusion_enabled": False}},
    {"settings": {**SETTINGS, "rag_graph_strategies": []}},
    {"settings": {**SETTINGS, "ollama_model": "gemma4:e4b"}},
    {"settings": {**SETTINGS, "llm_temperature": 0.0}},
    {"settings": {**SETTINGS, "llm_max_tokens": 100000}},
    {"call": {**ck.EXPECT_CALL, "top_k": 6}},
    {"call": {**ck.EXPECT_CALL, "use_graph": False}},
    {"backend_sha256": {**BACKEND, "utils/retrieval/pins.py": "0" * 64}},
    {"exp_sha256": {**EXP, "ba_arms.py": "0" * 64}},
    {"exp_sha256": {**EXP, "extra.py": "0" * 64}},
    {"env": {"RAG_ENV": "staging"}},
], ids=lambda o: next(iter(o)))
def test_i0_detects_each_meta_mismatch(over):
    assert i0([meta(), meta(**over)])


def i0_gen(metas):
    return ck.check_i0(metas, backend_expected=BACKEND, exp_expected=EXP, encoder_expected={},
                       exp_meta=EXP_META, mode="generate")


def test_i0_generate_meta_needs_no_encoder_or_threads():
    gen = {k: v for k, v in meta(mode="generate").items()
           if k not in ("encoder_fingerprint", "torch_threads", "handshake")}
    assert i0_gen([gen]) == []
    assert i0_gen([{**gen, "settings": {**SETTINGS, "rag_build_id": None}}])
    assert i0_gen([{**gen, "settings": {**SETTINGS, "llm_max_tokens": 4096}}])
    assert i0_gen([{**gen, "exp_sha256": {}}])
    assert i0_gen([]) and i0_gen([meta()])           # none, or a retrieve line, in gen.jsonl
    assert i0([meta(), gen])                         # a generate line in retrieval.jsonl


@pytest.mark.parametrize("exp_meta", [
    None,
    {**EXP_META, "image_id": "sha256:0123456789ab"},
    {**EXP_META, "ollama_digests": {ck.GEN_MODEL: "d" * 64}},
    {**EXP_META, "refusal_v2_sha256": "0" * 64},
], ids=["missing", "image", "digest", "refusal"])
def test_i0_detects_exp_meta_problems(exp_meta):
    assert i0(exp_meta=exp_meta)


def test_i0_needs_a_retrieve_meta_line():
    assert i0([meta(mode="generate")])


# ---------------------------------------------------------------- I1–I5

def test_i1_detects_a_different_top_k_and_lists_route_changes_apart():
    rws = rows()
    ref = eval3c_of(rws)
    ref["QE"]["sources"] = ref["QE"]["sources"][::-1]
    ref["QA"]["route_used"] = "fallback"
    out = ck.check_i1(rws, ref)
    assert not out["ok"] and [m["qid"] for m in out["mismatch"]] == ["QE"]
    assert [r["qid"] for r in out["route_diff"]] == ["QA"]
    ok = ck.check_i1(rws, {**eval3c_of(rws), "QA": ref["QA"]})
    assert ok["ok"] and ok["compared"] == 6


def test_i1_reports_the_largest_score_drift():
    rws = rows()
    ref = eval3c_of(rws)
    ref["QE"]["sources"][0]["score"] += 3e-6
    out = ck.check_i1(rws, ref)
    assert out["ok"] and out["max_abs_dscore"] == pytest.approx(3e-6)


def test_i2_detects_a_non_c_arm_that_differs_and_a_skipped_c_question():
    rws = rows()
    rws["QE"]["arms"]["off"]["ctx_sha"] = "0" * 64
    out = ck.check_i2(rws)
    assert not out["ok"] and out["mismatch"] == [{"qid": "QE", "arm": "off", "what": "ctx_sha"}]
    rws = rows()
    rws["QD"]["arms_skipped"] = "book_anchor_not_invoked"
    rws["QD"]["arms"]["nopin"] = rws["QD"]["arms"]["off"] = None
    assert ck.check_i2(rws)["skipped_in_c"] == ["QD"] and not ck.check_i2(rws)["ok"]
    rws = rows()
    rws["QF"]["arms"]["ctrl"]["ba_calls"] = 1
    assert ck.check_i2(rws)["skip_inconsistent"] == ["QF"]


def test_i3_detects_d_nopin_not_equal_to_p_s_and_reports_subset_exceptions():
    subs = ck.subsets(rows())
    bad = {**subs, "D_nopin": ["QA", "QD"]}
    out = ck.check_i3(bad)
    assert not out["ok"] and out["d_nopin_minus_p_s"] == ["QD"]
    assert out["d_nopin_not_in_d_off"] == ["QD"]
    assert ck.check_i3({**subs, "D_off": ["QA", "QC"]})["p_m_not_in_d_off"] == ["QB"]
    assert ck.check_i3({**subs, "D_off": ["QA", "QC"]})["ok"]


def test_i4_detects_route_and_strategy_errors_and_lists_intent_failures():
    rws = rows()
    rws["QA"]["arms"]["off"]["stats"]["route_used"] = "fallback"
    rws["QC"]["arms"]["nopin"]["stats"]["strategy_errors"] = {"semantic": "Timeout"}
    rws["QE"]["intent_ok"] = False
    out = ck.check_i4(rws)
    assert not out["ok"]
    assert out["route_mismatch"] == ["QA"] and out["strategy_errors"] == {"QC": ["nopin"]}
    assert out["intent_failed"] == ["QE"]
    rws = rows()
    rws["QE"]["intent_ok"] = False
    assert ck.check_i4(rws)["ok"]
    rws["QB"]["arms"]["ctrl"]["stats"]["fusion_alpha"] = 0.0
    assert ck.check_i4(rws)["applied"] == ["QB"]


def test_i5_lists_an_off_pool_that_is_not_ctrl_minus_anchors():
    rws = rows()
    rws["QC"]["arms"]["off"]["pool"].append(pool_entry("ps:isa.99.1", "sql_supplement", 0.4))
    out = ck.check_i5(rws)
    assert [e["qid"] for e in out["exceptions"]] == ["QC"]
    assert out["exceptions"][0]["extra_in_off"] == ["ps:isa.99.1"]
    assert "iii" in out["exceptions"][0]["tags"]


# ---------------------------------------------------------------- mechanisms

def mech_row(ctrl, off):
    return row("Q", ctrl, None, off)


def test_mechanism_i_an_anchor_leaves_the_core():
    r = rows()["QC"]
    assert ck.mechanisms(r)["tags"] == ["i"]


def test_mechanism_ii_only_non_anchor_reorder():
    ctrl = arm(D[:5], pool=ba_pool(D[:5], ["ps:isa.60.1"]))
    off = arm([D[1], D[0], *D[2:5]], pool=ba_pool(D[:5], []))
    out = ck.mechanisms(mech_row(ctrl, off))
    assert out["tags"] == ["ii"]


def test_mechanism_iii_supplement_and_rerank_drift():
    ctrl = arm(D[:5], pool=ba_pool(D[:5], ["ps:isa.60.1"]))
    off = arm(D[:5], pool=ba_pool(D[:6], []))
    off["pool"][0]["rerank_score"] = 0.5 + 2e-7
    out = ck.mechanisms(mech_row(ctrl, off))
    assert out["tags"] == ["iii"] and out["max_abs_drr"] == pytest.approx(2e-7)


def test_mechanism_iv_aux_slot_changes():
    ctrl = arm([*D[:4], "ps:isa.60.1"], aux=["ps:exo.40.34"], strategies=BA,
               pool=ba_pool(D[:5], ["ps:isa.60.1"]))
    off = arm(D[:5], aux=["ps:exo.16.1"], pool=ba_pool(D[:5], []))
    assert ck.mechanisms(mech_row(ctrl, off))["tags"] == ["i", "iv"]


# ---------------------------------------------------------------- plan, judge ids, order, freeze

def test_gen_plan_is_deterministic_shuffled_and_skips_ctrl_equal_contexts():
    rws = rows()
    subs = ck.subsets(rws)
    plan = ck.gen_plan(rws, subs)
    assert plan == ck.gen_plan(rws, subs)
    items = plan["items"]
    assert plan["meta"]["counts"] == {"ctrl": 18, "nopin": 6, "off": 18}
    assert {(i["qid"], i["arm"]) for i in items if i["arm"] == "nopin"} == {("QA", "nopin")}
    assert not any(i["qid"] == "QB" and i["arm"] == "nopin" for i in items)
    assert [i["order"] for i in items] == list(range(len(items)))
    blocks = [(i["qid"], i["rep"]) for i in items]
    assert blocks != sorted(blocks)                            # shuffled by (q, rep) blocks
    starts = {}
    for n, b in enumerate(blocks):
        starts.setdefault(b, n)
    for b, n in starts.items():
        size = sum(1 for x in blocks if x == b)
        assert blocks[n:n + size] == [b] * size                 # each block contiguous
    for i in items:
        assert i["ctx_sha"] == rws[i["qid"]]["arms"][i["arm"]]["ctx_sha"]
    assert ck.gen_plan(rws, subs, seed=1)["items"] != items


def test_judge_ids_and_order():
    subs = ck.subsets(rows())
    ids = ck.judge_ids(subs)
    assert ids == {"ctrl": ["QA", "QB", "QC"], "nopin": ["QA"], "off": ["QA", "QB", "QC"]}
    order = ck.judge_order(ids)
    assert order == ck.judge_order(ids)
    assert len(order["coverage"]) == 18 and len(order["strict"]) == 9
    assert order["strict"] == [d for d in order["coverage"] if int(d.split("_r")[1]) <= 3]
    for rep in range(1, 7):
        assert sorted(d for d in order["coverage"] if d.endswith(f"_r{rep}")) == \
            [f"{a}_r{rep}" for a in ("ctrl", "nopin", "off")]
    reps = [int(d.split("_r")[1]) for d in order["coverage"]]
    assert reps == sorted(reps)
    assert {tuple(order["coverage"][3 * k:3 * k + 3]) for k in range(6)} != \
        {tuple(f"{a}_r{k + 1}" for a in ("ctrl", "nopin", "off")) for k in range(6)}
    no_nopin = ck.judge_order({**ids, "nopin": []})
    assert len(no_nopin["coverage"]) == 12 and not any("nopin" in d for d in no_nopin["coverage"])


def test_freeze_detects_any_changed_file(tmp_path):
    files = {name: {"x": name} for name in ck.FROZEN}
    for name, doc in files.items():
        (tmp_path / name).write_text(json.dumps(doc))
    record = ck.freeze_record(tmp_path)
    assert ck.freeze_record(tmp_path) == record
    assert ck.verify_freeze(tmp_path, record) == []
    (tmp_path / "gen_plan.json").write_text("{}")
    assert ck.verify_freeze(tmp_path, record) == ["gen_plan.json"]
    (tmp_path / "judge_order.json").unlink()
    assert ck.verify_freeze(tmp_path, record) == ["gen_plan.json", "judge_order.json"]


# ---------------------------------------------------------------- overlap

def test_overlap_with_eval3c():
    rws = rows()
    subs = ck.subsets(rws)
    ref = {"c43": ["QA", "QB", "QC", "QH"], "ba39": ["QA", "QB", "QH"],
           "pinned20": ["QA", "QB"], "pinned_single19": ["QA", "QH"],
           "routes": {q: r["arms"]["ctrl"]["stats"]["route_used"] for q, r in rws.items()}
           | {"QH": "R5", "QD": "fallback"}}
    out = ck.overlap(rws, subs, ref)
    assert out["n"] == {"D_nopin&ba39": 1, "D_off&ba39": 2, "D_nopin&pinned_single19": 1}
    assert out["only_d_off"] == [{"qid": "QC", "reason": "not in eval3c's 39"}]
    assert out["only_ba39"] == [{"qid": "QH", "reason": "not retrieved in this run"}]
    assert out["only_pinned_single19"] == [{"qid": "QH", "reason": "not retrieved in this run"}]
    assert out["c_union_c43"] == ["QA", "QB", "QC", "QD", "QH"]
    assert out["route_diff"] == [{"qid": "QD", "eval3c": "fallback", "now": "R5",
                                  "in_c": True, "in_c43": False}]


# ---------------------------------------------------------------- smoke (§6)

def p(*ids):
    return [f"ps:{i}" for i in ids]


def smoke_rows(first_r1="R1Q"):
    q024 = row("GENERAL_BIBLE_QUESTION_024",
               arm(p("isa.6.1", "isa.13.1", "mrk.1.1", "mat.3.1", "luk.3.1")),
               arm(p("mrk.1.1", "mat.3.1", "luk.3.1", "jhn.1.19", "isa.40.1")),
               arm(p("mrk.1.1", "mat.3.1", "luk.3.1", "jhn.1.19", "mat.11.2")))
    c096 = arm(p("rev.21.9", "exo.40.34", "2ch.5.11", "ezk.43.1", "exo.16.1"))
    q096 = row("GENERAL_BIBLE_QUESTION_096", c096, copy.deepcopy(c096),
               arm(p("exo.40.34", "2ch.5.11", "ezk.43.1", "exo.16.1", "isa.4.2")))
    c001 = arm(p("mat.1.18", "isa.7.10", "mat.4.12", "mat.12.15", "isa.30.19"))
    q001 = row("GENERAL_BIBLE_QUESTION_001", c001, copy.deepcopy(c001),
               arm(p("mat.1.18", "isa.7.10", "mat.4.12", "mat.12.15", "isa.13.1")))
    nat050 = p("mat.22.23", "mrk.12.18", "luk.20.27", "jhn.12.12", "mat.16.21")
    q050 = row("GENERAL_BIBLE_QUESTION_050",
               arm(["ck:exo.3.13~exo.3.22", "ck:exo.3.1~exo.3.13", *nat050[:3]]),
               arm(nat050), arm(nat050))
    c013 = arm(p("1co.15.12", "1co.15.35", "1co.15.1", "gen.15.1", "2co.6.14"),
               strategies={"ps:gen.15.1": "book_anchor"})
    q013 = row("GENERAL_BIBLE_QUESTION_013", c013, copy.deepcopy(c013),
               arm(p("1co.15.12", "1co.15.35", "1co.15.1", "2co.6.14", "rom.6.1")))
    r1 = arm(["vs:jhn.3.16"], route="R1", ba_calls=0, pool=[])
    qr1 = row(first_r1, r1, copy.deepcopy(r1), copy.deepcopy(r1), forced=True)
    return {r["qid"]: r for r in (q024, q096, q001, q050, q013, qr1)}


def test_smoke_expectations_pass_and_fail():
    rws = smoke_rows()
    assert ck.smoke_problems(rws, "R1Q") == []
    bad = smoke_rows()
    bad["GENERAL_BIBLE_QUESTION_024"]["arms"]["off"]["ids"][4] = "ps:isa.40.1"
    bad["GENERAL_BIBLE_QUESTION_013"]["arms"]["off"]["results"][4]["source_strategy"] = \
        "book_anchor"
    bad["R1Q"]["arms"]["off"]["ctx_sha"] = "0" * 64
    probs = ck.smoke_problems(bad, "R1Q")
    assert len(probs) == 3
    assert any("024" in x for x in probs) and any("013" in x for x in probs)
    assert any("R1Q" in x for x in probs)
    missing = smoke_rows()
    del missing["GENERAL_BIBLE_QUESTION_050"]
    assert any("050" in x for x in ck.smoke_problems(missing, "R1Q"))


# ---------------------------------------------------------------- eval3c reference

def raw_item(qid, sources, strategies, question="q"):
    return {"question_id": qid, "question": question, "route_used": "R5",
            "strategies_used": strategies, "sources": sources}


def src(pid, strategy, score):
    return {"id": pid, "strategy": strategy, "score": score}


def test_eval3c_reference_from_raw_and_lexicon():
    raw = [
        raw_item("A", [src("a1", "book_anchor", 0.908), src("a2", "book_anchor", 0.904),
                       src("d1", "hybrid_hybrid", 0.9)], ["semantic", "book_anchor"], "單書"),
        raw_item("B", [src("b1", "book_anchor", 0.708), src("d1", "hybrid_hybrid", 0.7),
                       src("x", "event_registry", None)], ["semantic", "book_anchor"], "多書"),
        raw_item("C", [src("d1", "hybrid_hybrid", 0.9), src("c1", "book_anchor", 0.3)],
                 ["semantic", "book_anchor"], "單書"),
        raw_item("D", [src("d1", "hybrid_hybrid", 0.9)], ["semantic", "book_anchor"], "單書"),
        {**raw_item("E", [src("v", "verse_direct", None)], ["verse_direct"]), "route_used": "R1"},
    ]
    books = {"單書": ["以賽亞書"], "多書": ["出埃及記", "啟示錄"], "q": []}
    ref = ck.build_eval3c_ref(raw, lambda q: books[q])
    assert ref["c43"] == ["A", "B", "C", "D"] and ref["ba39"] == ["A", "B", "C"]
    assert ref["pinned20"] == ["A", "B"] and ref["pinned_single19"] == ["A"]
    assert ref["n_pinned"] == {"A": 2, "B": 1}
    assert ref["first_r1"] == "E" and ref["routes"]["E"] == "R1"
    ba39 = [{"qid": "A", "n_pinned": 2, "multi_book": False},
            {"qid": "B", "n_pinned": 1, "multi_book": True},
            {"qid": "C", "n_pinned": 0, "multi_book": False}]
    assert ck.build_eval3c_ref(raw, lambda q: books[q], ba39=ba39)["ba39_crosscheck"] is True
    with pytest.raises(ck.CheckError):
        ck.build_eval3c_ref(raw, lambda q: books[q], ba39=ba39[:2])


def test_the_frozen_eval3c_reference_has_the_prereg_counts():
    ref = json.loads((_EXP / "eval3c_ref.json").read_text(encoding="utf-8"))
    assert (len(ref["c43"]), len(ref["ba39"]), len(ref["pinned20"]),
            len(ref["pinned_single19"])) == (43, 39, 20, 19)
    assert set(ref["pinned_single19"]) | {"GENERAL_BIBLE_QUESTION_096"} == set(ref["pinned20"])
    assert ref["first_r1"] == "GENERAL_BIBLE_QUESTION_042" and len(ref["routes"]) == 500
    assert "VERSE_LOOKUP_097" in ref["pinned_single19"]

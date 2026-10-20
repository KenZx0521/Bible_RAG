"""Question set for the chronology card's trigger recall (evaluation/experiments/2026-10-19_regnal_qset/).

No agent is launched and Ollama is never called: the claude command line is checked as a value, launches
go through a fake that writes synthetic stream-json transcripts, and the scorer runs on a synthetic
regnal layer with template questions built here (no scripture text, no question of experiment A's
sets). Tests that read the reference layer skip when the store is not mounted.
"""

import json
import os
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

QSET = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-19_regnal_qset"
if str(QSET) not in sys.path:
    sys.path.insert(0, str(QSET))

import banned_q as B  # noqa: E402
import claude_q as CL  # noqa: E402
import mech_q as M  # noqa: E402
import prompt_q as P  # noqa: E402
import q_common as Q  # noqa: E402
import run_q as RQ  # noqa: E402
import score_q as SC  # noqa: E402
import spec_q as S  # noqa: E402
import transcript_q as TR  # noqa: E402

STORE_OK = Q.REF_A.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({Q.REF_A})")
REG = Q.regnal()


# ---------------------------------------------------------------- synthetic reference and layer

def ref_row(rid, kd, name, pred, ptype, reign, age=None, father=None, aliases=(), sync=()):
    v = "x.1.1"
    return {"id": rid, "kingdom": kd, "name": name, "father": [father, v] if father else None,
            "pred": [pred, ptype, v] if ptype else None, "sync": [list(s) for s in sync],
            "reign": [str(reign), reign, v], "age": [age, v] if age else None, "mother": None, "mother_desc": None,
            "death": None, "aliases": [[a, v, "t"] for a in aliases], "alt": []}


SYN_ROWS = [
    ref_row("I01", "I", "耶羅波安", None, "founder", 22),
    ref_row("I02", "I", "拿答", "I01", "son", 2, father="耶羅波安"),
    ref_row("I03", "I", "巴沙", "I02", "usurp", 24),
    ref_row("I04", "I", "以拉", "I03", "son", 2, father="巴沙"),
    ref_row("I05", "I", "心利", "I04", "usurp", 0.02),
    ref_row("J01", "J", "羅波安", None, "founder", 17, age=41),
    ref_row("J02", "J", "亞比央", "J01", "son", 3, father="羅波安", aliases=("亞比雅",)),
    ref_row("J03", "J", "亞撒", "J02", "son", 41, father="亞比央"),
    ref_row("J04", "J", "約沙法", "J03", "son", 25, age=35, father="亞撒"),
    ref_row("J05", "J", "約蘭", "J04", "son", 8, age=32, father="約沙法"),
]


def layer_bytes(rows):
    """A regnal layer document (contract format) of reference rows, with other node ids (L00…)."""
    ids = {r["id"]: f"L{n:02d}" for n, r in enumerate(rows)}
    nodes = []
    for n, r in enumerate(rows):
        f = {"reign": [r["reign"][1], "x.1.1", "ki"]}
        if r["age"]:
            f["age"] = [r["age"][0], "x.1.1", "ki"]
        if r["father"]:
            f["father"] = [r["father"][0], "x.1.1", "ki"]
        nodes.append({"id": ids[r["id"]], "kingdom": r["kingdom"], "name": r["name"],
                      "aliases": [a[0] for a in r["aliases"]], "fields": f, "evidence": [], "order": n,
                      "has_acc": True})
    edges = [[ids[r["pred"][0]], ids[r["id"]], r["pred"][1], "x.1.1"] for r in rows if r["pred"] and r["pred"][0]]
    doc = {"nodes": nodes, "edges": edges, "fallback_edges": [], "syncs": [], "conflicts": []}
    return json.dumps(doc, ensure_ascii=False).encode("utf-8"), ids


def syn_rules(rule_seeds=None):
    data, _ = layer_bytes(SYN_ROWS)
    layer = REG.layer.parse_layer(data)
    return SC.Rules(SC.make_fire(REG.trigger.trigger, layer), rule_seeds, REG.engine, layer,
                    {"layer": {"sha256": Q.sha256_bytes(data)}})


def item(iid, kind, qtype, kd, start, question, gold=None, k=None, n=None, other=None, valid=True, lc=True,
         flags=()):
    return {"item_id": iid, "kind": kind, "qtype": qtype, "kingdom": kd, "start": start, "other": other, "k": k,
            "n": n, "gold": gold, "question": question, "valid": valid, "label_consistent": lc,
            "flags": list(flags), "writer": "opus", "persona": "casual"}


SYN_ITEMS = [
    item("zz-01", "pos", "S1a", "I", "I02", "以色列王拿答之後的第二位王是誰？", gold="I04", k=2),
    item("zz-02", "pos", "S1a", "J", "J04", "猶大王約沙法之前第二位王是誰？", gold="J02", k=-2),
    item("zz-03", "pos", "S1a", "J", "J01", "羅波安的孫子的兒子是哪位？", gold="J04", k=3),
    item("zz-04", "pos", "S1a", "I", "I01", "那位王之後的第三位王是誰？", gold="I04", k=3),
    item("zz-05", "pos", "S1c", "I", "I02", "拿答之後第二個篡位的人是誰？", gold="I05", n=2),
    item("zz-06", "pos", "S4", "J", "J04", "約沙法出生時在位的王是誰？", gold="J03"),
    item("zz-07", "pos", "S1b", "J", "J01", "從羅波安到約沙法，王位交接了幾次？", gold=3, other="J04"),
    item("zz-08", "pos", "S1a", "J", "J02", "亞比央之後的第二位王是誰？", gold="J04", k=2, lc=False),
    item("zz-09", "pos", "S1a", "J", "J03", "亞撒之後的第一位", gold="J05", k=2, valid=False),
    item("zz-10", "near", "N1", "J", "J03", "亞撒一共統治多少年？"),
    item("zz-11", "near", "N5", "J", "J04", "從大衛到約沙法相隔幾代？", lc=False),
]


# ---------------------------------------------------------------- banned and CUES

def top_level_branches(pattern):
    """The top-level alternatives of a regex source (outside groups, classes and escapes)."""
    out, depth, cls, esc, cur = [], 0, False, False, ""
    for ch in pattern:
        if esc:
            esc, cur = False, cur + ch
            continue
        if ch == "\\":
            esc, cur = True, cur + ch
            continue
        if cls:
            cls = ch != "]"
        elif ch == "[":
            cls = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    return out + [cur]


CUE_EXAMPLES = {   # the last of S1a, S1b, S1c and S4: the 2026-10-19 relaxation's group ``new``
    "S1a": ["約西亞之後第四位", "往前數第三位", "接續他作王的是誰", "繼位的是誰", "往前推兩任"],
    "S1b": ["王位交接幾次", "相隔幾代", "王位更迭了幾次"],
    "S1c": ["第二個篡位", "之後，第二個靠謀反登基"],
    "S4": ["出生時在位的王", "出生那一年，誰在做王"],
}


def test_every_cue_branch_has_a_literal_on_the_banned_list():
    """A CUES branch added or changed without a literal in CUE_LITERALS fails here."""
    cues = REG.trigger.CUES
    assert set(cues) == set(CUE_EXAMPLES)
    for qtype, pat in cues.items():
        branches = top_level_branches(pat.pattern)
        assert len(branches) == len(CUE_EXAMPLES[qtype]), qtype
        for branch, example in zip(branches, CUE_EXAMPLES[qtype]):
            assert re.search(branch, example), (qtype, branch)
            essential = [w for w in B.CUE_LITERALS if w in example
                         and not re.search(branch, example.replace(w, "ㄅ" * len(w)))]
            assert essential, (qtype, branch, example)


# one example per alternative of the relaxation's group ``new`` (trigger._S1A_NEW … _S4_NEW, the k = ±1
# and reversed-birth groups split too), in order
NEW_EXAMPLES = {
    "S1a": ["之後再往下數第三個王是誰", "往前倒推兩位是誰", "之後，隔兩任的王是誰", "之後兩任王是誰",
            "的下一任是誰", "的上上任是誰", "的繼任者是誰", "死後，接著作王的是誰"],
    "S1b": ["中間換手了幾次", "王位一共傳了幾次", "換了幾次王", "經歷了幾次更迭"],
    "S1c": ["之後，第二個靠謀反登基的是誰", "以後，殺王奪位的人裡面，第二個是誰"],
    "S4": ["出生那一年，誰在做王", "出生於哪一位王在位期間", "是在哪位王在位時出生的"],
}


def _leaf_branches(pattern: str) -> list[str]:
    out = []
    for b in top_level_branches(pattern):
        m = re.fullmatch(r"\(\?P<adj\d?>(.*)\)", b)
        out.extend(top_level_branches(m.group(1)) if m else [b])
    return out


def test_every_relaxation_alternative_has_a_literal_on_the_banned_list():
    """Inside group ``new`` too: an alternative added without a literal in CUE_LITERALS fails here."""
    t = REG.trigger
    for qtype, src in (("S1a", t._S1A_NEW), ("S1b", t._S1B_NEW), ("S1c", t._S1C_NEW), ("S4", t._S4_NEW)):
        leaves = _leaf_branches(src)
        assert len(leaves) == len(NEW_EXAMPLES[qtype]), qtype
        for leaf, example in zip(leaves, NEW_EXAMPLES[qtype]):
            assert re.search(leaf, example), (qtype, leaf, example)
            essential = [w for w in B.CUE_LITERALS if w in example
                         and not re.search(leaf, example.replace(w, "ㄅ" * len(w)))]
            assert essential, (qtype, example)


def test_banned_check_catches_cues_literals_terms_and_markers():
    terms = {h.term for h in B.check_prompt_text("請問約西亞之後第四位王")}
    assert {"CUES:S1a", "之後"} <= terms
    assert {"召回"} <= {h.term for h in B.check_prompt_text("量召回")}
    assert {"regnal"} <= {h.term for h in B.check_prompt_text("see regnal layer")}
    assert {"Kay"} <= {h.term for h in B.check_prompt_text("ask Kay")}
    assert not B.check_prompt_text("讀者：一般信徒。king: 亞撒（猶大）")


def test_banned_lists_load_pinned_ho_and_a_files():
    assert set(B.HO.PROMPT_TERMS) <= set(B.PROMPT_TERMS)
    assert set(B.A.A_PROMPT_TERMS) <= set(B.PROMPT_TERMS)
    assert {"trigger.py", "trigger.CUES", "_KTH", "utils.regnal", "年表卡", "ref_layer"} <= set(B.MEMORY_MARKERS)


def test_plain_english_words_are_prompt_only_never_memory_markers():
    """'regnal year' and 'cues' are ordinary English (a writer's English thinking may hold them): the
    prompt check still bans them, a transcript does not void a job for them."""
    assert not {"regnal", "cues", "cue"} & {t.lower() for t in B.MEMORY_MARKERS}
    assert {"regnal", "cues"} <= {h.term.lower() for h in B.check_prompt_text("regnal cues")}
    assert not B.memory_hits("in which regnal year of Asa; avoid giving CUES to the answer")
    assert B.memory_hits("as utils.regnal and trigger.CUES say")


def test_prompt_file_and_fixed_texts_pass_the_banned_check():
    pf = P.load_prompts()
    assert set(pf.sections) == set(P.SECTIONS)
    for name, text in (("defs", P.definitions_text()), ("aspects", "\n".join(P.ASPECTS.values())),
                       ("personas", "\n".join(P.PERSONA_TEXT.values()))):
        assert not B.check_prompt_text(text, name), name
    assert set(P.PERSONA_TEXT) == set(Q.PERSONAS) and set(P.DEFINITIONS) == set(Q.INTENT.values())


def test_writer_prompts_of_a_synthetic_job_pass_cues_and_banned():
    ch, pf = S.Chains(SYN_ROWS), P.load_prompts()
    slots = [dict(slot="q1", kind="pos", qtype="S1a", intent="offset", start="J04", other=None, k=-2, n=None),
             dict(slot="q2", kind="pos", qtype="S1b", intent="handovers", start="J01", other="J04", k=None, n=None),
             dict(slot="q3", kind="pos", qtype="S1c", intent="usurper_n", start="I02", other=None, k=None, n=2),
             dict(slot="q4", kind="near", qtype="N1", intent="attribute", start="J03", other=None, aspect="mother")]
    system, user, schema = P.gen_prompt(pf, ch, {"persona": "casual", "slots": slots})
    for text in (system, user, json.dumps(schema, ensure_ascii=False)):
        assert not B.cue_hits(text) and not B.check_prompt_text(text)
    assert "亞比雅" not in user          # J02 is not in this job
    assert "k: -2 (2 places earlier" in user and "n: 2" in user


def test_a_cue_in_a_rendered_writer_prompt_refuses():
    ch, pf = S.Chains(SYN_ROWS), P.load_prompts()
    bad = P.PromptFile(pf.path, pf.sha256, {**pf.sections, "task_gen": pf.sections["task_gen"] + "之後\n"})
    slot = dict(slot="q1", kind="pos", qtype="S1a", intent="offset", start="J04", other=None, k=2, n=None)
    with pytest.raises(Q.QError, match="banned"):
        P.gen_prompt(bad, ch, {"persona": "casual", "slots": [slot]})


def test_label_prompt_allows_cue_words_in_questions_but_not_markers():
    pf = P.load_prompts()
    system, user, schema = P.label_prompt(pf, [("x01", "約沙法之後第二位王是誰？"), ("x02", "第二個篡位的人？")])
    assert "x01：約沙法之後第二位王是誰？" in user and not B.check_prompt_text(system)
    assert schema["properties"]["items"]["minItems"] == 2
    with pytest.raises(Q.QError, match="memory markers"):
        P.label_prompt(pf, [("x01", "regnal_layer 的問題")])


@needs_store
def test_every_writer_prompt_of_the_spec_passes_cues_and_banned():
    ref = S.load_ref()
    spec, ch, pf = S.build_spec(ref), S.Chains(ref.rows), P.load_prompts()
    for job in spec["jobs"] + [S.probe_job(spec, "opus")]:
        system, user, schema = P.gen_prompt(pf, ch, job)
        for text in (system, user, json.dumps(schema, ensure_ascii=False)):
            assert not B.cue_hits(text), job["job_id"]
        for s in job["slots"]:
            assert s["item_id"] not in user and "p1" not in user and "p2" not in user


# ---------------------------------------------------------------- reference and spec

def test_chains_follow_pred_links_and_refuse_solomon():
    ch = S.Chains(SYN_ROWS)
    assert ch.chain["J"][0] == "J01" and ch.chain["I"][-1] == "I05"
    assert ch.born("J04") == ("J03", 6.0, 1)
    rows = [ref_row("J00", "J", "所羅門", None, "founder", 40)] + [
        dict(r, pred=["J00", "son", "x"]) if r["id"] == "J01" else r for r in SYN_ROWS]
    with pytest.raises(Q.QError, match="所羅門"):
        S.Chains(rows)
    off = [ref_row("J00", "U", "所羅門", None, "founder", 40)] + SYN_ROWS
    assert "J00" not in S.Chains(off).pos


def test_derive_v2_drops_solomon_and_makes_rehoboam_founder():
    rows = [ref_row("J00", "J", "所羅門", None, "founder", 40)] + [
        dict(r, pred=["J00", "son", "1ki.11.43"]) if r["id"] == "J01" else r for r in SYN_ROWS]
    out = S.derive_v2(rows)
    assert [r["id"] for r in out] == [r["id"] for r in SYN_ROWS]
    assert next(r for r in out if r["id"] == "J01")["pred"] == [None, "founder", "1ki.11.43"]
    assert next(r for r in rows if r["id"] == "J01")["pred"][0] == "J00"   # the input is not changed


def test_safe_names_never_offer_an_alias_that_is_another_kings_name():
    rows = SYN_ROWS + [ref_row("J06", "J", "亞哈謝", "J05", "son", 1, aliases=("亞撒", "約哈斯"))]
    ch = S.Chains(rows)
    assert ch.safe_names("J06") == ["亞哈謝", "約哈斯"] and ch.safe_names("J02") == ["亞比央", "亞比雅"]


def test_spread_draws_every_key_once_before_repeats():
    pool = [{"start": s, "v": i} for i, s in enumerate("aabbbc")]
    out = S.spread(pool, random.Random(1))
    assert sorted(o["start"] for o in out[:3]) == ["a", "b", "c"]
    rep = S.draw_repeat([{"start": "a", "cell": "x"}, {"start": "b", "cell": "y"}], 3, random.Random(2), "S4")
    assert len(rep) == 3 and len({r["cell"] for r in rep[:2]}) == 2
    with pytest.raises(Q.QError):
        S.draw_repeat([{"start": "a", "cell": "x"}], 3, random.Random(2), "S4")


@needs_store
def test_load_ref_reads_v2_or_derives_in_memory_and_never_writes(tmp_path):
    before = Q.sha256_file(Q.REF_A)
    derived = S.load_ref(v2=tmp_path / "missing.json")
    assert derived.source.startswith("derived:") and derived.sha256 == Q.REF_V2_DERIVED_SHA256
    assert Q.sha256_bytes(Q.canonical(list(derived.rows))) == Q.REF_V2_DERIVED_SHA256
    v2 = tmp_path / "ref_layer_v2.json"
    v2.write_bytes(Q.canonical(list(derived.rows)))
    got = S.load_ref(v2=v2)
    assert got.source == "ref_layer_v2" and got.matches_derivation and got.rows == derived.rows
    bad = tmp_path / "ref_a.json"
    bad.write_bytes(Q.REF_A.read_bytes() + b" ")
    with pytest.raises(Q.QError, match="frozen"):
        S.load_ref(v2=v2, a=bad)
    assert Q.sha256_file(Q.REF_A) == before and not list(tmp_path.glob("*.tmp"))


@needs_store
def test_cells_on_the_reference_layer():
    ch = S.Chains(S.load_ref().rows)
    c = S.cells(ch)
    assert {t: len(v) for t, v in c.items()} == {"S1a": 136, "S1b": 99, "S1c": 13, "S4": 13}
    assert all(x["kingdom"] == "I" for x in c["S1c"])
    assert not {"J06", "J19"} & {x["start"] for x in c["S4"]}
    assert len(S.units(ch)) == 34 and len(ch.chain["J"]) == 20 and "所羅門" not in [ch.name(x) for x in ch.pos]


@needs_store
def test_spec_is_reproducible_from_its_seed_and_keeps_its_rules():
    ref = S.load_ref()
    spec = S.build_spec(ref)
    assert S.spec_sha(spec) == S.spec_sha(S.build_spec(ref)) != S.spec_sha(S.build_spec(ref, Q.SEED + 1))
    part = spec["partition"]
    for u in spec["units"]:
        assert len({part[x] for x in u}) == 1
    ch = S.Chains(ref.rows)
    seen: dict[str, list] = {}
    for side in Q.SETS:
        jobs = [j for j in spec["jobs"] if j["set"] == side]
        assert spec["drawn"][side] == Q.QUOTA[side]
        assert abs(sum(j["writer"] == "opus" for j in jobs) - sum(j["writer"] == "sonnet" for j in jobs)) <= 1
        for j in jobs:
            types = [S.slot_type(s) for s in j["slots"]]
            assert types.count("S1a") == 1 and len(types) == len(set(types)) and 2 <= len(types) <= S.JOB_MAX
            assert [s["slot"] for s in j["slots"]] == [f"q{i}" for i in range(1, len(types) + 1)]
            for s in j["slots"]:
                assert part[s["start"]] == side and (not s["other"] or part[s["other"]] == side)
                seen.setdefault(s["cell"], []).append(j)
                if s["qtype"] == "S1b":
                    assert ch.kingdom(s["start"]) == ch.kingdom(s["other"])
    for cell, jobs in seen.items():
        assert len(jobs) <= S.MAX_PER_CELL
        assert len({j["job_id"] for j in jobs}) == len(jobs) and len({j["persona"] for j in jobs}) == len(jobs)
    assert spec["order"][:2] == ["p1-j00", "p2-j00"]
    assert sorted(spec["order"]) == sorted(j["job_id"] for j in spec["jobs"])
    pj = S.probe_job(spec, "opus")
    assert pj["set"] == "probe" and pj["from_job"].startswith("p1-") and len(pj["slots"]) == 3


# ---------------------------------------------------------------- scorer

def test_scorer_denominator_and_stages_without_rule_seeds():
    rules = syn_rules()
    rows = SC.score_rows(rules, SYN_ITEMS, S.Chains(SYN_ROWS))
    agg = SC.aggregate(rows)["positives"]
    assert agg["n"] == 8                                   # invalid excluded, label-inconsistent kept
    assert agg["R_trig"]["k"] == 6 and agg["R_seed"] == "n/a" and agg["R_card"] == "n/a"
    assert agg["R_card_oracle"]["k"] == 6
    assert agg["fail"] == {"cue_miss": 1, "king_miss": 1}
    assert agg["label_consistent"]["n"] == 7 and agg["label_inconsistent"]["R_trig"]["k"] == 1
    near = SC.aggregate(rows)["near"]
    assert near["n"] == 2 and near["fired"] == 1 and near["gray"] == {"n": 1, "fired": 1}
    by = {r["id"]: r for r in rows}
    assert by["zz-03"]["fail"] == "cue_miss" and by["zz-04"]["fail"] == "king_miss"
    assert by["zz-07"]["card_oracle"] and by["zz-05"]["oracle_why"] == "ok"


def test_scorer_with_pluggable_rule_seeds():
    def fake(layer, question):
        if "亞比央" in question:
            return SimpleNamespace(ids=[], reason="abstain")
        kings = REG.trigger.trigger(question, layer.names).kings
        chain = layer.view.chain["I"] + layer.view.chain["J"]
        ids = [y for k in kings for y in chain if layer.view.nodes[y]["name"] == k]
        return SimpleNamespace(ids=ids, reason=None)
    rows = SC.score_rows(syn_rules(fake), SYN_ITEMS, S.Chains(SYN_ROWS))
    agg = SC.aggregate(rows)["positives"]
    assert agg["R_seed"]["k"] == 5 and agg["R_card"]["k"] == 5 and agg["R_seed"]["n"] == 8
    by = {r["id"]: r for r in rows}
    assert by["zz-08"]["seed"] is False and by["zz-08"]["card_why"] == "no_seed"
    assert by["zz-07"]["card"] and by["zz-06"]["card"]


def test_wrong_payload_is_not_a_card_hit():
    rows = SC.score_rows(syn_rules(), [item("zz-21", "pos", "S1a", "I", "I02", "拿答之後的第二位王是誰？",
                                            gold="I05", k=2)], S.Chains(SYN_ROWS))
    assert rows[0]["fired"] and not rows[0]["card_oracle"] and rows[0]["oracle_why"] == "wrong_payload"


def test_ref_to_layer_maps_by_name_and_homonym_order():
    rows = SYN_ROWS + [ref_row("I06", "I", "耶羅波安", "I05", "son", 41)]
    data, ids = layer_bytes(rows)
    m = SC.ref_to_layer(S.Chains(rows), REG.layer.parse_layer(data).view)
    assert m["I01"] == ids["I01"] and m["I06"] == ids["I06"] and m["J04"] == ids["J04"]


def test_p2_records_aggregates_only_and_once(tmp_path):
    rows = SC.score_rows(syn_rules(), SYN_ITEMS, S.Chains(SYN_ROWS))
    out = {"utc": Q.now(), "set": "p2", "rules": {}, "aggregate": SC.aggregate(rows)}
    rec = SC.record(tmp_path, out, rows)
    text = (tmp_path / SC.P2_RUNS).read_text(encoding="utf-8")
    assert rec["run_index"] == 1 and len(text.splitlines()) == 1
    assert "zz-0" not in text and "拿答" not in text and "之後" not in text
    with pytest.raises(Q.QError, match="already"):
        SC.record(tmp_path, out, rows)
    assert SC.record(tmp_path, out, rows, again=True)["run_index"] == 2
    p1 = SC.record(tmp_path, dict(out, set="p1"), rows)
    assert "run_index" not in p1 and len(list((tmp_path / "scores").glob("p1_*.json"))) == 1


def test_score_layer_check_refuses_the_pre_fix_layer_and_p2_without_the_pin(monkeypatch):
    monkeypatch.setattr(Q, "SCORE_LAYER_SHA256", None)
    with pytest.raises(Q.QError, match="pre-fix"):
        SC.score_layer_check(Q.LAYER_PRE_FIX_SHA256, "p1")
    with pytest.raises(Q.QError, match="SCORE_LAYER_SHA256"):
        SC.score_layer_check("ab" * 32, "p2")
    SC.score_layer_check("ab" * 32, "p1")                      # P1 before the pin: allowed, sha recorded
    monkeypatch.setattr(Q, "SCORE_LAYER_SHA256", "cd" * 32)
    with pytest.raises(Q.QError, match="pinned"):
        SC.score_layer_check("ab" * 32, "p1")
    SC.score_layer_check("cd" * 32, "p2")
    assert SC.layer_role("cd" * 32) == "score_pin" and SC.layer_role(Q.LAYER_PRE_FIX_SHA256) == "pre_fix"
    assert SC.layer_role("ef" * 32) == "unpinned"


@pytest.mark.parametrize("cmd", (["score", "--set", "p1"], ["gt"], ["regress"]))
def test_every_scorer_command_needs_an_explicit_layer(cmd, capsys):
    with pytest.raises(SystemExit):
        SC.main(cmd)
    assert "--layer" in capsys.readouterr().err


def test_load_rules_without_a_lexicon_taking_layer_calls_the_two_argument_trigger(tmp_path, monkeypatch):
    """A checkout from before the rule-seed change: no with_lexicon, a two-argument trigger."""
    data, _ = layer_bytes(SYN_ROWS)
    (tmp_path / "regnal_layer.json").write_bytes(data)
    fake = SimpleNamespace(trigger=SimpleNamespace(trigger=lambda question, names: REG.trigger.trigger(question, names)),
                           engine=REG.engine, seeds=SimpleNamespace(),
                           layer=SimpleNamespace(parse_layer=REG.layer.parse_layer),
                           routing=REG.routing, files_sha256=dict(REG.files_sha256))
    monkeypatch.setattr(SC, "regnal", lambda: fake)
    rules = SC.load_rules(tmp_path / "regnal_layer.json")
    assert rules.provenance["lexicon"] is None and rules.fire("拿答之後的第二位王是誰？").fired
    assert "ragcommon/routing.py" in rules.provenance["files_sha256"]
    with pytest.raises(Q.QError, match="no routing lexicon"):
        SC.load_rules(tmp_path / "regnal_layer.json", lexicon_path=tmp_path / "x.json")


def test_load_rules_attaches_the_lexicon_and_passes_blockers_like_the_backend(tmp_path, monkeypatch):
    """A checkout whose layer module has with_lexicon (the rule-seed change): the scorer builds the layer
    as make_active does and calls trigger(question, names, blockers); a missing lexicon refuses."""
    data, _ = layer_bytes(SYN_ROWS)
    (tmp_path / "regnal_layer.json").write_bytes(data)
    (tmp_path / "routing_lexicon.json").write_text("{}", encoding="utf-8")
    seen = []

    def trig(question, names, blockers=()):
        seen.append(blockers)
        return REG.trigger.trigger(question, names)

    def with_lexicon(layer, lex):
        assert lex == "LEX"
        return SimpleNamespace(view=layer.view, names=layer.names, sha256=layer.sha256, blockers=("押沙龍",),
                               chain_size=layer.chain_size)
    fake = SimpleNamespace(trigger=SimpleNamespace(trigger=trig), engine=REG.engine, seeds=SimpleNamespace(),
                           layer=SimpleNamespace(parse_layer=REG.layer.parse_layer, with_lexicon=with_lexicon),
                           routing=SimpleNamespace(load_lexicon=lambda p: "LEX"), files_sha256={})
    monkeypatch.setattr(SC, "regnal", lambda: fake)
    rules = SC.load_rules(tmp_path / "regnal_layer.json")
    assert rules.fire("拿答之後的第二位王是誰？").fired and seen == [("押沙龍",)]
    lex = rules.provenance["lexicon"]
    assert lex["sha256"] == Q.sha256_bytes(b"{}") and lex["blockers"] == 1 and rules.provenance["blockers_passed"]
    (tmp_path / "routing_lexicon.json").unlink()
    with pytest.raises(Q.QError, match="--lexicon"):
        SC.load_rules(tmp_path / "regnal_layer.json")


def test_paired_old_new_and_wilson():
    new = [{"id": "a", "kind": "pos", "fired": True}, {"id": "b", "kind": "pos", "fired": False},
           {"id": "c", "kind": "near", "fired": True}]
    old = [{"id": "a", "kind": "pos", "fired": False}, {"id": "b", "kind": "pos", "fired": False},
           {"id": "c", "kind": "near", "fired": False}]
    assert SC.paired(new, old) == {"positives": {"both": 0, "new_only": 1, "old_only": 0, "neither": 1},
                                   "near_fired": {"new": 1, "old": 0}}
    lo, hi = SC.wilson(35, 50)
    assert 0.55 < lo < 0.57 and 0.80 < hi < 0.82 and SC.wilson(0, 0) is None


@needs_store
def test_gt_and_regression_on_the_prod_layer():
    rules = SC.load_rules(Q.LAYER_PROD)
    assert rules.provenance["layer"]["role"] == "pre_fix"
    assert {k: v["fired"] for k, v in SC.gt_check(rules).items()} == {"ground_truth.json": 0, "ground_truth.v2.json": 0}
    reg = SC.regression(rules)
    assert reg["confirm"]["fired"] == 32 and reg["dev"]["fired"] == 27
    assert set(rules.provenance["files_sha256"]) >= {"trigger.py", "seeds.py", "engine.py", "layer.py"}


# ---------------------------------------------------------------- claude command line, transcripts, ledger

def test_argv_without_tools_keeps_the_blinding_flags():
    argv = CL.build_argv("SYS", "USER", {"type": "object"}, 0.3, "claude-opus-5-5", "xhigh", True, "none")
    i = argv.index("--tools")
    assert argv[i + 1] == "" and "--allowedTools" not in argv
    for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--json-schema"):
        assert flag in argv
    assert argv[argv.index("--setting-sources") + 1] == "local" and argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.3" and "bt-guard" in argv[argv.index("--settings") + 1]
    fb = CL.build_argv("S", "U", {}, 0.3, "m", "high", False, "bash_guard")
    assert fb[fb.index("--tools") + 1] == "Bash" and "--thinking-display" not in fb
    with pytest.raises(Q.QError):
        CL.build_argv("S", "U", {}, 0.3, "m", "high", False, "all")


def test_child_env_strips_claude_vars_and_puts_the_pinned_cli_first(tmp_path):
    env = CL.child_env(tmp_path, {"PATH": "/usr/bin", "CLAUDE_X": "1", "claudecode": "2", "HOME": "/h"})
    assert not [k for k in env if k.upper().startswith("CLAUDE")]
    assert env["PATH"].split(os.pathsep)[:2] == [str(tmp_path / "clibin"), str(tmp_path / "bin")]
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_pin_cli_links_only_the_pinned_executable(tmp_path, monkeypatch):
    vdir = tmp_path / "versions"
    vdir.mkdir()
    (vdir / "9.9.9").write_bytes(b"fake cli")
    monkeypatch.setattr(CL, "CLI_VERSIONS_DIR", vdir)
    monkeypatch.setattr(CL, "CLI_SHA256", {"9.9.9": Q.sha256_bytes(b"fake cli")})
    bindir = CL.pin_cli(tmp_path / "root", "9.9.9")
    assert (bindir / "claude").resolve() == (vdir / "9.9.9").resolve()
    (vdir / "9.9.9").write_bytes(b"updated")
    with pytest.raises(Q.QError, match="pinned sha"):
        CL.pin_cli(tmp_path / "root", "9.9.9")


def test_guard_copy_is_hos_verbatim():
    CL.check_guard_copy()
    ho = QSET.parent / "2026-10-14_graph_gd" / "ho_tools" / "bt_guard.py"
    assert (QSET / "bt_guard.py").read_bytes() == ho.read_bytes()


def test_model_fallback_and_agent_limit():
    ev = [{"type": "system", "subtype": "model_refusal_fallback", "original_model": "a", "fallback_model": "b"}]
    assert "fallback" in CL.model_fallback(ev, None, "a")
    assert "other models" in CL.model_fallback([], {"modelUsage": {"a": {}, "b": {}}}, "a")
    assert CL.model_fallback([], {"modelUsage": {"a": {}}}, "a") is None
    assert CL.agent_limit({"subtype": "error_max_budget_usd"}, 0.3) == "error_max_budget_usd"
    assert CL.agent_limit({"subtype": "success", "total_cost_usd": 0.31}, 0.3)
    assert CL.agent_limit(None, 0.3) is None


def events(tools=("StructuredOutput",), model="claude-opus-5-5", output=None, text="", calls=()):
    ev = [{"type": "system", "subtype": "init", "cwd": "/srv", "tools": list(tools), "mcp_servers": [],
           "model": model, "permissionMode": "dontAsk", "claude_code_version": "2.1.302"}]
    content = ([{"type": "text", "text": text}] if text else []) + list(calls)
    if content:
        ev.append({"type": "assistant", "message": {"content": content, "usage": {"input_tokens": 10,
                                                                                    "cache_read_input_tokens": 3000}}})
    ev.append({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.05,
               "structured_output": output or {"items": []}, "modelUsage": {model: {}}})
    return ev


def test_transcript_rules_allow_cue_words_in_output_but_not_markers():
    prompts = {"system": "你負責寫問題。", "user": "讀者：一般信徒。"}
    ok = TR.check_events(events(output={"items": [{"slot": "q1", "question": "拿答之後第二個篡位的是誰"}]}),
                         prompts, "claude-opus-5-5", "none")
    assert not [v for v in ok if v.level == "error"]
    leak = TR.check_events(events(text="I recall utils.regnal"), prompts, "claude-opus-5-5", "none")
    assert {"t_memory"} <= {v.rule for v in TR.blinding(leak)}
    think = {"type": "thinking", "thinking": "Ask in which regnal year of Asa he began; avoid cues to the answer."}
    plain = TR.check_events(events(calls=[think]), prompts, "claude-opus-5-5", "none")
    assert not TR.blinding(plain)
    tools = TR.check_events(events(tools=("Bash", "StructuredOutput")), prompts, "claude-opus-5-5", "none")
    assert "t_init" in {v.rule for v in tools}
    call = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}
    assert "t_tool" in {v.rule for v in TR.check_events(events(calls=[call]), prompts, "claude-opus-5-5", "none")}
    model = TR.check_events(events(model="claude-opus-4-8"), prompts, "claude-opus-5-5", "none")
    assert "t_init" in {v.rule for v in model}


def test_banned_words_in_a_writer_user_prompt_are_errors_but_not_in_a_label_prompt():
    prompts = {"system": "你是題目分類員。", "user": "x01：約沙法之後第二位王是誰？"}
    gen = TR.check_events(events(), prompts, "claude-opus-5-5", "none", "gen")
    lab = TR.check_events(events(), prompts, "claude-opus-5-5", "none", "label")
    assert "t_banned" in {v.rule for v in gen} and "t_banned" not in {v.rule for v in lab}


class FakeLauncher:
    """Stands in for claude_q.launch: writes the prompts record and a transcript; NO_RESULT writes none."""

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, root, run_id, system, user, schema, cap, model, effort, pin, cwd, extra_record=None):
        self.calls.append(run_id)
        return self.write(root, run_id, system, user, cap, model, self.outputs.pop(0))

    @staticmethod
    def write(root, run_id, system, user, cap, model, out):
        (root / "transcripts").mkdir(parents=True, exist_ok=True)
        (root / "prompts").mkdir(parents=True, exist_ok=True)
        (root / "prompts" / f"{run_id}.json").write_text(json.dumps({"system": system, "user": user}), encoding="utf-8")
        ev = events(model=model, output=out if isinstance(out, dict) else None)
        if out == "NO_RESULT":
            ev = ev[:1]
        elif out == "LIMIT":
            ev[-1] = {"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": cap}
        path = root / "transcripts" / f"{run_id}.jsonl"
        path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in ev) + "\n", encoding="utf-8")
        res = CL.result_event(ev)
        return CL.RunResult(run_id, path, 0, 0.1, res, CL.failure(0, res), CL.usage_of(res))


PIN = CL.CliPin("2.1.302", True, "none", {"opus": "claude-opus-5-5"})


def job(cap=0.3, kind="gen", sub="p1"):
    return RQ.Job(kind, sub, "p1-j00", "你負責寫問題。", "讀者：一般信徒。", {"type": "object"}, cap,
                  "claude-opus-5-5", "xhigh")


def test_run_job_reruns_infrastructure_failures_and_the_ledger_counts_their_caps(tmp_path):
    fake = FakeLauncher(["NO_RESULT", "NO_RESULT", {"items": [{"slot": "q1", "question": "Q"}]}])
    rec = RQ.run_job(tmp_path, job(), PIN, launcher=fake)
    assert rec["ok"] and len(rec["runs"]) == 3 and rec["output"]["items"][0]["question"] == "Q"
    led = RQ.ledger(tmp_path)
    assert led["by_sub"]["p1"] == pytest.approx(0.3 + 0.3 + 0.05)
    assert {v["source"] for v in led["runs"].values()} == {"cap_assumed", "result"}


def test_run_job_counts_an_agent_limit_without_rerun(tmp_path):
    rec = RQ.run_job(tmp_path, job(), PIN, launcher=FakeLauncher(["LIMIT", "NO_RESULT"]))
    assert not rec["ok"] and len(rec["runs"]) == 1 and rec["runs"][0]["limit"]


def test_a_probe_is_never_rerun(tmp_path):
    rec = RQ.run_job(tmp_path, job(kind="probe", sub="probe"), PIN, launcher=FakeLauncher(["NO_RESULT", "NO_RESULT"]))
    assert not rec["ok"] and len(rec["runs"]) == 1


def test_probe_checks_tools_structured_output_and_model_resolution():
    jb = {"slots": [{"slot": "q1"}, {"slot": "q2"}]}
    out = {"items": [{"slot": "q1", "question": "甲"}, {"slot": "q2", "question": "乙"}]}
    call = {"type": "tool_use", "id": "t1", "name": "StructuredOutput", "input": out}
    prompts = {"system": "你負責寫問題。", "user": "讀者：一般信徒。"}
    keys = ("c1_init", "c2_structured_output", "c3_model", "c4_no_memory", "c5_result")
    ok = RQ.probe_checks(events(output=out, calls=[call]), prompts, jb, "opus", "none", True)
    assert all(ok[k] == "pass" for k in keys) and ok["detail"]["resolved"] == "claude-opus-5-5"
    gone = RQ.probe_checks(events(tools=(), output=out, calls=[call]), prompts, jb, "opus", "none", True)
    assert gone["c2_structured_output"] == "fail"
    alias = RQ.probe_checks(events(model="claude-sonnet-x", output=out, calls=[call]), prompts, jb, "sonnet", "none",
                            True)
    assert alias["c3_model"] == "pass" and alias["detail"]["resolved"] == "claude-sonnet-x"
    two = events(output=out, calls=[call])
    two[-1]["modelUsage"] = {"claude-opus-5-5": {}, "claude-opus-4-8": {}}
    assert RQ.probe_checks(two, prompts, jb, "opus", "none", True)["c3_model"] == "fail"
    no_mem = RQ.probe_checks(events(output=out, calls=[call]), prompts, jb, "opus", "none", False)
    assert no_mem["c4_no_memory"] == "fail"


def test_hard_cap_and_probe_allowance(tmp_path, monkeypatch):
    monkeypatch.setattr(RQ, "USD_CAP", 0.5)
    RQ.reserve(tmp_path, "p1", "p1-j00_1", 0.3)
    with pytest.raises(Q.BudgetRefused, match="硬上限"):
        RQ.check_cap(tmp_path, 0.3)
    assert RQ.run_job(tmp_path, job(), PIN, launcher=FakeLauncher([]))["refused"]
    monkeypatch.setattr(RQ, "USD_CAP", 10.0)
    RQ.reserve(tmp_path, "probe", "probe_opus_1", 0.3)
    RQ.reserve(tmp_path, "probe", "probe_sonnet_1", 0.2)
    with pytest.raises(Q.BudgetRefused, match="probe"):
        RQ.check_cap(tmp_path, 0.05, probe=True)


def synthetic_ctx(tmp_path):
    slot = dict(slot="q1", item_id="p1-x01", kind="pos", qtype="S1a", intent="offset", kingdom="J", start="J04",
                other=None, k=-2, n=None, gold="J02", cell="S1a:J04--2")
    jb = {"job_id": "p1-j00", "set": "p1", "writer": "opus", "persona": "casual", "slots": [slot]}
    return RQ.Ctx(tmp_path, {"jobs": [jb], "order": ["p1-j00"]}, S.Chains(SYN_ROWS), P.load_prompts(), PIN)


def test_a_job_stopped_before_launch_writes_no_draft_and_gen_reruns_it(tmp_path, monkeypatch):
    ctx = synthetic_ctx(tmp_path)

    def refuse(*a, **k):
        raise Q.QError("agent cwd /srv is not empty")
    monkeypatch.setattr(CL, "launch", refuse)
    out = RQ.cmd_gen(ctx, ("p1",))
    assert out["started"] == 1 and out["stopped"] == 1 and out["ok"] == 0 and out["failed"] == 0
    assert "not empty" in out["stopped_why"]["p1-j00"]
    assert not RQ.draft_path(tmp_path, "p1", "p1-j00").exists() and RQ.ledger(tmp_path)["total_usd"] == 0
    monkeypatch.setattr(CL, "launch", FakeLauncher([{"items": [{"slot": "q1", "question": "約沙法的事蹟"}]}]))
    again = RQ.cmd_gen(ctx, ("p1",))
    assert again["started"] == 1 and again["ok"] == 1 and RQ.draft_path(tmp_path, "p1", "p1-j00").is_file()


def test_a_budget_refusal_writes_no_draft(tmp_path, monkeypatch):
    ctx = synthetic_ctx(tmp_path)
    monkeypatch.setattr(RQ, "USD_CAP", 0.1)
    monkeypatch.setattr(CL, "launch", FakeLauncher([]))
    out = RQ.cmd_gen(ctx, ("p1",))
    assert out["stopped"] == 1 and "硬上限" in out["stopped_why"]["p1-j00"]
    assert not RQ.draft_path(tmp_path, "p1", "p1-j00").exists()


def test_writes_outside_the_root_are_refused(tmp_path):
    with pytest.raises(Q.QError, match="outside"):
        Q.write_json(tmp_path / ".." / "x.json", {}, tmp_path)


# ---------------------------------------------------------------- mechanical checks

def test_name_finder_does_not_read_kings_inside_other_words():
    rows = SYN_ROWS + [ref_row("I06", "I", "沙龍", "I05", "usurp", 0.1), ref_row("I07", "I", "亞哈", "I06", "son", 22)]
    f = M.NameFinder(S.Chains(rows))
    assert f.names("押沙龍和亞哈隨魯") == [] and f.names("亞哈和沙龍") == ["亞哈", "沙龍"]


def test_item_checks_answer_simplified_and_flags():
    ch = S.Chains(SYN_ROWS)
    f = M.NameFinder(ch)
    s1a = dict(kind="pos", qtype="S1a", start="I02", other=None, gold="I04", kingdom="I", k=2)
    assert M.item_checks(ch, f, s1a, "拿答之後第二位王是不是以拉？")[0][0].rule == "v_answer"
    assert M.item_checks(ch, f, s1a, "拿答后面第二个王是谁")[0][0].rule == "v_simplified"
    assert M.item_checks(ch, f, s1a, "那位王後面第二位是誰？") == ([], ["f_start_unnamed"])
    assert M.item_checks(ch, f, s1a, "拿答、巴沙之後再下一位是誰？")[1] == ["f_between"]
    s1b = dict(kind="pos", qtype="S1b", start="J01", other="J04", gold=3, kingdom="J")
    assert M.item_checks(ch, f, s1b, "羅波安到約沙法換了幾次王？") == ([], [])
    assert M.item_checks(ch, f, s1b, "羅波安到後來換了幾次王？")[1] == ["f_start_unnamed"]


FATHER_ROWS = SYN_ROWS + [ref_row("J06", "J", "亞她利雅", "J05", "queen_usurp", 6),
                          ref_row("J07", "J", "約阿施", "J06", "son", 40, father="約蘭")]


@pytest.mark.parametrize("question", ("猶大王約阿施（約蘭的兒子）往前數第二位王是誰？", "約蘭的兒子約阿施之前第二位王是誰？",
                                      "約蘭王之子約阿施之前第二位王是誰？", "約阿施，父親是約蘭，往前數第二位王是誰？",
                                      "約阿施(父親約蘭)之前第二位王是誰？", "約阿施是約蘭的兒子，他之前第二位王是誰？"))
def test_a_father_marker_naming_the_answer_is_no_leak(question):
    """The start king's father written to tell homonyms apart may be the answer (qset scouting §2.6):
    valid, flagged f_father_is_answer, and it stays in the denominator."""
    ch = S.Chains(FATHER_ROWS)
    s1a = dict(kind="pos", qtype="S1a", start="J07", other=None, gold="J05", kingdom="J", k=-2)
    assert M.item_checks(ch, M.NameFinder(ch), s1a, question) == ([], ["f_father_is_answer"])


def test_the_answer_named_outside_a_father_marker_or_as_a_non_father_is_still_a_leak():
    ch = S.Chains(FATHER_ROWS)
    f = M.NameFinder(ch)
    s1a = dict(kind="pos", qtype="S1a", start="J07", other=None, gold="J05", kingdom="J", k=-2)
    for q in ("約蘭的兒子約阿施之前第二位王是不是約蘭？", "約蘭的孫子約阿施之前第二位王是誰？", "約阿施和約蘭之間隔了誰？"):
        assert [v.rule for v in M.item_checks(ch, f, s1a, q)[0]] == ["v_answer"], q
    s3 = dict(kind="pos", qtype="S1a", start="J07", other=None, gold="J04", kingdom="J", k=-3)
    assert [v.rule for v in M.item_checks(ch, f, s3, "約沙法的兒子約阿施之前第三位王是誰？")[0]] == ["v_answer"]
    # the father between the start and the answer, written as the marker, is no f_between
    assert M.item_checks(ch, f, s3, "約蘭的兒子約阿施之前第三位王是誰？") == ([], [])
    assert M.item_checks(ch, f, s3, "約阿施、約蘭之前第三位王是誰？") == ([], ["f_between"])


@needs_store
def test_father_markers_on_the_reference_cells_of_the_review():
    ch = S.Chains(S.load_ref().rows)
    f = M.NameFinder(ch)
    j08 = dict(kind="pos", qtype="S1a", start="J08", other=None, gold="J06", kingdom="J", k=-2)
    assert M.item_checks(ch, f, j08, "猶大王約阿施（亞哈謝的兒子）往前數第二位王是誰？") == ([], ["f_father_is_answer"])
    j17 = dict(kind="pos", qtype="S4", start="J17", other=None, gold="J16", kingdom="J")
    assert M.item_checks(ch, f, j17, "約哈斯（約西亞的兒子）出生時誰在位？") == ([], ["f_father_is_answer"])


def test_slot_violations_and_dedupe():
    jb = {"slots": [{"slot": "q1"}, {"slot": "q2"}]}
    got, bad = M.slot_violations(jb, {"items": [{"slot": "q1", "question": " A "}, {"slot": "q9", "question": "B"}]})
    assert got == {"q1": "A"} and {v.rule for v in bad} == {"v_slot"} and len(bad) == 2
    items = M.dedupe([{"question": "甲 乙", "valid": True}, {"question": "甲乙", "valid": True}])
    assert items[0]["valid"] and not items[1]["valid"] and items[1]["violations"][0]["rule"] == "v_duplicate"


def test_label_consistency_rules():
    ch = S.Chains(SYN_ROWS)
    f = M.NameFinder(ch)
    s1a = dict(kind="pos", qtype="S1a", intent="offset", start="J04", other=None, kingdom="J", k=-2, n=None)
    lab = {"intent": "offset", "king": "約沙法", "kingdom": "猶大", "k": -2, "n": None, "second_king": None}
    assert M.label_consistent(ch, f, s1a, lab) == (True, [])
    assert M.label_consistent(ch, f, s1a, dict(lab, k=2))[0] is False
    assert M.label_consistent(ch, f, s1a, dict(lab, kingdom="不明"))[0] is True
    s1b = dict(kind="pos", qtype="S1b", intent="handovers", start="J01", other="J04", kingdom="J", k=None, n=None)
    lb = {"intent": "handovers", "king": "約沙法", "kingdom": "猶大", "k": None, "n": None, "second_king": "羅波安"}
    assert M.label_consistent(ch, f, s1b, lb)[0] is True
    near = dict(kind="near", qtype="N5", intent="kin", start="J04")
    assert M.label_consistent(ch, f, near, dict(lab, intent="kin"))[0] is True
    assert M.label_consistent(ch, f, near, dict(lab, intent="handovers"))[0] is False
    assert M.label_consistent(ch, f, near, None) == (None, ["no label"])


@needs_store
def test_assemble_refills_invalid_slots_once_and_marks_duplicates(tmp_path):
    ref = S.load_ref()
    spec = S.build_spec(ref)
    Q.write_json(tmp_path / S.SPEC_FILE, spec, tmp_path)
    ctx = RQ.Ctx(tmp_path, spec, S.Chains(ref.rows), P.load_prompts(), PIN)
    jb = next(j for j in spec["jobs"] if j["set"] == "p1" and len(j["slots"]) >= 2)
    first = {"items": [{"slot": s["slot"], "question": f"{ctx.ch.name(s['start'])}的題目{n}"}
                       for n, s in enumerate(jb["slots"])]}
    bad = jb["slots"][0]
    if bad["kind"] == "pos" and bad["qtype"] != "S1b":
        first["items"][0]["question"] = f"{ctx.ch.name(bad['start'])}與{ctx.ch.name(bad['gold'])}"
    else:
        first["items"][0]["question"] = "这是什么"
    RQ._write_draft(ctx, jb, {"ok": True, "output": first, "runs": []})
    items = [i for i in RQ.assemble(ctx, "p1") if i["job"] == jb["job_id"]]
    assert not items[0]["valid"] and all(i["valid"] for i in items[1:])
    rjob = RQ.refill_job(jb, {i["slot"]: i for i in items})
    assert rjob["job_id"] == jb["job_id"] + "-r" and [s["slot"] for s in rjob["slots"]] == [bad["slot"]]
    RQ._write_draft(ctx, rjob, {"ok": True, "output": {"items": [{"slot": bad["slot"], "question":
                                                                  f"{ctx.ch.name(bad['start'])}的新題目"}]}, "runs": []})
    items = [i for i in RQ.assemble(ctx, "p1") if i["job"] == jb["job_id"]]
    assert items[0]["valid"] and items[0]["refilled"] and items[0]["first_violations"]
    others = [i for i in RQ.assemble(ctx, "p1") if i["job"] != jb["job_id"]]
    assert all(i["violations"][0]["rule"] == "v_missing" for i in others)
    batches = RQ.label_batches(RQ.assemble(ctx, "p1"), "p1")
    assert sum(len(b) for b in batches) == len(jb["slots"]) and all(len(b) <= Q.LABEL_BATCH for b in batches)


class FlowLauncher(FakeLauncher):
    """Writer jobs: one templated question per slot (the king line of the prompt, no cue word);
    labeller jobs: every question read as 'other'."""

    def __init__(self):
        super().__init__([])

    def __call__(self, root, run_id, system, user, schema, cap, model, effort, pin, cwd, extra_record=None):
        props = schema["properties"]["items"]["items"]["properties"]
        if "slot" in props:
            kings = re.findall(r"^(?:king|earlier king): (\S+?)（", user, re.M)
            out = {"items": [{"slot": s, "question": f"{k}的事蹟（{run_id} {s}）"}
                             for s, k in zip(props["slot"]["enum"], kings)]}
        else:
            out = {"items": [{"id": i, "intent": "other", "king": None, "kingdom": "不明", "k": None, "n": None,
                              "second_king": None} for i in props["id"]["enum"]]}
        return self.write(root, run_id, system, user, cap, model, out)   # no shared state: jobs run in threads


@needs_store
def test_gen_mech_label_score_flow_with_a_fake_launcher(tmp_path, monkeypatch):
    ref = S.load_ref()
    spec = S.build_spec(ref)
    Q.write_json(tmp_path / S.SPEC_FILE, spec, tmp_path)
    pin = CL.CliPin("2.1.302", True, "none", {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5"})
    CL.write_pin(tmp_path, pin)
    monkeypatch.setattr(CL, "launch", FlowLauncher())
    ctx = RQ.context(tmp_path)
    assert RQ.cmd_gen(ctx, ("p1",)) == {"started": 28, "ok": 28, "failed": 0, "stopped": 0, "stopped_why": {}}
    assert RQ.cmd_gen(ctx, ("p1",))["started"] == 0                      # drafts are not redone
    got = RQ.write_items(ctx, "p1")
    assert got["slots"] == 75 and got["valid"] == 75
    assert RQ.cmd_refill(ctx, ("p1",))["started"] == 0
    assert RQ.cmd_label(ctx, ("p1",)) == {"started": 8, "ok": 8, "failed": 0, "stopped": 0}
    doc = Q.read_json(tmp_path / "p1" / "items.json")
    pos = [i for i in doc["items"] if i["kind"] == "pos"]
    assert all(i["label_consistent"] is False for i in pos) and len(pos) == 60
    out, rows = SC.score_doc(SC.load_rules(Q.LAYER_PROD), doc["items"], S.Chains(ref.rows), "p1")
    agg = out["aggregate"]["positives"]
    assert agg["n"] == 60 and agg["R_trig"]["k"] == 0 and agg["label_inconsistent"]["n"] == 60
    assert agg["fail"] == {"cue_miss": 60}
    led = RQ.ledger(tmp_path)
    assert led["by_sub"]["p1"] == pytest.approx(0.05 * (28 + 8)) and led["by_sub"]["p2"] == 0
    assert RQ.cmd_status(ctx)["p2"]["drafted"] == 0

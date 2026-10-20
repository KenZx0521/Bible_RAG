"""GEN confirmation set: the blind P1/P2 question sets and the F1a writer (spec_qg, prompt_qg, mech_qg, run_qg, f1a_g;
prereg §3.8 F1a, §5.4, §5.6 G1, §8.1-3..5). The runner's launches are in test_gen_confirm_qset_run.py.

Nothing here launches claude or calls Ollama; every root is a tmp dir; the pytest run of f1a_g and git are fakes or a
tmp repository. The synthetic layer, names, pool and questions are made up (the window scan at the end checks both
qset test files and the new modules against the text layer and the real questions). The store tests (skipped when it
is not mounted) build the real specs at run time and assert counts, sets and booleans only, so a failure never prints
a P2 slot or a name. Covered: spec determinism (the P2 sample is Random(20261022).sample of the real sorted sids),
the 14 near-miss families over 20 items, no P1 near miss on a pool pair, P2 near misses never a P1 one (read from
P1's spec, whatever the candidates), writer halves; every rendered prompt passes banned_g's prompt scope and holds no
cue word (also without banned_g's cue list), the counting-way rule; each validity rule with a positive and a
negative case (a repeated label, inner white space, a missing transcript), the refill once only, by the same writer
and persona; the scoring math (R_* and n_v, near misses, P2's totals), the once-only write of a P2 record; the
g1.json contract against power_g.g1; f1a_g's records and refusals; the sys.modules rule (§3.9).
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import banned_g as B  # noqa: E402
import claude_g as CL  # noqa: E402
import f1_g as F1  # noqa: E402
import f1a_g as FA  # noqa: E402
import g_common as GC  # noqa: E402
import gencard  # noqa: E402
import hog_common as HC  # noqa: E402
import mech_qg as MQ  # noqa: E402
import prompt_qg as Q  # noqa: E402
import prompts_g as P  # noqa: E402
import run_qg as R  # noqa: E402
import spec_qg as S  # noqa: E402

STORE_OK = GC.POOL.is_file() and GC.GEN_NAMES.is_file() and GC.GEN_LAYER.is_file()
needs_store = pytest.mark.skipif(not STORE_OK, reason=f"store not mounted ({GC.OUT_ROOT})")
TEXT_UNITS = GC.STORE / "layers/text/text@247eafe44b02/verse_units.jsonl"
WINDOW = 8
FAKE_VERSION = "9.9.9"
NEW_FILES = ("spec_qg.py", "prompt_qg.py", "prompts_qg.md", "mech_qg.py", "run_qg.py", "f1a_g.py")

# ---------------------------------------------------------------- a synthetic layer (made up)
# (id, name, begetting age, remaining years, stated lifespan); G05.06 is the engine's taken row
CH5 = (("G05.00", "阿爾文", 100, 800, 900), ("G05.01", "貝克", 90, 800, 890), ("G05.02", "卡森", 80, 700, 780),
       ("G05.03", "戴爾", 70, 750, 820), ("G05.04", "艾利", 60, 700, 760), ("G05.05", "法蘭", 150, 600, 750),
       ("G05.06", "高登", 60, 300, 360), ("G05.07", "哈維", 180, 700, 880), ("G05.08", "伊萬", 170, 500, 670),
       ("G05.09", "傑伊", 400, None, 900))
CH11 = (("G11.00", "凱", 90, 900, None), ("G11.01", "羅蘭", 30, 300, None), ("G11.02", "馬可斯", 25, 200, None),
        ("G11.03", "諾蘭", 35, 100, None), ("G11.04", "奧斯卡", 20, 300, None), ("G11.05", "彼特", 30, 50, None),
        ("G11.06", "昆西", 30, 200, None), ("G11.07", "雷夫", 25, 100, None), ("G11.08", "史坦", 70, None, 205))
COMMON = {"凱": ("凱旋", "凱歌"), "史坦": ("史坦著", "史坦住", "歷史")}
CAIN = ("凱恩", "艾迪", "米契", "柔伊", "諾德")
ABRAM = ("艾瑞克", "艾瑞克森", "哈利", "蘿拉")
BOOKS = ("某乙福音", "某乙", "某丙志上", "某丙志")
LISTS = S.Lists(cain_pairs=(("凱恩", "高登"), ("高登", "艾迪"), ("米契", "伊萬"), ("伊萬", "柔伊")),
                after12_pairs=(("艾瑞克", "路克"), ("路克", "馬特"), ("馬特", "蘿拉")),
                books={"luke": "某乙福音", "chron": "某丙志上"})
T_F1, T_F5 = "依創世記，{x}幾歲時，{y}出生？", "依創世記，{x}去世那年，{y}幾歲？"


def gen_doc() -> dict:
    nodes, edges, derived = [], [], {}
    for ch, rows in ((5, CH5), (11, CH11)):
        for order, (gid, name, b, r, t) in enumerate(rows):
            f = {"beget": [b, f"syn.{ch}.{3 * order}"]}
            if r is not None:
                f["remain"] = [r, f"syn.{ch}.{3 * order + 1}"]
            if t is not None:
                f["total"] = [t, f"syn.{ch}.{3 * order + 2}"]
            else:
                derived[gid] = b + r
            nxt = rows[order + 1][1] if order + 1 < len(rows) else None
            nodes.append({"id": gid, "name": name, "chapter": ch, "order": order, "sons": [nxt] if nxt else [],
                          "fields": f, "flood_offset": [2, "syn.11.0"] if gid == "G11.00" else None})
        edges += [[a[0], b[0], "son", f"syn.{ch}.{3 * i}"] for i, (a, b) in enumerate(zip(rows, rows[1:]))]
    nodes[9]["sons"] = ["凱", "路克", "馬特"]
    nodes[-1]["sons"] = ["艾瑞克", "雷夫", "哈利"]           # 雷夫 also names a chain person: the namesake son
    return {"schema": "arith.gen_layer.v1", "text_digest": "syn", "nodes": nodes, "edges": edges,
            "conflict_edges": [["G05.09", "G11.00", "son", "syn.5.30"]], "flood": {"noah_age": [450, "syn.7.6"]},
            "derived": {"total": derived}, "checks": {}}


def names_doc(gen: dict) -> dict:
    chain = [{"id": n["id"], "name": n["name"], "chapter": n["chapter"]}
             for n in sorted(gen["nodes"], key=lambda n: (n["chapter"], n["order"]))]
    return {"schema": "gen_confirm.gen_names.v1", "text_digest": "syn", "gen_layer_sha256": "syn", "chain": chain,
            "cain_line": sorted(CAIN), "abram_family": sorted(ABRAM), "extra_persons": sorted(CAIN + ABRAM),
            "other_books": sorted(BOOKS), "lexicon_blockers": ["卡森城"], "sources": {}}


def pool_row(L, sid: str, qt: str, a: str, b: str) -> dict:
    ids = L.chains[L.chapter[a]]
    i, j = L.index[a], L.index[b]
    gold = L.age_at_birth(a, b) if qt == "F1" else L.lifespan[a] - L.age_at_birth(a, b)
    return dict(sid=sid, qtype=qt, chapter=L.chapter[a], stratum=f"{qt}c{L.chapter[a]}", d=j - i, x=a, y=b,
                pair=f"{a}>{b}", persons=list(ids[i:j + 1]), edges=[f"{ids[k]}>{ids[k + 1]}" for k in range(i, j)],
                gold=gold, marker_required=False, homonym=False)


@pytest.fixture(scope="module")
def syn():
    gen = gen_doc()
    nd = names_doc(gen)
    L = gencard.parse(gen, nd, common_words=COMMON)
    rows = [pool_row(L, "", "F1", a, b) for ch in (5, 11) for i, a in enumerate(L.chains[ch])
            for b in L.chains[ch][i + 2:i + 5] if S._alive_at_birth(L, a, b)]
    rows += [pool_row(L, "", "F5", a, b) for ch in (5, 11) for i, a in enumerate(L.chains[ch])
             for b in L.chains[ch][i + 2:] if S._died_after(L, a, b)]
    want = {"F1c5": 6, "F1c11": 6, "F5c5": 1, "F5c11": 1}
    dev, pool = [], []
    for r in rows:
        (dev if want.get(r["stratum"], 0) > sum(d["stratum"] == r["stratum"] for d in dev) else pool).append(r)
    dev = [dict(r, sid=f"D{k:02d}") for k, r in enumerate(dev)]
    pool = [dict(r, sid=f"S{k:02d}") for k, r in enumerate(pool)]
    return SimpleNamespace(gen=gen, nd=nd, L=L, names=P.Names.from_doc(nd), pool=pool, dev=dev)


@pytest.fixture(scope="module")
def specs(syn):
    p1 = S.build_spec("p1", syn.pool, syn.L, LISTS, dev=syn.dev)
    return {"p1": p1, "p2": S.build_spec("p2", syn.pool, syn.L, LISTS, p1_near=S.near_of(p1))}


def nm(syn, i: str) -> str:
    return syn.L.name[i]


def question_for(syn, slot: dict) -> str:
    t = T_F1 if slot.get("qtype") == "F1" else T_F5
    return t.format(x=nm(syn, slot["x"]), y=nm(syn, slot["y"]))


# ---------------------------------------------------------------- spec
def test_spec_is_deterministic_and_dealt_as_specified(syn, specs):
    again = S.build_spec("p1", syn.pool, syn.L, LISTS, dev=syn.dev)
    assert S.spec_sha(again) == S.spec_sha(specs["p1"])
    for s, spec in specs.items():
        c = spec["counts"]
        assert (c["jobs"], c["slots"], c["positives"], c["near"]) == (24, 70, 50, 20)
        assert c["writers"] == {"opus": 12, "sonnet": 12} and sum(c["personas"].values()) == 24
        assert set(c["personas"]) == set(S.PERSONAS) and c["job_sizes"] == {"2": 2, "3": 22}
        for j in spec["jobs"]:
            sids = [x["sid"] for x in j["slots"] if x["kind"] == "pos"]
            assert len(sids) == len(set(sids)) and len(j["slots"]) <= S.JOB_SIZE
            assert [x["slot"] for x in j["slots"]] == [f"q{k}" for k in range(1, len(j["slots"]) + 1)]
        ids = [x["item_id"] for j in spec["jobs"] for x in j["slots"]]
        assert len(ids) == len(set(ids)) == 70 and spec["order"] == [j["job_id"] for j in spec["jobs"]]
    p1 = [x for j in specs["p1"]["jobs"] for x in j["slots"] if x["kind"] == "pos"]
    assert specs["p1"]["counts"]["by_stratum"] == S.shares(syn.pool, 50)
    assert {x["sid"] for x in p1} == {d["sid"] for d in syn.dev}


def test_p2_positives_are_the_seeded_sample_without_repeats(syn, specs):
    p2 = [x["sid"] for j in specs["p2"]["jobs"] for x in j["slots"] if x["kind"] == "pos"]
    want = random.Random(20261022).sample(sorted(r["sid"] for r in syn.pool), 50)
    assert GC.P2_SEED == 20261022 and len(p2) == len(set(p2)) == 50 and set(p2) == set(want)


def test_near_misses_cover_the_14_families_and_p2_never_repeats_p1(specs):
    assert len(S.NEAR_FAMILIES) == 14 and sum(len(s) for _f, s in S.NEAR_FAMILIES) == 20
    want = {f: len(srcs) for f, srcs in S.NEAR_FAMILIES}
    near = {s: [x for j in sp["jobs"] for x in j["slots"] if x["kind"] == "near"] for s, sp in specs.items()}
    for s in S.SETS:
        assert specs[s]["counts"]["by_family"] == want and len(near[s]) == 20
    keys = {s: [S.near_key(x) for x in v] for s, v in near.items()}
    assert all(len(set(k)) == 20 for k in keys.values()) and not set(keys["p1"]) & set(keys["p2"])
    words = {x["word"] for x in near["p1"] if x["source"].startswith("word")}
    assert words == {"凱旋", "史坦著"}                        # each guarded name's first common word


def test_p1_near_misses_name_no_pool_pair(syn, specs):
    pool_pairs = {(r["x"], r["y"]) for r in syn.pool}
    assert any((c["x_id"], c["y_id"]) in pool_pairs for v in S.candidates(syn.L, LISTS).values() for c in v)
    assert not [x for x in S.near_of(specs["p1"]) if (x["x_id"], x["y_id"]) in pool_pairs]


def test_p2_near_misses_avoid_p1s_whatever_the_candidates(syn, specs, monkeypatch):
    p1, real = S.near_of(specs["p1"]), S.candidates
    shifted = lambda L, lists: {k: v[-1:] + v for k, v in real(L, lists).items()}  # noqa: E731  (a front insertion)
    monkeypatch.setattr(S, "candidates", shifted)
    p2 = S.near_of(S.build_spec("p2", syn.pool, syn.L, LISTS, p1_near=p1))
    assert len(p2) == 20 and not {S.near_key(x) for x in p2} & {S.near_key(x) for x in p1}
    with pytest.raises(S.SpecError, match="after P1"):
        S.build_spec("p2", syn.pool, syn.L, LISTS)


def test_spec_refuses_too_few_candidates_and_unknown_names(syn, specs):
    with pytest.raises(S.SpecError, match="Cain"):
        S.near_items("p1", syn.L, S.Lists(cain_pairs=(("某甲", "某丁"),) * 4, books=LISTS.books))
    with pytest.raises(S.SpecError, match="book"):
        S.near_items("p1", syn.L, S.Lists(cain_pairs=LISTS.cain_pairs, books={"luke": "某戊書", "chron": "某丙志上"}))
    with pytest.raises(S.SpecError, match="no free candidate"):
        S.near_items("p2", syn.L, S.Lists(cain_pairs=LISTS.cain_pairs[:2], books=LISTS.books),
                     taken=S.near_of(specs["p1"]))
    with pytest.raises(S.SpecError, match="development"):
        S.build_spec("p1", syn.pool, syn.L, LISTS)


def test_spec_file_sha_is_the_spec_sha_and_a_changed_spec_is_refused(tmp_path, specs):
    path = S.write_spec(specs["p2"], tmp_path)
    assert path == tmp_path / "qset/p2/spec.json" and GC.sha256_file(path) == S.spec_sha(specs["p2"])
    S.write_spec(specs["p2"], tmp_path)
    with pytest.raises(S.SpecError, match="another sha256"):
        S.write_spec({**specs["p2"], "seed": 1}, tmp_path)
    assert set(S.summary(specs["p2"])) >= {"sha256", "jobs", "by_stratum", "by_family"}
    text = json.dumps(S.summary(specs["p2"]), ensure_ascii=False)
    assert not re.search(r"\bS\d\d\b", text) and not any(n in text for n in (r[1] for r in CH5 + CH11))


@needs_store
def test_store_specs_sample_the_real_pool_and_keep_the_shape(tmp_path):
    pool = GC.read_json(GC.POOL)["pool"]
    p1 = S.build_from_store("p1")
    p2 = S.build_from_store("p2", p1_spec=p1)
    sids = [x["sid"] for j in p2["jobs"] for x in j["slots"] if x["kind"] == "pos"]
    assert set(sids) == set(random.Random(GC.P2_SEED).sample(sorted(r["sid"] for r in pool), 50)) and len(set(sids)) == 50
    assert p1["counts"]["distinct_positive_slots"] == 14 and p1["counts"]["by_stratum"] == S.shares(pool, 50)
    assert all(sp["counts"]["writers"] == {"opus": 12, "sonnet": 12} for sp in (p1, p2))
    words = {x["word"] for x in (x for j in p1["jobs"] for x in j["slots"]) if x.get("word")}
    assert words == {"閃電", "他拉著"} and S.spec_sha(S.build_from_store("p2", p1_spec=p1)) == S.spec_sha(p2)
    pairs, (n1, n2) = {(r["x"], r["y"]) for r in pool}, (S.near_of(p1), S.near_of(p2))
    assert sum((x["x_id"], x["y_id"]) in pairs for x in n1) == 0
    k1, k2 = [S.near_key(x) for x in n1], [S.near_key(x) for x in n2]
    assert len(set(k1)) == len(set(k2)) == 20 and not set(k1) & set(k2)
    assert p2["inputs"]["p1/spec.json"] == S.spec_sha(p1)
    with pytest.raises(S.SpecError, match="missing"):
        S.build_from_store("p2", out_root=tmp_path)                       # P2 reads P1's stored spec


# ---------------------------------------------------------------- prompts
def _parts(r: Q.QRendered) -> list[str]:
    return [r.system, r.user, json.dumps(r.schema, ensure_ascii=False), *r.values.values()]


def test_every_rendered_prompt_passes_the_prompt_scope_and_holds_no_cue_word(syn, specs):
    cues = gencard.CUE_LITERALS
    for spec in specs.values():
        for job in spec["jobs"]:
            r = Q.render_job(job, syn.names)
            for part in _parts(r):
                assert B.require(part, job["job_id"], "prompt") == part
                assert not [c for c in cues if c in part]
            assert r.schema["properties"]["items"]["minItems"] == len(job["slots"])
            assert r.schema["properties"]["items"]["items"]["properties"]["slot"]["enum"] == \
                [s["slot"] for s in job["slots"]]


def test_positive_blocks_are_the_ho_writers_definition_and_naming(syn, specs):
    job = specs["p2"]["jobs"][0]
    pos = next(s for s in job["slots"] if s["kind"] == "pos")
    spec = P.slot_spec(pos, syn.names, "Q01")
    block = Q.slot_block(pos, syn.names)
    assert f"quantity: {spec.definition}" in block and f"naming: {spec.naming}" in block
    assert spec.definition == P.DEFINITIONS[spec.qtype].format(x=spec.x, y=spec.y) and P.NO_OTHER_PERSON[:12] in block
    row = next(r for r in syn.pool if r["chapter"] == 11 and r["y"] != "G11.08")
    marked = Q.slot_block({**row, "kind": "pos", "slot": "q1", "marker_required": True}, syn.names)
    son = syn.L.name[syn.L.son(row["y"])]
    assert f"{son}的父親{nm(syn, row['y'])}" in marked and "identifying phrase" in marked
    assert [ln.split(":")[0] for ln in block.splitlines()[1:]] == ["quantity", "people", "scope", "naming"]
    assert str(pos["gold"]) not in block.replace("Genesis 11", "").replace("Genesis 5", "")


def test_a_banned_term_or_cue_word_refuses_the_render(syn, specs):
    job = specs["p1"]["jobs"][0]
    near = next(j for j in specs["p1"]["jobs"] if any(s["kind"] == "near" for s in j["slots"]))
    k = next(i for i, s in enumerate(near["slots"]) if s["kind"] == "near")
    for bad in ("幾歲人", "gemma", "prereg"):
        slots = [dict(s) for s in near["slots"]]
        slots[k]["x"] = bad
        with pytest.raises(B.BlindingError):
            Q.render_job({**near, "slots": slots}, syn.names)
    with pytest.raises(B.BlindingError):
        Q.checked("one cue: 出生", "test")
    with B.override_cue_literals(()), pytest.raises(B.BlindingError, match="cue words"):
        Q.checked("one cue: 出生", "test")                              # gencard's own list, not banned_g's
    assert Q.render_job(job, syn.names).prompt_sha256 == GC.sha256_file(Q.PROMPT_FILE)


def test_the_writer_may_say_in_words_how_the_years_are_counted():
    """HO's rule 9 (gen_g.md), so P1/P2 questions carry the clauses the confirmation questions may carry."""
    system = Q.load().sections["system"]
    assert "differ by one year" in system and "which way is meant" in system and "without any numeral" in system


@needs_store
def test_store_prompts_all_pass_without_printing():
    names, cues = P.load_names(), gencard.CUE_LITERALS
    p1 = S.build_from_store("p1")
    for spec in (p1, S.build_from_store("p2", p1_spec=p1)):
        for job in spec["jobs"]:
            r = Q.render_job(job, names)
            assert all(not [c for c in cues if c in part] and not B.prompt_hits(part) for part in _parts(r))


# ---------------------------------------------------------------- validity (mech_qg)
def _pos_slot(syn, k: int = 0) -> dict:
    return {**syn.pool[k], "kind": "pos", "slot": "q1", "item_id": "p9-j00-q1"}


def test_slot_rule(syn):
    labels = ["q1", "q2"]
    ok, bad = MQ.slot_violations(labels, {"items": [{"slot": "q1", "question": "甲"}, {"slot": "q2", "question": "乙"}]})
    assert ok == {"q1": "甲", "q2": "乙"} and bad == []
    for out in ({"items": [{"slot": "q1", "question": "甲"}]}, {"items": [{"slot": "q1", "question": " "},
                {"slot": "q2", "question": "乙"}]}, {"items": [{"slot": "q1", "question": "甲" * 201},
                {"slot": "q2", "question": "乙"}]}, {"items": [{"slot": "q3", "question": "甲"}]}, None, {"x": 1}):
        got, bad = MQ.slot_violations(labels, out)
        assert bad and all(v.rule == "v_slot" for v in bad) and len(got) < 2
    got, bad = MQ.slot_violations(["q1"], {"items": [{"slot": "q1", "question": "甲"}, {"slot": "q1", "question": "乙"}]})
    assert got == {} and [v.detail.split(":")[0] for v in bad] == ["q1"]      # a label given twice has no question


def test_question_rules_apply_to_positives_only(syn):
    pos = _pos_slot(syn)
    near = {**pos, "kind": "near", "family": "yes_no", "source": "yes_no"}
    x, y = nm(syn, pos["x"]), nm(syn, pos["y"])
    assert MQ.question_violations(pos, T_F1.format(x=x, y=y) if pos["qtype"] == "F1" else T_F5.format(x=x, y=y),
                                  syn.names) == []
    cases = {"v_number": f"依創世記，{x}在三百年後幾歲時，{y}出生？", "v_source": f"{x}幾歲時，{y}出生？",
             "yes_no": f"依創世記，{y}出生時{x}還在世嗎？", "extra_name": f"依創世記，{x}幾歲時，{y}和凱恩出生？",
             "multi_question": f"依創世記，{x}幾歲？{y}出生？", "v_kin": f"依創世記，{x}幾歲時，曾孫{y}出生？",
             "v_simplified": f"依創世記，{x}幾歲时，{y}出生这？"}
    for rule, q in cases.items():
        assert rule in {v.rule for v in MQ.question_violations(pos, q, syn.names)}, rule
        assert [v.rule for v in MQ.question_violations(near, q, syn.names)] == (["v_simplified"]
                                                                               if rule == "v_simplified" else [])


def test_blind_check_fails_closed(tmp_path):
    """qset.md §3: the output run's transcript is re-read; a missing one, or an ok draft naming none, voids it."""
    blind = R.blind_of(SimpleNamespace(root=tmp_path))
    assert blind({"ok": False, "output_run": None}) == []
    assert [v.rule for v in blind({"ok": True, "output_run": "p9-j00_1"})] == ["t_result"]
    assert [v.rule for v in blind({"ok": True, "output": {"items": []}})] == ["t_result"]


def test_blinding_voids_the_whole_job(syn):
    job = {"job_id": "p9-j00", "set": "p9", "writer": "opus", "persona": "casual", "slots": [_pos_slot(syn)]}
    q = question_for(syn, syn.pool[0])
    draft = {"ok": True, "output": {"items": [{"slot": "q1", "question": q}]}, "output_run": "r"}
    assert MQ.job_items(job, draft, syn.names, lambda d: [])[0]["valid"]
    it = MQ.job_items(job, draft, syn.names, lambda d: ["t_memory"])[0]
    assert not it["valid"] and it["violations"][0]["rule"] == "v_blind" and it["question"] is None
    it = MQ.job_items(job, {**draft, "ok": False, "output": None}, syn.names, lambda d: [])[0]
    assert not it["valid"] and it["violations"][0]["rule"] == "v_slot"
    assert MQ.job_items(job, None, syn.names, lambda d: [])[0]["violations"][0]["rule"] == "v_slot"


def _mini(syn) -> tuple[dict, dict]:
    def job(jid, rows, writer, persona):
        return {"job_id": jid, "set": "p9", "writer": writer, "persona": persona,
                "slots": [{**r, "kind": "pos", "slot": f"q{k}", "item_id": f"{jid}-q{k}"} for k, r in enumerate(rows, 1)]}
    spec = {"jobs": [job("p9-j00", syn.pool[:2], "opus", "casual"),
                     job("p9-j01", [{**syn.pool[0], "copy": 1}], "sonnet", "seminary")],   # a P1-style repeat
            "order": ["p9-j00", "p9-j01"]}
    q = [question_for(syn, r) for r in syn.pool[:2]]
    spaced = " " + q[0][:4] + " \u3000 " + q[0][4:].replace("，", ",")     # white space inside, NFKC punctuation
    drafts = {"p9-j00": {"ok": True, "output": {"items": [{"slot": "q1", "question": q[0]},
                                                          {"slot": "q2", "question": q[1] + "这"}]}},
              "p9-j01": {"ok": True, "output": {"items": [{"slot": "q1", "question": spaced}]}}}
    return spec, drafts


def test_duplicates_and_the_refill_round_happen_once(syn):
    spec, drafts = _mini(syn)
    read = drafts.get
    first = MQ.first_round(spec, read, syn.names, lambda d: [])
    assert [i["valid"] for i in first] == [True, False, False]
    assert [v["rule"] for v in first[2]["violations"]] == ["v_duplicate"]
    refills = MQ.refill_jobs(spec, read, syn.names, lambda d: [])
    assert [(r["job_id"], [s["slot"] for s in r["slots"]]) for r in refills] == [("p9-j00-r", ["q2"]), ("p9-j01-r", ["q1"])]
    by_id = {j["job_id"]: j for j in spec["jobs"]}
    assert all((r["writer"], r["persona"]) == (by_id[r["refill_of"]]["writer"], by_id[r["refill_of"]]["persona"])
               for r in refills)                                          # the same writer and persona
    assert [i["valid"] for i in MQ.assemble(spec, read, syn.names, lambda d: [])] == [True, False, False]
    q0, q1 = question_for(syn, syn.pool[0]), question_for(syn, syn.pool[1])
    drafts["p9-j00-r"] = {"ok": True, "output": {"items": [{"slot": "q2", "question": q1},
                                                           {"slot": "q1", "question": q1}]}}   # a stray label too
    drafts["p9-j01-r"] = {"ok": True, "output": {"items": [{"slot": "q1", "question": q0}]}}   # a duplicate again
    assert MQ.refill_jobs(spec, read, syn.names, lambda d: []) == refills      # the round is not asked for again
    out = MQ.assemble(spec, read, syn.names, lambda d: [])
    assert [(i["valid"], i["refilled"]) for i in out] == [(True, False), (True, True), (False, True)]
    assert out[0]["question"] == q0 and out[2]["first_violations"][0]["rule"] == "v_duplicate"
    assert MQ.tally(out)["pos"] == {"slots": 3, "valid": 2, "refilled": 2, "invalid_by_rule": {"v_duplicate": 1}}


# ---------------------------------------------------------------- scoring
def _item(syn, kind: str, question: str, row: dict | None = None, valid: bool = True, family: str | None = None) -> dict:
    row = row or syn.pool[0]
    return {"item_id": f"i{random.random()}", "kind": kind, "stratum": row["stratum"] if kind == "pos" else None,
            "family": family, "source": family, "writer": "opus", "persona": "casual", "valid": valid,
            "refilled": False, "question": question, "x": row["x"], "y": row["y"], "gold": row["gold"],
            "violations": [] if valid else [{"rule": "v_slot", "detail": "x"}]}


def test_scoring_math_on_synthetic_questions(syn):
    f1 = next(r for r in syn.pool if r["qtype"] == "F1" and r["chapter"] == 5)
    other = next(r for r in syn.pool if r["qtype"] == "F1" and r["chapter"] == 5 and r["y"] != f1["y"])
    x, y, y2 = nm(syn, f1["x"]), nm(syn, f1["y"]), nm(syn, other["y"])
    ok_q = T_F1.format(x=x, y=y)
    wrong_q = T_F1.format(x=nm(syn, other["x"]), y=y2)
    rows = [R.score_row(syn.L, it) for it in (
        _item(syn, "pos", ok_q, f1), _item(syn, "pos", wrong_q, f1), _item(syn, "pos", f"依創世記，{x}和{y}是誰？", f1),
        _item(syn, "pos", ok_q, f1, valid=False), _item(syn, "near", ok_q, family="f1_far"),
        _item(syn, "near", f"依創世記，{x}是誰？", family="lifespan"), _item(syn, "near", ok_q, valid=False, family="N2"))]
    agg = R.aggregate(rows)
    assert (agg["n_v"], agg["R_trig"], agg["R_seed"], agg["R_card"], agg["R_wrong"]) == (3, 2, 1, 1, 1)
    assert agg["rates"]["R_card"] == round(1 / 3, 4) and agg["invalid_positives"] == 1
    assert sum(agg["abstain"].values()) == 1 and agg["by_writer"]["opus"]["n"] == 3
    assert agg["near"] == {**agg["near"], "n": 3, "valid": 2, "fired": 1, "invalid": 1, "fired_or_invalid": 2}
    assert agg["near"]["by_family"]["f1_far"] == {"n": 1, "fired": 1, "invalid": 0}
    assert agg["near"]["by_family"]["N2"] == {"n": 1, "fired": 0, "invalid": 1}
    assert rows[0]["seeds"] == [f1["x"], f1["y"]] and "question" not in json.dumps(rows, ensure_ascii=False)
    tot = R.totals(agg)                                                     # P2's record: totals only (§5.4)
    assert (tot["n_v"], tot["R_card"], tot["R_wrong"], tot["invalid_positives"]) == (3, 1, 1, 1)
    assert tot["near"] == {"n": 3, "valid": 2, "fired": 1, "invalid": 1, "fired_or_invalid": 2}
    assert not [k for k in json.dumps(tot).split('"') if k.startswith(("by_", "abstain", "rates"))]


def test_the_p2_near_miss_record_counts_an_invalid_one_as_fired():
    agg = {"near": {"n": 20, "valid": 18, "fired": 1, "invalid": 2, "fired_or_invalid": 3}}
    assert R.near_record(agg) == {"fired": 3, "n": 20}
    with pytest.raises(HC.HoError, match="not 20"):
        R.near_record({"near": {**agg["near"], "n": 19}})


def test_a_once_only_record_is_rewritten_only_as_itself(tmp_path):
    """A crash between P2's records leaves some written: a rerun keeps each one equal to what it computes now."""
    p = tmp_path / "g1.json"
    assert R.write_same(p, {"a": 1, "t": "x"}) == p and GC.read_json(p) == {"a": 1, "t": "x"}
    sha = GC.sha256_file(p)
    assert R.write_same(p, {"a": 1, "t": "y"}) == p and GC.sha256_file(p) == sha
    with pytest.raises(HC.HoError, match="differs"):
        R.write_same(p, {"a": 2, "t": "y"})


def test_a_gold_card_that_misses_its_gold_stops_the_score(syn, monkeypatch):
    f1 = next(r for r in syn.pool if r["qtype"] == "F1")
    q = question_for(syn, f1)
    monkeypatch.setattr(R.gencard, "card", lambda q, L: SimpleNamespace(covers=lambda g: False))
    with pytest.raises(HC.HoError, match="K0-lines"):
        R.score_row(syn.L, _item(syn, "pos", q, f1))
    monkeypatch.setattr(R.gencard, "card", lambda q, L: None)
    with pytest.raises(HC.HoError, match="disagree"):
        R.score_row(syn.L, _item(syn, "pos", q, f1))


def test_gt_triggers_count_firing_questions(syn, tmp_path):
    f1 = next(r for r in syn.pool if r["qtype"] == "F1")
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps({"questions": [{"question": question_for(syn, f1)}, {"question": "誰是某甲？"}]}),
                  encoding="utf-8")
    assert R.gt_triggers(syn.L, [gt]) == {"gt.json": 1}


def test_g1_doc_follows_the_contract(monkeypatch):
    import analyze_g as AG
    import power_g as PG
    import run_g as RG
    assert (R.G1_N, S.N_POS, S.N_NEAR) == (PG.N_PLAN, PG.P2_POSITIVES, RG.P2_N)
    assert RG.P2_RESULT == GC.QSET_ROOT / R.NEAR_FILE
    keys = {"schema", "R_card", "R_wrong", "n_v", "g1", "pass", "gt_zero_trigger", "f1a_pins_sha256",
            "p2_spec_sha256", "sentence", "t"}
    doc = R.g1_doc(40, 1, 50, 0, "a" * 64, "b" * 64, lambda rc, rw, nv: 0.75)
    assert set(doc) == keys and doc["schema"] == "gen_confirm.g1.v1" and doc["pass"] and doc["sentence"] is None
    assert all(isinstance(doc[k], int) for k in ("R_card", "R_wrong", "n_v")) and isinstance(doc["g1"], float)
    low = R.g1_doc(30, 4, 49, 0, "a" * 64, "b" * 64, lambda rc, rw, nv: 0.69999)
    assert not low["pass"] and low["sentence"] == AG.g1_stop_sentence(30, 4, 49) and low["gt_zero_trigger"]
    assert R.g1_doc(0, 0, 0, 0, "a", "b", lambda *a: 1.0)["g1"] == 0.0
    for bad in (True, -1, 1.0, None):
        with pytest.raises(ValueError, match="count"):
            R.g1_doc(40, 1, 50, bad, "a", "b", lambda *a: 0.9)


def test_g1_sentence_names_the_gt_nail_when_it_fails(monkeypatch):
    """§5.6, §9 (D18): only the GT nail failing names the GT trigger count; both failing name both values; the
    contract's keys stay, and state_g still accepts a passing document."""
    import analyze_g as AG
    import state_g as ST
    gt = R.g1_doc(40, 1, 50, 2, "a" * 64, "b" * 64, lambda rc, rw, nv: 0.9)
    assert not gt["pass"] and not gt["gt_zero_trigger"] and gt["g1"] == 0.9
    assert gt["sentence"] == AG.stop_sentence("G1", "GT 觸發 2 次", "未出題") == \
        "依事先規則停止（G1＝GT 觸發 2 次），不構成無效證據；盲集未出題"
    both = R.g1_doc(30, 4, 49, 1, "a" * 64, "b" * 64, lambda rc, rw, nv: 0.5)
    assert not both["pass"] and both["sentence"] == \
        "依事先規則停止（G1＝R_card＝30/49，R_wrong＝4/49；GT 觸發 1 次），不構成無效證據；盲集未出題"
    keys = {"schema", "R_card", "R_wrong", "n_v", "g1", "pass", "gt_zero_trigger", "f1a_pins_sha256",
            "p2_spec_sha256", "sentence", "t"}
    ok = R.g1_doc(40, 1, 50, 0, "a" * 64, "b" * 64, lambda rc, rw, nv: 0.70)
    assert set(gt) == set(both) == set(ok) == keys and ok["pass"] and ok["sentence"] is None
    assert ST.g1_problems(ok, "a" * 64) == []
    assert any("did not pass" in p for p in ST.g1_problems(gt, "a" * 64))


@needs_store
def test_g1_value_is_power_g_g1_at_n_53(monkeypatch):
    import power_g as PG
    seen = []
    real = PG.g1
    monkeypatch.setattr(PG, "g1", lambda *a, **k: seen.append((a[1:], k)) or real(*a, **k))
    doc = R.g1_doc(40, 1, 50, 0, "a" * 64, "b" * 64)
    assert seen == [((40, 1, 50), {"n": 53})] and doc["pass"] == (doc["g1"] >= 0.70)


# ---------------------------------------------------------------- f1a_g and the F1a group
def test_f1a_group_holds_mech_qg_and_the_p2_path_is_pinned_beside_it():
    keys, p2 = set(F1.f1a_paths()), set(FA.p2_paths())
    assert any(k.endswith("/mech_qg.py") for k in keys) and any(k.endswith("/mech_g.py") for k in keys)
    assert "reports/gen_confirm_20261020/gen_names.json" in keys
    assert {k.rsplit("/", 1)[-1] for k in p2} == {"prompts_g.py", "banned_g.py", "transcript_g.py", "run_qg.py",
                                                  "spec_qg.py", "prompt_qg.py", "prompts_qg.md", "g_common.py",
                                                  "ground_truth.json", "ground_truth.v2.json"} and not p2 & keys
    assert {"test_gen_confirm_qset.py", "test_gen_confirm_qset_run.py"} <= set(FA.TEST_FILES)


def test_pytest_counts_and_nail_problems():
    assert FA.pytest_counts("360 passed in 3.19s") == {"passed": 360, "failed": 0, "skipped": 0, "errors": 0}
    c = FA.pytest_counts("1 failed, 7 passed, 2 skipped, 1 error in 2.0s")
    assert (c["failed"], c["passed"], c["skipped"], c["errors"]) == (1, 7, 2, 1)
    assert FA.nail_problems({"returncode": 0, **FA.pytest_counts("5 passed in 1s")}) == []
    assert FA.nail_problems({"returncode": 0, **FA.pytest_counts("5 passed, 1 skipped in 1s")}) == ["1 skipped"]
    assert "pytest exit 1" in FA.nail_problems({"returncode": 1, **FA.pytest_counts("1 failed")})
    for tail in ("1 xfailed", "1 xpassed", "2 deselected"):
        assert FA.nail_problems({"returncode": 0, **FA.pytest_counts(f"5 passed, {tail} in 1s")}) == [tail]


def test_f1a_written_once_only_in_order_on_a_clean_tree_and_green_tests(tmp_path):
    def made(prefix: str, names) -> dict:
        out = {f"x/{prefix}/{n}": tmp_path / prefix / n for n in names}
        for f in out.values():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# made up\n", encoding="utf-8")
        return out
    group, p2, tests = made("gencard", ("a.py", "b.py")), made("p2", ("run.py", "p.md")), made("tests", ("t.py",))
    out, green = tmp_path / "f1a_pins.json", lambda: {"returncode": 0, "passed": 9, "failed": 0, "skipped": 0, "errors": 0}
    qroot = tmp_path / "qset"
    w = lambda g=group, git=lambda ps: [], t=green: FA.write(out, g, git, t, qroot, p2=p2, test_paths=tests)  # noqa: E731
    with pytest.raises(SystemExit, match="no P1 score"):
        w()
    (qroot / "p1").mkdir(parents=True)
    (qroot / "p1/scores.jsonl").write_text('{"t": 1}\n{"t": 2}\n', encoding="utf-8")
    for leftover in ("drafts/p2-j00.json", "transcripts/p2-j00_1.jsonl", "reserve/p2-j00_1.json"):
        GC.write_json(qroot / "p2" / leftover, {"x": 1})
        with pytest.raises(SystemExit, match="before P2"):
            w()
        (qroot / "p2" / leftover).unlink()
    GC.write_json(qroot / "p2/spec.json", {"x": 1})
    (qroot / "p2/run.lock").write_text("", encoding="utf-8")                # a spec and a lock are not a P2 run
    with pytest.raises(SystemExit, match="not committed"):
        w(git=lambda ps: ["x/gencard/a.py"])
    with pytest.raises(SystemExit, match="not committed.*x/tests/t.py"):
        w(git=lambda ps: [k for k in ps if k.startswith("x/tests/")])       # the nail tests are committed too
    with pytest.raises(SystemExit, match="do not pass"):
        w(t=lambda: {**green(), "returncode": 1, "failed": 1})
    with pytest.raises(SystemExit, match="do not pass"):
        w(t=lambda: {**green(), "skipped": 2})
    with pytest.raises(SystemExit, match="missing"):
        w(g={**group, "x/none.py": tmp_path / "none.py"})

    def edits_while_testing():
        (tmp_path / "p2" / "run.py").write_text("# edited during the tests\n", encoding="utf-8")
        return green()
    with pytest.raises(SystemExit, match="changed while the tests ran"):
        w(t=edits_while_testing)
    (tmp_path / "p2" / "run.py").write_text("# made up\n", encoding="utf-8")
    assert not out.exists()
    doc = w()
    assert set(doc) == {"files", "p2_files", "t", "git_head", "checks"} and doc["checks"]["tests"]["passed"] == 9
    assert doc["p2_files"] == F1.sha_map(p2) and doc["checks"]["test_files"] == F1.sha_map(tests)
    assert doc["checks"]["p1_scores"] == 2 and F1.f1a_problems(F1.sha_map(group), GC.read_json(out)) == []
    assert FA.p2_problems(F1.sha_map(p2), GC.read_json(out)) == []
    with pytest.raises(SystemExit, match="written once"):
        w()
    (tmp_path / "p2" / "p.md").write_text("# changed\n", encoding="utf-8")
    assert FA.p2_problems(F1.sha_map(p2), GC.read_json(out)) == ["x/p2/p.md: sha256 differs from f1a_pins.json"]
    assert FA.p2_problems(F1.sha_map(p2), {"files": {}}) == ["f1a_pins.json has no p2_files map"]


def test_f1a_git_check_flags_an_edited_or_untracked_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],  # noqa
                                    capture_output=True, check=True)
    git("init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "a.py")
    git("commit", "-qm", "a")
    paths = {"a.py": repo / "a.py", "b.py": repo / "b.py", "store.json": tmp_path / "store.json"}
    (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
    assert FA.git_problems(paths, repo) == ["b.py"]
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert FA.git_problems(paths, repo) == ["a.py", "b.py"]


# ---------------------------------------------------------------- modules and windows
def test_the_qset_tools_load_only_the_allowed_modules_of_a_and_none_of_ho_or_qset():
    code = (f"import sys; sys.path.insert(0, {str(H)!r}); import run_qg, spec_qg, prompt_qg, mech_qg, f1a_g, "
            "g_common, analyze_g; g_common.stage0(); from pathlib import Path; "
            "kg = Path(g_common.REPO, 'evaluation/experiments/2026-10-18_kg_cards/A/confirm').resolve(); "
            "f = lambda m: Path(getattr(m, '__file__', None) or '/').resolve(); "
            "print(sorted(n for n, m in list(sys.modules.items()) if kg in f(m).parents)); "
            "print(any('regnal_qset' in str(f(m)) or 'ho_a' in f(m).parts for m in list(sys.modules.values())))")
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True).stdout.split("\n")
    assert set(eval(out[0])) <= {"analyze_c", "c_common", "guards_c"} and out[1] == "False"  # noqa: S307


def windows(s: str) -> set[str]:
    return {s[i:i + WINDOW] for i in range(len(s) - WINDOW + 1)}


@needs_store
def test_these_files_share_no_window_with_a_verse_or_a_real_question():
    """No 8-character window of the new qset files or this file (as written or NFKC) is in a verse or a real
    question (counts only)."""
    import unicodedata
    nf = lambda s: unicodedata.normalize("NFKC", s)  # noqa: E731
    mine = set()
    for p in [Path(__file__), Path(__file__).with_name("test_gen_confirm_qset_run.py")] + [H / n for n in NEW_FILES]:
        src = p.read_text(encoding="utf-8")
        mine |= windows(src) | windows(nf(src))
    texts = {"verses": [json.loads(ln)["text"] for ln in TEXT_UNITS.read_text(encoding="utf-8").splitlines()]}
    for f in ("ground_truth.json", "ground_truth.v2.json"):
        texts[f] = [q["question"] for q in GC.read_json(GC.REPO / f)["questions"]]
    texts["A_confirm"] = [q["question"] for q in GC.read_json(
        GC.STORE / "reports/kg_cards_20261018/A_confirm/questions_frozen.json")["questions"]]
    texts["stage0_items"] = [it["question"] for it in GC.read_json(GC.STAGE0_OUT / "items.json")["items"]]
    hits = {k: sum(bool((windows(t) | windows(nf(t))) & mine) for t in v) for k, v in texts.items()}
    assert all(texts.values()) and hits == {k: 0 for k in texts}

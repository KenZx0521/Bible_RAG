"""Experiment A confirmation set, mechanical checks of drafted questions (ho_a/mech_a.py; confirm_A.md §9 test 4).

Synthetic questions are built from segments.json candidates with template wording (kgca_helpers),
then mutated one rule at a time: S2, S3, single attribute, extra_king, has_ref, S4 seed 亞哈謝 and
S1b in a 2-edge segment must all be blocked, plus the other §2.9 rules. Nothing launches an agent
or calls Ollama; the tests need the store's reference layer and segments.json and skip without them.
"""

import copy

import pytest

import kgca_helpers as K

pytestmark = pytest.mark.skipif(not K.STORE_OK, reason=f"store not mounted ({K.C.SEGMENTS})")


@pytest.fixture(scope="module")
def env():
    import mech_a
    import support
    return {"M": mech_a, "SU": support, "doc": K.seg_doc()}


def _cand(sid, qtype, **match):
    seg = K.seg_row(sid)
    c = next(c for c in seg["candidates"] if c["qtype"] == qtype and all(c.get(k) == v for k, v in match.items()))
    return seg, c


def _check(env, q, seg, slot_type=None, others=(), reverse_of=None):
    found, hidden = env["M"].check_item(q, q["id"], seg, slot_type or q["qtype"], env["doc"]["segments"],
                                        others, reverse_of)
    return {v.rule for v in found if v.level == "error"}, found, hidden


def test_every_segment_candidate_gives_a_clean_question(env):
    for seg in env["doc"]["segments"]:
        for i, c in enumerate(seg["candidates"]):
            q = K.make_question(f"Q{seg['id']}t{i}", seg, c)
            rules, _, hidden = _check(env, q, seg)
            assert rules == set(), (seg["id"], c, rules)
            assert set(hidden) == {"ref_disagree", "gen_passage", "answer_is_father"} and hidden["ref_disagree"] is False


def test_s2_cross_kingdom_sync_is_blocked(env):
    seg, c = _cand("J1", "S1a")
    q = K.make_question("QJ1s1a1", seg, c)
    q["question"] = "猶大王亞撒登基時，是以色列王耶羅波安在位第幾年？"
    rules, _, _ = _check(env, q, seg)
    assert {"forbidden_form", "extra_king"} <= rules


def test_s3_contemporaries_is_blocked(env):
    seg, c = _cand("I4", "S1a", k=2)
    q = K.make_question("QI4s1a1", seg, c)
    q["question"] = "以色列王亞哈在位期間，猶大有哪些王？"
    assert "forbidden_form" in _check(env, q, seg)[0]


def test_single_attribute_question_is_blocked(env):
    seg, c = _cand("I3", "S1a", k=2)
    q = K.make_question("QI3s1a1", seg, c)
    q["question"] = "以色列王暗利在位幾年？"
    q["chain"] = q["chain"][1:2] + [dict(q["chain"][1], role="answer")]
    q["chain"][0]["role"] = "seed"
    q["answer"] = {"kind": "count", "text": "十二年", "accept": [], "value": 12, "unit": "年"}
    rules = _check(env, q, seg)[0]
    assert {"forbidden_form", "chain_len", "key_form"} <= rules


def test_second_question_is_blocked(env):
    seg, c = _cand("I8", "S1a", k=2)
    q = K.make_question("QI8s1a1", seg, c)
    q["question"] += "他在位多久？"
    assert "forbidden_form" in _check(env, q, seg)[0]


def test_extra_king_and_reference_are_blocked(env):
    seg, c = _cand("I2", "S1a", k=2)
    q = K.make_question("QI2s1a1", seg, c)
    mid = q["chain"][1]["king"]
    bad = dict(q, question=q["question"].replace("是誰", f"（{mid}之後）是誰"))
    rules, found, _ = _check(env, bad, seg)
    assert "extra_king" in rules and any(mid in v.detail for v in found if v.rule == "extra_king")
    assert "has_ref" in _check(env, dict(q, question=q["question"] + "（王上16:8）"), seg)[0]
    assert "has_ref" in _check(env, dict(q, question="依列王紀，" + q["question"]), seg)[0]
    assert "has_ref" in _check(env, dict(q, question=q["question"] + "（王下 3）"), seg)[0]
    assert "has_ref" not in _check(env, dict(q, question="不算王上一位，" + q["question"]), seg)[0]


def test_s4_seed_ahaziah_is_blocked(env):
    seg = K.seg_row("J1")
    cand = {"qtype": "S4", "seed": "J06", "answer": "J04", "steps": 2}
    q = K.make_question("QJ1s3a1", seg, cand)
    rules, found, _ = _check(env, q, seg, "S4")
    assert "chain_len" in rules and any("亞哈謝" in v.detail for v in found if v.rule == "chain_len")


def test_s4_needs_its_convention(env):
    seg, c = _cand("J4", "S4")
    q = K.make_question("QJ4s3a1", seg, c)
    assert "s4_convention" in _check(env, dict(q, convention=""), seg)[0]
    assert "s4_convention" in _check(env, dict(q, question="猶大王約雅敬出生時在位的猶大王是誰？"), seg)[0]


def test_s1b_in_a_two_edge_segment_is_blocked(env):
    seg = K.seg_row("I2")
    cand = {"qtype": "S1b", "a": seg["kings"][0], "b": seg["kings"][2], "value": 2}
    q = K.make_question("QI2s2a1", seg, cand)
    rules = _check(env, q, seg, "S1b")[0]
    assert "s1b_short_seg" in rules and "slot_mismatch" not in rules


def test_segment_cross_and_unresolved_names(env):
    seg, c = _cand("I2", "S1a", k=2)
    q = K.make_question("QI2s1a1", seg, c)
    out = copy.deepcopy(q)
    out["chain"].append(dict(out["chain"][-1], king="暗利", role="answer"))
    out["chain"][-2]["role"] = "step"
    out["k"] = 3
    assert "seg_cross" in _check(env, out, seg)[0]
    typo = copy.deepcopy(q)
    typo["chain"][1]["king"] = "以拉拉"
    assert "name_unresolved" in _check(env, typo, seg)[0]


def test_basis_must_be_a_kings_verse_in_range(env):
    seg, c = _cand("I2", "S1a", k=2)
    q = K.make_question("QI2s1a1", seg, c)
    for keys, rule in ((["2ch.16.1"], "basis_in_range"), (["1ki.99.1"], "basis_exists"), ([], "basis_exists")):
        bad = copy.deepcopy(q)
        bad["chain"][1]["basis"] = keys
        assert rule in _check(env, bad, seg)[0]


def test_genealogy_shortcut_is_blocked(env):
    seg = K.seg_row("J2")
    q = K.make_question("QJ2s1a1", seg, {"qtype": "S1a", "seed": "J09", "answer": "J11", "k": 2})
    rules, found, _ = _check(env, q, seg)
    assert "genealogy_shortcut" in rules
    assert "1ch.3.12" in next(v.detail for v in found if v.rule == "genealogy_shortcut")


def test_namesake_seed_needs_the_father(env):
    seg, c = _cand("I7", "S1a", k=2)
    q = K.make_question("QI7s1a1", seg, c)
    assert "（約阿施的兒子）" in q["question"] and _check(env, q, seg)[0] == set()
    bare = dict(q, question=q["question"].replace("（約阿施的兒子）", ""))
    assert "seeds_named" in _check(env, bare, seg)[0]


def test_namesake_tag_naming_a_chain_king_is_blocked(env):
    # I6 backward (耶羅波安→約阿施→約哈斯) is not a segments.json candidate; written anyway, the required
    # tag 「（約阿施的兒子）」 names the intermediate king
    seg = K.seg_row("I6")
    q = K.make_question("QI6s1a1", seg, {"qtype": "S1a", "seed": "I13", "answer": "I11", "k": -2})
    rules, found, _ = _check(env, q, seg)
    assert "extra_king" in rules and any("推算鏈上的另一位王" in v.detail for v in found)


def test_optional_father_tag_is_an_extra_king(env):
    seg, c = _cand("I4", "S1a", k=-2)                                     # 約蘭 → 亞哈 (his father)
    q = K.make_question("QI4s1a2", seg, c)
    assert _check(env, q, seg)[0] == set()
    tagged = dict(q, question=q["question"].replace("約蘭", "約蘭（亞哈的兒子）", 1))
    rules, found, _ = _check(env, tagged, seg)
    assert "extra_king" in rules and any("亞哈" in v.detail for v in found if v.rule == "extra_king")
    seg, c = _cand("J4", "S1a", k=-2)                                     # 約雅敬 → 約西亞 (his father)
    q = K.make_question("QJ4s1a2", seg, c)
    tagged = dict(q, question=q["question"].replace("約雅敬", "約西亞的兒子約雅敬", 1))
    assert "extra_king" in _check(env, tagged, seg)[0]


def test_seeds_must_be_the_chain_ends(env):
    seg, c = _cand("I4", "S1a", k=2)                                      # 亞哈 → 亞哈謝 → 約蘭
    q = K.make_question("QI4s1a1", seg, c)
    for extra in ("約蘭", "亞哈謝"):                                       # answer or intermediate as 2nd seed
        bad = copy.deepcopy(q)
        bad["seeds"].append({"name": extra, "father": None})
        bad["question"] = bad["question"].replace("是誰", f"（經過{extra}）是誰")
        rules = _check(env, bad, seg)[0]
        assert "seeds_chain" in rules, extra
    seg, c = _cand("J1", "S4")                                            # chain starts at 約蘭
    q = K.make_question("QJ1s3a1", seg, c)
    assert _check(env, q, seg)[0] == set()
    bad = copy.deepcopy(q)
    bad["seeds"] = [{"name": "亞哈謝", "father": None}]
    bad["question"] = bad["question"].replace("約蘭", "亞哈謝", 1)
    assert "seeds_chain" in _check(env, bad, seg)[0]
    seg, c = _cand("J1", "S1b")
    q = K.make_question("QJ1s2a1", seg, c)
    bad = copy.deepcopy(q)
    bad["seeds"] = bad["seeds"][:1]
    assert "seeds_chain" in _check(env, bad, seg)[0]


def test_key_form_refuses_another_kings_name_and_wrong_counts(env):
    seg, c = _cand("I2", "S1a", k=2)
    q = K.make_question("QI2s1a1", seg, c)
    bad = copy.deepcopy(q)
    bad["answer"]["accept"] = ["巴沙"]
    assert "key_form" in _check(env, bad, seg)[0]
    seg, c = _cand("J1", "S1b")
    q = K.make_question("QJ1s2a1", seg, c)
    bad = copy.deepcopy(q)
    bad["answer"]["value"] += 1
    assert "key_form" in _check(env, bad, seg)[0]
    assert "key_form" in _check(env, dict(q, answer=dict(q["answer"], unit="年")), seg)[0]


def test_slot_mismatch_and_reverse_direction(env):
    seg, c = _cand("I3", "S1a", k=2)
    q = K.make_question("QI3s2a1", seg, c)
    assert "slot_mismatch" in _check(env, q, seg, "S1c")[0]
    assert "slot_mismatch" in _check(env, dict(q, kingdom="猶大"), seg)[0]
    assert "slot_mismatch" in _check(env, q, seg, "S1a_rev", reverse_of={"k": 2})[0]
    seg2, c2 = _cand("I3", "S1a", k=-2)
    rev = K.make_question("QI3s2a1", seg2, c2)
    assert _check(env, rev, seg2, "S1a_rev", reverse_of={"k": 2})[0] == set()


def test_duplicate_in_segment(env):
    seg, c = _cand("I3", "S1a", k=2)
    first = K.make_question("QI3s1a1", seg, c)
    again = K.make_question("QI3s2a1", seg, c)
    rules, found, _ = _check(env, again, seg, others=[first])
    assert "dup_in_segment" in rules


def test_fix_issues_are_neutral_and_never_carry_hidden_flags_or_ids(env):
    seg = K.seg_row("J2")
    q = K.make_question("QJ2s1a1", seg, {"qtype": "S1a", "seed": "J09", "answer": "J11", "k": 2})
    q["question"] += "（王下14:21）"
    found, hidden = env["M"].check_item(q, q["id"], seg, "S1a", env["doc"]["segments"])
    lines = env["M"].fix_issues(found)
    assert lines and hidden["gen_passage"] is True
    text = "\n".join(lines)
    for word in ("ref_disagree", "gen_passage", "J09", "J11", "J1", "參照", "G-auto"):
        assert word not in text

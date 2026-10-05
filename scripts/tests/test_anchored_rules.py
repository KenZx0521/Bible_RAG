"""Anchored kinship rules: a kinship edge only where a verse states it (REL-01).

Step 2's rule rows took the direction of SON_OF / FATHER_OF from id order, so
Lot became Terah's father. Step 6.05 replaces them with anchored_rules: four
slot patterns inside one verse (P1 P的兒子C, P2 C是P的兒子, P3 給F生C, P4 H的妻W),
both names resolved through the pericope's own MENTIONS, the direction taken
from the slot. The W1 decisions are in config/relations/anchored_rules.yaml:
only 「給F生C」 emits FATHER_OF (K1), a span resolves only as its entity's
declared name (K2), the tokenizer knows Person/Place/Group names only (review
2b), and a list item followed by 的 ends the list (review 2a, Q3 'cont').
The same-name guard (K2 「同名時 abstain」, §6 #12) abstains a parent hit whose
child already has another curated, prior or llm parent, or whose endpoint is a
known homonym node (Q2), and logs it as a conflict.

The regression fixture holds 46 real verses from the W1 simulation
(docs/records/2026-10-04_kg_fix/batch1/w1_1A/gen_fixture.py) with the parents
each child already has; without a guard every expected and every abstained
triple is a hit, with the guard exactly the expected ones.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from entity_extraction.entity_overrides import final_type, load_overrides
from relation_extraction import anchored_rules
from relation_extraction.anchored_rules import (
    GuardConfig, build_lexicon, build_span_map, compile_tokenizer, load_config, parent_map_of, run,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "anchored_rules" / "regression.jsonl"
FIXTURE_SHA256 = "17ce5b9babb2e9564ef0c2fd839468935ee5c3fc6e197ffca47166b2018e4dc6"
SIMULATOR = ROOT / "docs/records/2026-10-04_kg_fix/batch1/w1_1A/anchored_w1.py"

CFG = load_config()
NO_GUARD = dataclasses.replace(CFG, guard=GuardConfig(other_parent=False, homonym_ids=frozenset()))
PID = "tst:1:0"
P1, P2, P3, P4 = "P1_child_of", "P2_is_child_of", "P3_begot", "P4_wife"


def _run(text, names, cfg=CFG, parent_map=None):
    """run() over one verse; names maps a span to one Person id."""
    span_map = {PID: {span: {eid} for span, eid in names.items()}}
    return run([{"id": PID, "content": f"**1** {text}"}], span_map,
               compile_tokenizer(list(names)), cfg, parent_map or {})


def _hits(text, names, cfg=CFG, parent_map=None):
    """(head, relation, tail, pattern) of one verse."""
    return [(h["head_id"], h["relation"], h["tail_id"], h["pattern"])
            for h in _run(text, names, cfg, parent_map)[0]]


def _entities(*rows):
    """{id: entities.jsonl row} from (id, type, canonical_name, aliases)."""
    return {eid: {"entity_id": eid, "type": etype, "canonical_name": name, "aliases": list(aliases)}
            for eid, etype, name, aliases in rows}


def _mentions(pid, *pairs):
    """Verse-level entity_mentions.jsonl rows of pericope pid from (entity_id, span)."""
    return [{"entity_id": eid, "source_id": f"{pid}:v:1", "source_type": "verse", "text_span": span}
            for eid, span in pairs]


def _pipeline(entities, mentions, pericopes, cfg=CFG, chunk_parent=None):
    final_types = {eid: final_type(eid, e["type"], load_overrides()) for eid, e in entities.items()}
    lexicon = build_lexicon(entities, final_types, mentions, cfg)
    span_map, skipped = build_span_map(entities, final_types, mentions, chunk_parent or {}, cfg)
    hits, stats, conflicts = run(pericopes, span_map, compile_tokenizer(lexicon), cfg, {})
    return lexicon, span_map, skipped, hits, stats, conflicts


@lru_cache(maxsize=None)
def _fixture_rows():
    return tuple(json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines())


def _fixture_row(case):
    return next(row for row in _fixture_rows() if row["case"] == case)


def _fixture_run(row, cfg=CFG, parent_map=None):
    """run() over the fixture row's verse, with its own lexicon and pericope spans."""
    pid = row["pericope_id"]
    span_map = {pid: {span: set(ids) for span, ids in row["spans"].items()}}
    pericope = {"id": pid, "content": f"**{row['verse']}** {row['text']}"}
    return run([pericope], span_map, compile_tokenizer(row["lexicon"]), cfg, parent_map or {})


def _fixture_parents(row):
    return {child: set(parents) for child, parents in row["parents"].items()}


def _fixture_hits(row, cfg=CFG, parent_map=None):
    return _fixture_run(row, cfg, parent_map)[0]


def _triples(hits):
    return [(h["head_id"], h["relation"], h["tail_id"]) for h in hits]


# --- config -----------------------------------------------------------------

def test_shipped_config_holds_the_w1_decisions():
    assert (CFG.begot, CFG.surface, CFG.list_stop) == ("gei", "declared", "cont")
    assert CFG.lexicon_types == {"Person", "Place", "Group"}
    assert CFG.slot_types == {"Person"}
    assert CFG.deny_ids == {"group:yehehua"}
    assert CFG.min_name_len == 2
    assert CFG.guard == GuardConfig(other_parent=True,
                                    homonym_ids=frozenset({"person:bide", "person:yuehan（shitu）"}))


def test_config_copies_the_simulator_constants():
    spec = importlib.util.spec_from_file_location("anchored_w1_archive", SIMULATOR)
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    assert CFG.list_sep == sim.LIST_SEP
    assert CFG.prev_ok == sim.PREV_OK
    assert CFG.trail_ok == sim.TRAIL_OK
    assert CFG.sentence_end == set("。；：！？")
    for name in ("child_re", "begot_re", "wife_re", "is_child_re"):
        assert getattr(CFG, name).pattern == getattr(sim, name.upper()).pattern


@pytest.mark.parametrize("change, message", [
    ({"version": 2}, "version"),
    ({"stop_de": "cont"}, "stop_de"),
    ({"begot": "mother"}, "begot"),
    ({"list_stop": "first"}, "list_stop"),
    ({"slot_types": ["Persons"]}, "Persons"),
    ({"child_re": "的兒子"}, "child_re"),
    ({"wife_re": "的妻("}, "wife_re"),
    ({"guard": {"other_parent": True}}, "homonym_ids"),
    ({"guard": {"other_parent": "yes", "homonym_ids": []}}, "other_parent"),
    ({"guard": {"other_parent": True, "homonym_ids": "person:bide"}}, "homonym_ids"),
    ({"guard": {"other_parent": True, "homonym_ids": [], "disagree": True}}, "disagree"),
    ({"guard": True}, "guard"),
])
def test_loader_rejects_a_malformed_config(tmp_path, change, message):
    doc = yaml.safe_load(anchored_rules.CONFIG_PATH.read_text(encoding="utf-8"))
    path = tmp_path / "anchored_rules.yaml"
    path.write_text(yaml.safe_dump({**doc, **change}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_loader_rejects_a_missing_key(tmp_path):
    doc = yaml.safe_load(anchored_rules.CONFIG_PATH.read_text(encoding="utf-8"))
    del doc["deny_ids"]
    path = tmp_path / "anchored_rules.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="deny_ids"):
        load_config(path)


# --- slot patterns ----------------------------------------------------------

def test_gei_begot_emits_father_of_each_child():
    hits = _fixture_hits(_fixture_row("named:gen:36:0:14"))
    assert [t for t in _triples(hits) if t[1] == "FATHER_OF"] == [
        ("person:yisao", "FATHER_OF", "person:yewushi"),
        ("person:yisao", "FATHER_OF", "person:yalan"),
        ("person:yisao", "FATHER_OF", "person:kela"),
    ]
    assert {h["pattern"] for h in hits if h["relation"] == "FATHER_OF"} == {P3}


TERAH = {"他拉": "person:tala", "亞伯蘭": "person:yabolan", "拿鶴": "person:nahe", "哈蘭": "person:halan"}


@pytest.mark.parametrize("text, names", [
    ("他拉生亞伯蘭、拿鶴、哈蘭。", TERAH),
    ("拉結生約瑟之後，雅各對拉班說：", {"拉結": "person:lajie", "約瑟": "person:yuese"}),
])
def test_plain_begot_emits_nothing(text, names):
    assert _hits(text, names) == []


def test_begot_father_mode_reads_every_begot():
    father = dataclasses.replace(CFG, begot="father")
    assert _hits("他拉生亞伯蘭、拿鶴、哈蘭。", TERAH, father) == [
        ("person:tala", "FATHER_OF", "person:yabolan", P3),
        ("person:tala", "FATHER_OF", "person:nahe", P3),
        ("person:tala", "FATHER_OF", "person:halan", P3),
    ]
    off = dataclasses.replace(CFG, begot="off")
    assert [h for h in _fixture_hits(_fixture_row("named:gen:36:0:14"), off) if h["pattern"] == P3] == []


def test_child_of_slot():
    assert _triples(_fixture_hits(_fixture_row("named:1ch:29:2:26"))) == [
        ("person:dawei", "SON_OF", "person:yexi")]
    assert _hits("迦勒的女兒押撒。", {"迦勒": "person:jiale", "押撒": "person:yasa"}) == [
        ("person:yasa", "DAUGHTER_OF", "person:jiale", P1)]


def test_is_child_of_chain():
    names = {"大衛": "person:dawei", "耶西": "person:yexi", "俄備得": "person:ebeide"}
    assert _hits("大衛是耶西的兒子；耶西是俄備得的兒子。", names) == [
        ("person:dawei", "SON_OF", "person:yexi", P2),
        ("person:yexi", "SON_OF", "person:ebeide", P2),
    ]
    assert _triples(_fixture_hits(_fixture_row("named:luk:3:2:31"))) == [
        ("person:mainan", "SON_OF", "person:madata"),
        ("person:madata", "SON_OF", "person:nadan"),
        ("person:nadan", "SON_OF", "person:dawei"),
    ]


def test_wife_slot_emits_the_sorted_pair_for_the_first_item():
    names = {"以掃": "person:yisao", "阿何利巴瑪": "person:ahelibama", "亞大": "person:yada"}
    assert _hits("以掃的妻子阿何利巴瑪、亞大。", names) == [
        ("person:ahelibama", "SPOUSE_OF", "person:yisao", P4)]


ANA = {"亞拿": "person:yana", "耶戶": "person:yehu"}


@pytest.mark.parametrize("text, names, expected", [
    ("亞拿的兒子耶戶。", ANA, [("person:yehu", "SON_OF", "person:yana", P1)]),
    ("亞拿突的兒子耶戶。", ANA, []),   # 亞拿 glued to the following 突
    ("耶戶的兒子亞拿突。", ANA, []),
    ("撒拉但的兒子耶戶。", {"拉但": "person:ladan", "耶戶": "person:yehu"}, []),   # glued to 撒
])
def test_word_boundaries(text, names, expected):
    assert _hits(text, names) == expected


def test_ambiguous_span_resolves_to_nothing():
    span_map = {PID: {"雅各": {"person:yage", "person:yage2"}, "約瑟": {"person:yuese"}}}
    hits, stats, _ = run([{"id": PID, "content": "**1** 雅各的兒子約瑟。"}], span_map,
                         compile_tokenizer(["雅各", "約瑟"]), CFG, {})
    assert hits == []
    assert stats["ambiguous_name"] == 1


# --- lexicon and span map ---------------------------------------------------

def test_god_is_denied():
    entities = _entities(("group:yehehua", "Group", "耶和華", ["上帝"]),
                         ("person:jidu", "Person", "基督", []))
    mentions = _mentions(PID, ("group:yehehua", "上帝"), ("person:jidu", "基督"))
    pericopes = [{"id": PID, "content": "**1** 你是上帝的兒子基督不是？"}]
    assert _pipeline(entities, mentions, pericopes)[3] == []
    # without the deny list the override's Person label would let 上帝 fill the slot
    no_deny = dataclasses.replace(CFG, deny_ids=frozenset())
    assert _triples(_pipeline(entities, mentions, pericopes, no_deny)[3]) == [
        ("person:jidu", "SON_OF", "group:yehehua")]


def test_declared_surface_skips_homophone_span():
    entities = _entities(("person:yasa", "Person", "亞撒", []),
                         ("person:yuesafa", "Person", "約沙法", []))
    mentions = _mentions(PID, ("person:yasa", "亞薩"), ("person:yuesafa", "約沙法"))
    pericopes = [{"id": PID, "content": "**1** 亞薩的兒子約沙法。"}]
    _, span_map, skipped, hits, _, _ = _pipeline(entities, mentions, pericopes)
    assert hits == [] and skipped == 1
    assert span_map == {PID: {"約沙法": {"person:yuesafa"}}}
    _, _, skipped, hits, _, _ = _pipeline(entities, mentions, pericopes,
                                          dataclasses.replace(CFG, surface="any"))
    assert _triples(hits) == [("person:yuesafa", "SON_OF", "person:yasa")] and skipped == 0


def test_mentions_roll_up_to_their_pericope():
    entities = _entities(("person:yexi", "Person", "耶西", []), ("person:dawei", "Person", "大衛", []))
    mentions = [
        {"entity_id": "person:yexi", "source_id": "1ch:29:2:v:26", "source_type": "verse", "text_span": "耶西"},
        {"entity_id": "person:dawei", "source_id": "1ch:29:2:0", "source_type": "chunk", "text_span": "大衛 "},
        {"entity_id": "person:dawei", "source_id": "1sa:16:0", "source_type": "pericope", "text_span": "大衛"},
    ]
    final_types = {eid: e["type"] for eid, e in entities.items()}
    span_map, _ = build_span_map(entities, final_types, mentions, {"1ch:29:2:0": "1ch:29:2"}, CFG)
    assert span_map == {"1ch:29:2": {"耶西": {"person:yexi"}, "大衛": {"person:dawei"}},
                        "1sa:16:0": {"大衛": {"person:dawei"}}}


def test_eot_junk_does_not_swallow_the_slot():
    entities = _entities(("person:yexi", "Person", "耶西", []), ("person:dawei", "Person", "大衛", []),
                         ("object:erzidawei", "Object", "兒子大衛", []))
    mentions = _mentions(PID, ("person:yexi", "耶西"), ("person:dawei", "大衛"),
                         ("object:erzidawei", "兒子大衛"))
    pericopes = [{"id": PID, "content": "**1** 耶西的兒子大衛作以色列眾人的王，"}]
    lexicon, _, _, hits, _, _ = _pipeline(entities, mentions, pericopes)
    assert "兒子大衛" not in lexicon
    assert _triples(hits) == [("person:dawei", "SON_OF", "person:yexi")]
    with_objects = dataclasses.replace(CFG, lexicon_types=CFG.lexicon_types | {"Object"})
    assert _pipeline(entities, mentions, pericopes, with_objects)[3] == []


def test_lexicon_is_stripped_long_names_first_and_drops_single_characters():
    entities = _entities(("person:yasa", "Person", " 亞撒 ", ["亞薩"]), ("place:dan", "Place", "但", []),
                         ("theme:ai", "Theme", "愛心", []))
    mentions = _mentions(PID, ("person:yasaliya", "亞撒利雅"), ("theme:ai", "仁愛"))
    final_types = {"person:yasa": "Person", "place:dan": "Place", "theme:ai": "Theme",
                   "person:yasaliya": "Person"}
    assert build_lexicon(entities, final_types, mentions, CFG) == ["亞撒利雅", "亞撒", "亞薩"]


# --- verses and lists -------------------------------------------------------

def test_no_cross_verse_match():
    names = {"耶西": "person:yexi", "大衛": "person:dawei"}
    span_map = {PID: {span: {eid} for span, eid in names.items()}}
    tokenizer = compile_tokenizer(list(names))
    split = [{"id": PID, "content": "**1** 耶西的兒子\n\n**2** 大衛作王。"}]
    assert run(split, span_map, tokenizer, CFG, {})[0] == []
    one = [{"id": PID, "content": "**1** 耶西的\n\n**2** 兒子大衛作王。\n\n**3** 耶西的兒子大衛作王。"}]
    hits = run(one, span_map, tokenizer, CFG, {})[0]
    assert hits == [{"head_id": "person:dawei", "relation": "SON_OF", "tail_id": "person:yexi",
                     "source_pericope_id": PID, "verse": 3, "pattern": P1,
                     "evidence_span": "耶西的兒子大衛作王。"}]


LIST_STOP_CASES = {
    "named:2ch:28:2:12": [("person:yasaliya", "SON_OF", "person:yuehanan"),
                          ("person:bilijia", "SON_OF", "person:mishilimo")],
    "named:jer:36:1:12": [("person:jimaliya", "SON_OF", "person:shafan")],
    "named:jer:38:0:1": [("person:shifatiya", "SON_OF", "person:matan"),
                         ("person:jidali", "SON_OF", "person:bashihuer"),
                         ("person:youjia", "SON_OF", "person:shilimiya")],
    "named:jer:38:0:6": [("person:majiya", "SON_OF", "person:hamilei")],
    "named:gen:36:0:3": [],
    "named:gen:28:1:9": [],
    "named:2sa:2:2:13": [("person:yueya", "SON_OF", "person:xiluya")],
    "named:mrk:6:0:3": [("person:yage", "SON_OF", "person:maliya"),
                        ("person:yuexi", "SON_OF", "person:maliya")],
}


@pytest.mark.parametrize("case", list(LIST_STOP_CASES))
def test_list_stops_at_de(case):
    assert _triples(_fixture_hits(_fixture_row(case))) == LIST_STOP_CASES[case]


@pytest.mark.parametrize("case, list_stop, triple, present", [
    # off: the next owner joins the list (review 2a: 沙龍 is 耶希西家's father)
    ("named:2ch:28:2:12", "off", ("person:shalong", "SON_OF", "person:mishilimo"), True),
    ("named:mrk:6:0:3", "off", ("person:bide", "SON_OF", "person:maliya"), True),
    # all: even the first item at the slot end is dropped (jer 38:6 loses 瑪基雅)
    ("named:jer:38:0:6", "all", ("person:majiya", "SON_OF", "person:hamilei"), False),
])
def test_list_stop_modes(case, list_stop, triple, present):
    # no guard: person:bide is a homonym id, which would hide what the list stop does
    hits = _fixture_hits(_fixture_row(case), dataclasses.replace(NO_GUARD, list_stop=list_stop))
    assert (triple in _triples(hits)) is present


# --- same-name guard (pass 1) -----------------------------------------------

LEVI = {"利未": "person:liwei", "麥基": "person:maiji"}


def test_parent_map_reads_each_relation_from_the_parent_side():
    assert parent_map_of([
        ("person:yage", "FATHER_OF", "person:yuese"),
        ("person:lajie", "MOTHER_OF", "person:yuese"),
        ("person:yuese", "SON_OF", "person:yage"),
        ("person:dina", "DAUGHTER_OF", "person:liya"),
        ("person:yage", "SPOUSE_OF", "person:lajie"),
        ("person:yuese", "SIBLING_OF", "person:bianyamin"),
    ]) == {"person:yuese": {"person:yage", "person:lajie"}, "person:dina": {"person:liya"}}


def test_guard_abstains_when_child_has_another_parent():
    hits, stats, conflicts = _run("利未是麥基的兒子；", LEVI, parent_map={"person:liwei": {"person:liya"}})
    assert hits == []
    assert conflicts == [{"head_id": "person:liwei", "relation": "SON_OF", "tail_id": "person:maiji",
                          "source_pericope_id": PID, "verse": 1, "pattern": P2,
                          "reason": "other_parent", "other_parents": ["person:liya"]}]
    assert (stats["pattern_hits"], stats["guard_other_parent"], stats["guard_homonym"],
            stats["emitted_hits"]) == (1, 1, 0, 0)
    assert stats["emitted_by_pattern"][P2] == 0 and stats["by_pattern"][P2] == 1


def test_guard_allows_the_same_parent():
    names = {"耶西": "person:yexi", "大衛": "person:dawei"}
    parents = {"person:dawei": {"person:yexi"}, "person:yexi": {"person:ebeide"}}
    assert _hits("耶西的兒子大衛。", names, parent_map=parents) == [
        ("person:dawei", "SON_OF", "person:yexi", P1)]
    # the parent's own parents are no other parents of the child
    assert _run("耶西的兒子大衛。", names, parent_map=parents)[2] == []


def test_guard_reads_father_of_from_the_head():
    row = _fixture_row("named:gen:36:0:14")
    # 1ch 7:10 gives 耶烏施 the father 比勒罕 (a merged homonym node)
    _, _, conflicts = _fixture_run(row, parent_map={"person:yewushi": {"person:bileihan"}})
    assert [(c["head_id"], c["relation"], c["tail_id"], c["pattern"], c["other_parents"])
            for c in conflicts] == [
        ("person:yisao", "FATHER_OF", "person:yewushi", P3, ["person:bileihan"])]
    # 以掃 has parents himself: as the father that blocks nothing
    assert len(_fixture_hits(row, parent_map={"person:yisao": {"person:yisa"}})) == 4


def test_mother_counts_as_another_parent():
    row = _fixture_row("named:1ch:1:1:28")
    assert row["parents"]["person:yisa"] == ["person:sala", "person:yabolahan"]
    hits, stats, conflicts = _fixture_run(row, parent_map=_fixture_parents(row))
    assert hits == []
    assert [(c["head_id"], c["reason"], c["other_parents"]) for c in conflicts] == [
        ("person:yisa", "other_parent", ["person:sala"]),
        ("person:yishimali", "other_parent", ["person:xiajia"]),
    ]
    assert stats["guard_other_parent"] == 2


@pytest.mark.parametrize("text, names", [
    ("你是約翰的兒子西門，", {"約翰": "person:yuehan（shitu）", "西門": "person:bide"}),   # parent slot
    ("西門的兒子約翰。", {"約翰": "person:yuehan（shitu）", "西門": "person:bide"}),       # child slot
    ("西門是約翰的兒子；", {"約翰": "person:yuehan（shitu）", "西門": "person:bide"}),
    ("給西門生了約翰。", {"約翰": "person:yuehan（shitu）", "西門": "person:bide"}),
    ("西門的兒子耶戶。", {"西門": "person:bide", "耶戶": "person:yehu"}),               # one endpoint
])
def test_homonym_ids_abstain_in_either_slot(text, names):
    hits, stats, conflicts = _run(text, names)
    assert hits == []
    assert [c["reason"] for c in conflicts] == ["homonym"]
    assert (stats["guard_homonym"], stats["guard_other_parent"]) == (1, 0)


def test_homonym_guard_drops_peter_son_of_the_apostle_john():
    row = _fixture_row("named:jhn:1:3:42")
    hits, _, conflicts = _fixture_run(row, parent_map=_fixture_parents(row))
    assert hits == []
    assert conflicts == [{"head_id": "person:bide", "relation": "SON_OF", "tail_id": "person:yuehan（shitu）",
                          "source_pericope_id": "jhn:1:3", "verse": 42, "pattern": P1,
                          "reason": "homonym", "other_parents": []}]
    assert _triples(_fixture_hits(row, NO_GUARD)) == [("person:bide", "SON_OF", "person:yuehan（shitu）")]


def test_homonym_is_checked_before_other_parents():
    _, stats, conflicts = _run("西門的兒子耶戶。", {"西門": "person:bide", "耶戶": "person:yehu"},
                               parent_map={"person:yehu": {"person:yana"}})
    assert [(c["reason"], c["other_parents"]) for c in conflicts] == [("homonym", ["person:yana"])]
    assert (stats["guard_homonym"], stats["guard_other_parent"]) == (1, 0)


def test_spouse_hits_are_not_guarded():
    names = {"西門": "person:bide", "阿何利巴瑪": "person:ahelibama"}
    hits, _, conflicts = _run("西門的妻子阿何利巴瑪。", names,
                              parent_map={"person:ahelibama": {"person:yana"}})
    assert _triples(hits) == [("person:ahelibama", "SPOUSE_OF", "person:bide")] and conflicts == []


def test_run_requires_the_parent_map():
    with pytest.raises(TypeError, match="parent_map"):
        run([], {}, compile_tokenizer([]), CFG)


def test_guard_parts_can_be_disabled_by_config():
    parents = {"person:liwei": {"person:liya"}}
    no_other = dataclasses.replace(CFG, guard=dataclasses.replace(CFG.guard, other_parent=False))
    assert _hits("利未是麥基的兒子；", LEVI, no_other, parents) == [
        ("person:liwei", "SON_OF", "person:maiji", P2)]
    assert _hits("西門的兒子耶戶。", {"西門": "person:bide", "耶戶": "person:yehu"}, no_other) == []
    no_homonym = dataclasses.replace(CFG, guard=dataclasses.replace(CFG.guard, homonym_ids=frozenset()))
    assert _hits("西門的兒子耶戶。", {"西門": "person:bide", "耶戶": "person:yehu"}, no_homonym) == [
        ("person:yehu", "SON_OF", "person:bide", P1)]
    assert _hits("利未是麥基的兒子；", LEVI, no_homonym, parents) == []


# --- determinism and regression ---------------------------------------------

def test_two_runs_identical():
    entities = _entities(("person:yexi", "Person", "耶西", []), ("person:dawei", "Person", "大衛", ["大衛王"]),
                         ("person:yisao", "Person", "以掃", []), ("person:yewushi", "Person", "耶烏施", []),
                         ("person:yalan", "Person", "雅蘭", []), ("place:xilun", "Place", "希崙", []))
    mentions = _mentions(PID, *[(eid, e["canonical_name"]) for eid, e in entities.items()])
    pericopes = [{"id": PID, "content": "**1** 耶西的兒子大衛。\n\n**2** 她給以掃生了耶烏施、雅蘭。"}]
    first = _pipeline(entities, mentions, pericopes)
    again = _pipeline(dict(reversed(list(entities.items()))), mentions[::-1], pericopes)
    assert first == again
    lexicon, _, _, hits, stats, conflicts = first
    assert json.dumps([hits, stats, conflicts], ensure_ascii=False) == \
        json.dumps(list(again[3:]), ensure_ascii=False)
    assert lexicon == ["大衛王", "耶烏施", "以掃", "大衛", "希崙", "耶西", "雅蘭"]
    assert len(hits) == 3


def test_regression_fixture_without_guard():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    rows = _fixture_rows()
    assert len(rows) == 46
    expected = abstained = 0
    for row in rows:
        hits = _fixture_hits(row, NO_GUARD, _fixture_parents(row))
        got = sorted((h["head_id"], h["relation"], h["tail_id"], h["pattern"]) for h in hits)
        want = sorted(tuple(t[:4]) for t in row["expected"] + row["abstained"])
        assert got == want, row["case"]
        assert {(h["source_pericope_id"], h["verse"], h["evidence_span"]) for h in hits} <= \
            {(row["pericope_id"], row["verse"], row["text"][:200])}
        expected += len(row["expected"])
        abstained += len(row["abstained"])
    assert (expected, abstained) == (65, 13)


def test_regression_fixture_with_guard():
    rows = _fixture_rows()
    assert {tuple(row["homonym_ids"]) for row in rows} == {tuple(sorted(CFG.guard.homonym_ids))}
    expected = abstained = 0
    for row in rows:
        hits, stats, conflicts = _fixture_run(row, parent_map=_fixture_parents(row))
        assert [[h["head_id"], h["relation"], h["tail_id"], h["pattern"]] for h in hits] == row["expected"], \
            row["case"]
        got = [[c["head_id"], c["relation"], c["tail_id"], c["pattern"],
                c["reason"] + ("" if c["reason"] == "homonym" else ":" + ",".join(c["other_parents"]))]
               for c in conflicts]
        assert got == row["abstained"], row["case"]
        assert stats["emitted_hits"] == len(hits)
        assert stats["guard_other_parent"] + stats["guard_homonym"] == len(conflicts)
        expected += len(hits)
        abstained += len(conflicts)
    assert (expected, abstained) == (65, 13)


def test_stats_count_hits_by_pattern():
    _, stats, conflicts = _fixture_run(_fixture_row("named:gen:36:0:14"))
    by_pattern = {P1: 0, P2: 0, P3: 3, P4: 1}
    assert stats == {"pattern_hits": 4, "by_pattern": by_pattern, "guard_other_parent": 0,
                     "guard_homonym": 0, "emitted_hits": 4, "emitted_by_pattern": by_pattern,
                     "ambiguous_name": 0}
    assert conflicts == []

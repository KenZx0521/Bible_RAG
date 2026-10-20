"""GEN confirmation set: blinding word lists and the writer / fixer / auditor prompts (prereg §3.2, §3.3, §3.5).

Unit tests use a made-up chain (ids Z05.*, Z11.*) and made-up names, with stand-in cue words injected into
banned_g (the real ones are gencard.CUE_LITERALS, tested when gencard is importable). The K0 transcript test
runs experiment A's transcript rules in a subprocess with this experiment's word lists. Store tests render the 58
pool slots with the real chain and skip when the store is not mounted. Nothing calls Ollama or any LLM.
"""

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

H = Path(__file__).resolve().parents[1] / "experiments" / "2026-10-20_gen_confirm"
if str(H) not in sys.path:
    sys.path.insert(0, str(H))

import banned_g as B  # noqa: E402
import g_common as GC  # noqa: E402
import prompts_g as P  # noqa: E402

needs_store = pytest.mark.skipif(not GC.POOL.is_file(), reason=f"store not mounted ({GC.POOL})")
TEXT_UNITS = GC.STAGE0_OUT.parents[1] / "layers/text/text@247eafe44b02/verse_units.jsonl"
HO_A = GC.REPO / "evaluation/experiments/2026-10-18_kg_cards/A/confirm/ho_a"
HO_TOOLS = GC.REPO / "evaluation/experiments/2026-10-14_graph_gd/ho_tools"
STAND_IN_CUES = ("出生", "去世", "幾歲", "多少年", "是否", "嗎")

# ---------------------------------------------------------------- synthetic chain, pool rows and drafts
CHAIN = (("Z05.00", "柯梅", 5), ("Z05.01", "柏羅丹", 5), ("Z05.02", "茵德", 5), ("Z05.03", "瓦勒", 5),
         ("Z05.04", "梅洛撒蒂", 5), ("Z05.05", "賽琳", 5), ("Z05.06", "洛珊", 5),
         ("Z11.00", "雷", 11), ("Z11.01", "歐芙", 11), ("Z11.02", "葛林", 11), ("Z11.03", "蘇倫", 11))
# 計 and 瑟 are the made-up one-character names (計 sits inside common words: 合計, 總計)
EXTRA = ("卡斯", "茉妮", "多芮", "計", "撒蒂", "弗朗", "瑟")


def names_doc(**over) -> dict:
    doc = {"schema": "gen_confirm.gen_names.v1", "text_digest": "0" * 64, "gen_layer_sha256": "0" * 64,
           "chain": [{"id": i, "name": n, "chapter": c} for i, n, c in CHAIN],
           "cain_line": ["卡斯", "茉妮"], "abram_family": ["計", "多芮"], "extra_persons": sorted(EXTRA),
           "other_books": ["路加", "路加福音"], "lexicon_blockers": ["瓦勒斯", "茵德城"], "sources": {}}
    doc.update(over)
    return doc


def fake_names() -> "P.Names":
    return P.Names.from_doc(names_doc())


def pool_row(qtype: str, x: str, y: str, marker: bool = False, sid: str = "S00", gold: int = 4321) -> dict:
    ids = [i for i, _, _ in CHAIN]
    by = {n: i for i, n, _ in CHAIN}
    a, b = ids.index(by[x]), ids.index(by[y])
    return dict(sid=sid, qtype=qtype, chapter=dict((i, c) for i, _, c in CHAIN)[by[x]], x=by[x], y=by[y],
                persons=ids[a:b + 1], marker_required=marker, gold=gold)


def draft(row: dict, question: str, qid: str = "Q01", value: int = 4321, unit: str = "歲",
          marker: str | None = None, slot_id: str | None = None) -> dict:
    names = dict((i, n) for i, n, _ in CHAIN)
    return {"id": qid, "slot": slot_id or qid, "qtype": P.QTYPE[row["qtype"]], "X": names[row["x"]],
            "Y": names[row["y"]], "marker": marker, "question": question, "answer": {"value": value, "unit": unit},
            "steps": [{"person": names[p], "fact": f"{qid} fact {k} on {names[p]}", "verse": f"gen.5.{k + 3}"}
                      for k, p in enumerate(row["persons"])],
            "convention": "", "notes": "nothing to add"}


ROW_F1 = pool_row("F1", "柯梅", "茵德", sid="S00")
ROW_F5 = pool_row("F5", "柏羅丹", "梅洛撒蒂", sid="S01")
ROW_MK = pool_row("F1", "瓦勒", "賽琳", marker=True, sid="S02")
ROW_11 = pool_row("F5", "雷", "葛林", sid="S03")
Q_F1 = "依創世記的記載，茵德出生那一年，柯梅幾歲？"
Q_F5 = "照創世記所記，柏羅丹去世的時候，梅洛撒蒂多大？"
Q_MK = "按創世記，瓦勒幾歲時洛珊的父親賽琳出生？"
Q_11 = "創世記記載雷去世那年，葛林的年紀是？"


def schema_errors(obj, schema: dict, path: str = "$") -> list[str]:
    """The JSON-schema subset the output schemas use (type, enum, properties, required, items, min/maxItems, anyOf)."""
    if "anyOf" in schema:
        return [] if any(not schema_errors(obj, s, path) for s in schema["anyOf"]) else [f"{path}: anyOf"]
    types = {"object": dict, "array": list, "string": str, "integer": int, "null": type(None)}
    t = schema.get("type")
    if t and (not isinstance(obj, types[t]) or (t == "integer" and isinstance(obj, bool))):
        return [f"{path}: not {t}"]
    errs = [f"{path}: not in enum"] if "enum" in schema and obj not in schema["enum"] else []
    if t == "object":
        errs += [f"{path}.{k}: missing" for k in schema.get("required", ()) if k not in obj]
        for k, s in schema.get("properties", {}).items():
            if k in obj:
                errs += schema_errors(obj[k], s, f"{path}.{k}")
    if t == "array":
        if len(obj) < schema.get("minItems", 0) or len(obj) > schema.get("maxItems", len(obj)):
            errs.append(f"{path}: length")
        for i, x in enumerate(obj):
            errs += schema_errors(x, schema.get("items", {}), f"{path}[{i}]")
    return errs


@pytest.fixture(autouse=True)
def stand_in_cues():
    with B.override_cue_literals(STAND_IN_CUES):
        yield


def _subprocess(code: str) -> str:
    return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
                          cwd=str(GC.REPO / "evaluation")).stdout


# ---------------------------------------------------------------- §3.3 lists
def test_memory_markers_hold_ho_a_and_this_experiments_names():
    for t in (*B.HO.MEMORY_MARKERS, *B.A_MEMORY_MARKERS):
        assert t in B.MEMORY_MARKERS
    for t in ("gen_confirm", "gencard", "gen_layer", "gen_names", "g_common", "x_common", "arith_stage0", "power_g",
              "pool_g", "order_g", "mech_g", "run_g", "analyze_g", "gen_g", "audit_g", "regnal_qset"):
        assert t in B.MEMORY_MARKERS, t


def test_banned_terms_are_ho_plus_a_leak_plus_project_words():
    for t in (*B.HO.BANNED_TERMS, *B.A_LEAK_TERMS, "T-rows", "G-ref", "B0", "rule seed", "gencard"):
        assert t in B.BANNED_TERMS, t
    assert "算術" not in B.BANNED_TERMS and "觸發" not in B.BANNED_TERMS


def test_prompt_terms_add_the_five_words_and_the_cue_literals():
    terms = B.PROMPT_TERMS
    for t in (*B.HO.PROMPT_TERMS, *B.A_PROMPT_TERMS, "算術", "觸發", "規則種子", "年歲卡", "推導卡", *STAND_IN_CUES):
        assert t in terms, t
    with B.override_cue_literals(("某線索",)):
        assert "某線索" in B.PROMPT_TERMS and "出生" not in B.PROMPT_TERMS


def test_bare_gen_f1_f5_and_arith_are_not_banned():
    every = (*B.PROMPT_TERMS, *B.BANNED_TERMS, *B.MEMORY_MARKERS)
    for t in ("GEN", "F1", "F5", "arith"):
        assert t not in every
    text = "GEN F1 F5 arithmetic bt v gen.5.3 bt grep 'x' gen key gen.11.10"
    assert B.find_terms(text, every) == []


def test_ascii_terms_match_on_word_boundaries_only():
    assert sorted(h.term for h in B.transcript_hits("the B0 arm and gencard")) == ["B0", "gencard"]
    assert B.transcript_hits("AB0 B01 gencards xgencard") == []


def test_a_lists_equal_banned_a_at_run_time_and_no_ho_a_module_is_loaded():
    code = (f"import importlib.util, json, sys; sys.path.insert(0, {str(H)!r});"
            f"spec = importlib.util.spec_from_file_location('banned_a_probe', {str(HO_A / 'banned_a.py')!r});"
            "m = importlib.util.module_from_spec(spec); sys.modules['banned_a_probe'] = m; spec.loader.exec_module(m);"
            "print(json.dumps([m.PROMPT_TERMS, m.BANNED_TERMS, m.MEMORY_MARKERS], ensure_ascii=False))")
    a_prompt, a_banned, a_memory = json.loads(_subprocess(code))
    assert tuple(a_prompt) == B.A_LEVEL_PROMPT_TERMS and tuple(a_banned) == B.A_LEVEL_BANNED_TERMS
    assert tuple(a_memory) == B.A_LEVEL_MEMORY_MARKERS
    code = (f"import sys; sys.path.insert(0, {str(H)!r}); import banned_g, prompts_g, mech_g;"
            f"bad = [n for n, m in sys.modules.items() if getattr(m, '__file__', None) and "
            f"any(d in m.__file__ for d in ('/ho_a/', '/A/confirm/', '2026-10-19_regnal_qset'))];"
            "print(bad, 'gencard' in sys.modules, 'c_common' in sys.modules)")
    assert _subprocess(code).split() == ["[]", "False", "False"]


def test_pinned_sources_refuse_a_changed_file(tmp_path):
    copy = tmp_path / "banned_a.py"
    copy.write_text((HO_A / "banned_a.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="sha256"):
        B.literal_tuples(copy, B.A_BANNED_SHA256, ("A_LEAK_TERMS",))
    with pytest.raises(RuntimeError, match="missing"):
        B.literal_tuples(HO_A / "banned_a.py", B.A_BANNED_SHA256, ("NO_SUCH_NAME",))


def test_cue_literals_are_imported_lazily():
    code = f"import sys; sys.path.insert(0, {str(H)!r}); import banned_g; print('gencard' in sys.modules)"
    assert _subprocess(code).split() == ["False"]


# ---------------------------------------------------------------- the scope rule
def test_prompt_scope_is_the_full_check():
    for text, term in (("請寫出生年", "出生"), ("用算術", "算術"), ("觸發", "觸發"), ("see gencard", "gencard"),
                       ("the B0 arm", "B0"), ("a pilot run", "pilot"), ("Kay", "Kay")):
        assert term in {h.term for h in B.prompt_hits(text)}, term


def test_agent_scope_is_memory_markers_only():
    assert B.agent_hits("茵德出生那一年柯梅幾歲？是否用算術或觸發 B0") == []
    assert {h.term for h in B.agent_hits("from gen_names and Kay")} == {"gen_names", "Kay"}


def test_transcript_scope_is_banned_plus_memory():
    assert B.transcript_hits("出生 去世 幾歲 算術 觸發 推導 模板") == []
    assert {h.term for h in B.transcript_hits("T-rows G-ref rule seed x_common")} == {"T-rows", "G-ref", "rule seed",
                                                                                    "x_common"}


def test_require_raises_and_names_the_terms():
    with pytest.raises(B.BlindingError, match="出生"):
        B.require("請寫出生年", "here")
    assert B.require("茵德出生", "q", "agent") == "茵德出生"
    with pytest.raises(ValueError):
        B.require("x", "q", "nowhere")


# ---------------------------------------------------------------- names and slots
def test_names_from_doc_and_its_lookups():
    n = fake_names()
    assert n.person("Z05.02").name == "茵德" and n.id_of("茵德") == "Z05.02" and n.id_of("無名") is None
    assert n.father("Z05.02").name == "柏羅丹" and n.father("Z05.00") is None
    assert n.son("Z05.05").name == "洛珊" and n.son("Z05.06") is None and n.son("Z11.03") is None
    assert [p.name for p in n.path("Z05.01", "Z05.04")] == ["柏羅丹", "茵德", "瓦勒", "梅洛撒蒂"]
    assert "撒蒂" in n.known and "柯梅" in n.known and "瓦勒斯" not in n.known


@pytest.mark.parametrize("over, match", [({"schema": "other"}, "schema"), ({"chain": []}, "chain"),
                                         ({"chain": [{"id": "Z05.00", "name": "柯梅", "chapter": 5}] * 2}, "unique"),
                                         ({"extra_persons": "計"}, "extra_persons")])
def test_names_from_doc_refuses_bad_docs(over, match):
    with pytest.raises(P.PromptError, match=match):
        P.Names.from_doc(names_doc(**over))
    doc = names_doc()
    del doc["lexicon_blockers"]
    with pytest.raises(P.PromptError, match="lexicon_blockers"):
        P.Names.from_doc(doc)


def test_slot_spec_of_a_plain_slot():
    s = P.slot_spec(ROW_F1, fake_names(), "Q01")
    assert (s.qtype, s.x, s.y, s.chapter, s.path, s.marker, s.slot_id) == (
        "age_at_birth", "柯梅", "茵德", 5, ("柯梅", "柏羅丹", "茵德"), None, "Q01")
    assert s.definition == "柯梅's age, in years, in the year 茵德 was born, according to Genesis."
    assert s.scope == "Genesis 5"
    t = P.slot_spec(ROW_F5, fake_names(), "Q02a1", slot_id="Q02")
    assert t.definition == "梅洛撒蒂's age, in years, in the year 柏羅丹 died, according to Genesis."
    assert (t.qid, t.slot_id) == ("Q02a1", "Q02")


def test_marker_is_y_chain_son_else_x_chain_father():
    s = P.slot_spec(ROW_MK, fake_names(), "Q03")
    assert (s.marker, s.marker_person, s.marker_end) == ("洛珊的父親賽琳", "洛珊", "Y")
    assert "洛珊" not in s.path
    last = pool_row("F5", "瓦勒", "洛珊", marker=True)
    t = P.slot_spec(last, fake_names(), "Q04")
    assert (t.marker, t.marker_person, t.marker_end) == ("茵德的兒子瓦勒", "茵德", "X")
    doc = names_doc(chain=[{"id": "Z05.00", "name": "柯梅", "chapter": 5}, {"id": "Z05.01", "name": "柏羅丹", "chapter": 5},
                           {"id": "Z05.02", "name": "茵德", "chapter": 5}])
    row = dict(sid="S09", qtype="F1", chapter=5, x="Z05.00", y="Z05.02", persons=["Z05.00", "Z05.01", "Z05.02"],
               marker_required=True)
    with pytest.raises(P.PromptError, match="marker"):
        P.slot_spec(row, P.Names.from_doc(doc), "Q05")


@pytest.mark.parametrize("change, match", [({"x": "Z05.03", "y": "Z05.01"}, "ancestor"), ({"chapter": 11}, "chapter"),
                                           ({"persons": ["Z05.00", "Z05.02"]}, "persons"), ({"qtype": "F3"}, "qtype"),
                                           ({"y": "Z05.01", "persons": ["Z05.00", "Z05.01"]}, "two generations"),
                                           ({"y": "Z11.02"}, "chapter")])
def test_slot_spec_refuses_bad_rows(change, match):
    with pytest.raises(P.PromptError, match=match):
        P.slot_spec({**ROW_F1, **change}, fake_names(), "Q01")


@pytest.mark.parametrize("qid", ["01", "Q1", "S00", "Q01 ", "Q01;x"])
def test_slot_spec_refuses_bad_ids(qid):
    with pytest.raises(P.PromptError, match="id"):
        P.slot_spec(ROW_F1, fake_names(), qid)


# ---------------------------------------------------------------- templates and schemas
def test_prompt_files_load_with_their_sections_and_pass_the_full_check():
    gen, audit = P.default_prompts()
    assert set(gen.sections) == {"system", "task_new", "task_fix"} and set(audit.sections) == {"system", "task_audit"}
    for pf in (gen, audit):
        text = pf.path.read_text(encoding="utf-8")
        assert B.prompt_hits(text) == [], pf.path.name
        bare = re.sub(r"(?m)^[0-9]+\. ", "", text.replace("gen.24.29-30", ""))
        assert not re.search(r"[0-9]{2,}", bare), "numbers in a template"


def test_templates_hold_no_stage0_wording_or_cue_words():
    s0 = (GC.STAGE0_DIR / "items_x.py").read_text(encoding="utf-8")
    templates = re.findall(r'Q_F[0-9] = "([^"]+)"', s0)
    assert templates
    for pf in P.default_prompts():
        text = pf.path.read_text(encoding="utf-8")
        for t in templates:
            assert t.split("{")[0] not in text
        assert not re.search(r"F[135]\b|GEN\b", text)


def test_schemas_pass_the_full_check_and_list_the_prereg_fields():
    P.check_schemas()
    assert P.ITEM_KEYS == ("id", "slot", "qtype", "X", "Y", "marker", "question", "answer", "steps", "convention",
                           "notes")
    assert P.ITEM_SCHEMA["required"] == list(P.ITEM_KEYS)
    assert P.ITEM_SCHEMA["properties"]["qtype"]["enum"] == ["age_at_birth", "age_at_death"]
    assert P.ITEM_SCHEMA["properties"]["answer"]["required"] == ["value", "unit"]
    assert P.ITEM_SCHEMA["properties"]["steps"]["items"]["required"] == ["person", "fact", "verse"]
    fnd = P.AUDIT_SCHEMA["properties"]["findings"]["items"]
    assert fnd["properties"]["severity"]["enum"] == ["critical", "major", "minor"]
    assert "value" in P.AUDIT_SCHEMA["required"]
    good = {"status": "drafted", "reason": "", "item": draft(ROW_F1, Q_F1)}
    assert schema_errors(good, P.GEN_SCHEMA) == []
    assert schema_errors({**good, "item": {**good["item"], "qtype": "F1"}}, P.GEN_SCHEMA)
    empty = {"id": "Q01", "value": None, "reading": "", "findings": [], "checked": ""}
    assert schema_errors(empty, P.AUDIT_SCHEMA) == []


# ---------------------------------------------------------------- rendering
def test_writer_prompt_of_a_plain_slot():
    r = P.render_writer(ROW_F1, fake_names(), "Q01")
    assert r.kind == "draft" and r.schema == P.GEN_SCHEMA and r.system == P.default_prompts()[0].sections["system"]
    for want in ("Q01", "age_at_birth", "柯梅's age, in years, in the year 茵德 was born, according to Genesis.",
                 "X = 柯梅", "Y = 茵德", "Genesis 5", "X is an ancestor of Y",
                 "name exactly 柯梅 and 茵德 and no other person"):
        assert want in r.user, want
    assert "的父親" not in r.user and "的兒子" not in r.user
    assert "4321" not in r.user + r.system and "Z05." not in r.user and "S00" not in r.user


def test_writer_prompt_of_a_marker_slot_shows_only_the_computed_marker():
    r = P.render_writer(ROW_MK, fake_names(), "Q03")
    assert r.user.count("洛珊的父親賽琳") == 1 and "name exactly" not in r.user and "no other person" in r.user
    assert "茵德的兒子瓦勒" not in r.user


def test_writer_prompt_of_chapter_eleven_and_years():
    r = P.render_writer(ROW_11, fake_names(), "Q04")
    assert "Genesis 11" in r.user and "葛林's age, in years, in the year 雷 died, according to Genesis." in r.user


def test_audit_prompt_holds_only_the_question_and_the_definition():
    item = draft(ROW_MK, Q_MK, value=8642, marker="洛珊的父親賽琳")
    item["notes"] = "writer note seen by nobody else"
    item["convention"] = "writer convention line"
    r = P.render_audit(item["question"], ROW_MK, "Q03", fake_names())
    assert r.kind == "audit" and r.schema == P.AUDIT_SCHEMA
    assert Q_MK in r.user and "瓦勒's age, in years, in the year 賽琳 was born, according to Genesis." in r.user
    every = r.system + r.user
    assert "8642" not in every and "writer note" not in every and "writer convention" not in every
    for st in item["steps"]:
        assert st["fact"] not in every and st["verse"] not in every
    assert "Genesis 5" not in every and "ancestor of Y" not in every and "Q03" in r.user
    assert "unambiguous by construction" in r.system and "namesake" in r.system


def test_audit_definition_of_a_marker_slot_says_which_namesake_is_meant():
    names = fake_names()
    r = P.render_audit(Q_MK, ROW_MK, "Q03", names)
    assert ("瓦勒's age, in years, in the year 賽琳 was born, according to Genesis. Here 賽琳 means the father of 洛珊."
            in r.user)
    last = pool_row("F5", "瓦勒", "洛珊", marker=True)
    t = P.render_audit("照創世記，茵德的兒子瓦勒去世時洛珊多大？", last, "Q04", names)
    assert "in the year 瓦勒 died, according to Genesis. Here 瓦勒 means the son of 茵德." in t.user
    assert "means the" not in P.render_audit(Q_F1, ROW_F1, "Q01", names).user
    assert P.slot_spec(ROW_F1, names, "Q01").identity == ""
    assert "means the" not in P.render_writer(ROW_MK, names, "Q03").user


def test_prompt_rules_keep_numerals_out_of_conventions_and_values_out_of_findings():
    gen, audit = P.default_prompts()
    g, a = gen.sections["system"], audit.sections["system"]
    assert "say in words, without any numeral" in g                    # rule 9 (prereg §3.4 v_number)
    assert "only where point 2 says the question needs one" in a       # rule 3 (mech marker_rule)
    assert "Otherwise the question names only the two people" in a
    assert "Keep your value and every number you computed out of findings and suggested_fix" in a   # §3.6 hint
    assert "a suggested fix says the counting way in words, without numerals" in a


def test_render_audit_refuses_anything_but_a_question_string():
    for bad in (draft(ROW_F1, Q_F1), "", None, ["q"]):
        with pytest.raises(P.PromptError):
            P.render_audit(bad, ROW_F1, "Q01", fake_names())


def test_audit_prompt_with_age_and_event_words_in_the_question_passes():
    q = "依創世記，柯梅幾歲的時候茵德出生？是否有記載？"
    assert B.prompt_hits(q)                          # the question itself would fail the full check
    r = P.render_audit(q, ROW_F1, "Q01", fake_names())
    assert q in r.user


def test_agent_text_with_a_memory_marker_is_refused():
    with pytest.raises(B.BlindingError, match="gencard"):
        P.render_audit("依創世記 gencard 柯梅幾歲？", ROW_F1, "Q01", fake_names())
    item = draft(ROW_F1, Q_F1)
    with pytest.raises(B.BlindingError, match="Kay"):
        P.render_kay_revise(ROW_F1, fake_names(), "Q01", item, "Kay wants a shorter question")
    with pytest.raises(B.BlindingError, match="x_common"):
        P.render_fix("audit", ROW_F1, fake_names(), "Q01", {**item, "notes": "see x_common"},
                     (P.Issue.tool("make it shorter"),))


def test_tool_values_get_the_full_check():
    doc = names_doc(chain=[{"id": i, "name": ("柯出生" if n == "柯梅" else n), "chapter": c} for i, n, c in CHAIN])
    with pytest.raises(B.BlindingError, match="出生"):
        P.render_writer({**ROW_F1}, P.Names.from_doc(doc), "Q01")
    with pytest.raises(B.BlindingError, match="出生"):
        P.render_fix("mech", ROW_F1, fake_names(), "Q01", draft(ROW_F1, Q_F1), (P.Issue.tool("the 出生 rule"),))


def test_fix_prompt_carries_tool_and_agent_parts_and_never_names_the_source():
    item = draft(ROW_F1, Q_F1)
    issues = (P.Issue.of(("tool", "the question contains a numeral: "), ("agent", "幾歲出生")),
              P.Issue.tool(P.GOLD_MISMATCH_HINT), P.Issue.agent("審題者：措辭可以更口語"))
    r = P.render_fix("audit", ROW_F1, fake_names(), "Q01", item, issues)
    assert r.kind == "fix" and r.source == "audit" and r.schema == P.GEN_SCHEMA
    assert "- the question contains a numeral: 幾歲出生" in r.user and P.GOLD_MISMATCH_HINT in r.user
    assert "與依所引經節的獨立重算不一致" in P.GOLD_MISMATCH_HINT
    assert P.item_json(item) in r.user and "name exactly 柯梅 and 茵德 and no other person" in r.user
    for word in ("audit", "mech", "kay", "Kay", "auditor"):
        assert word not in r.user.replace("audit_", ""), word
    with pytest.raises(P.PromptError, match="source"):
        P.render_fix("gold", ROW_F1, fake_names(), "Q01", item, issues)
    with pytest.raises(P.PromptError, match="issue"):
        P.render_fix("mech", ROW_F1, fake_names(), "Q01", item, ())


def test_kay_revise_is_a_fix_from_source_kay():
    item = draft(ROW_F1, Q_F1)
    r = P.render_kay_revise(ROW_F1, fake_names(), "Q01", item, "請把問句改得更像讀者會問的樣子")
    assert r.source == "kay" and "請把問句改得更像讀者會問的樣子" in r.user and r.kind == "fix"


def test_item_json_shows_the_item_keys_only():
    item = {**draft(ROW_F1, Q_F1), "hidden_gold": 4321, "mech": ["x"]}
    shown = json.loads(P.item_json(item))
    assert list(shown) == list(P.ITEM_KEYS)


def test_no_prompt_contains_another_slots_question_or_answer():
    names = fake_names()
    a, b = draft(ROW_F1, Q_F1, value=1357), draft(ROW_F5, Q_F5, qid="Q02", value=2468)
    prompts = [P.render_writer(ROW_F1, names, "Q01"), P.render_audit(a["question"], ROW_F1, "Q01", names),
               P.render_fix("mech", ROW_F1, names, "Q01", a, (P.Issue.tool("make it shorter"),)),
               P.render_kay_revise(ROW_F1, names, "Q01", a, "請改短一點")]
    for r in prompts:
        text = r.system + r.user + json.dumps(r.schema, ensure_ascii=False)
        assert Q_F5 not in text and "2468" not in text and "梅洛撒蒂" not in text
        for st in b["steps"]:
            assert st["fact"] not in text


def test_every_synthetic_render_passes_the_full_check_on_its_tool_parts():
    names = fake_names()
    for row, q in ((ROW_F1, Q_F1), (ROW_F5, Q_F5), (ROW_MK, Q_MK), (ROW_11, Q_11)):
        r = P.render_writer(row, names, "Q09")
        assert B.prompt_hits(r.system) == [] and B.prompt_hits(r.user) == []
        assert B.prompt_hits(json.dumps(r.schema, ensure_ascii=False)) == []
        assert B.agent_hits(P.render_audit(q, row, "Q09", names).user) == []


# ---------------------------------------------------------------- K0: a compliant transcript (prereg §3.3)
def _compliant_run(tmp_path: Path) -> tuple[Path, dict]:
    names = fake_names()
    r = P.render_writer(ROW_F1, names, "Q01")
    item = draft(ROW_F1, Q_F1)
    out = {"status": "drafted", "reason": "", "item": item}
    events = [
        {"type": "system", "subtype": "init", "cwd": "/srv", "model": "claude-opus-5-5",
         "tools": ["Bash", "StructuredOutput"], "mcp_servers": [], "permissionMode": "dontAsk"},
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "Read the begetting lines for the two people first."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "bt v gen.5.3-gen.5.8"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "gen.5.3 柯梅記事一\ngen.5.6 柏羅丹記事二"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "bt grep '茵德' gen"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "gen.5.9 茵德記事三"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "The sum is checked against both lines."},
            {"type": "tool_use", "id": "t3", "name": "StructuredOutput", "input": out}]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "done", "structured_output": out}]
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"events": events, "prompts": {"system": r.system, "user": r.user}},
                               ensure_ascii=False), encoding="utf-8")
    return path, out


def test_k0_compliant_transcript_passes_every_blinding_rule(tmp_path):
    import mech_g as M
    path, out = _compliant_run(tmp_path)
    assert schema_errors(out, P.GEN_SCHEMA) == []
    assert M.check_gen_output(out) == []
    assert M.check_draft(out["item"], P.slot_spec(ROW_F1, fake_names(), "Q01"), fake_names()) == []
    code = (f"import json, sys; from pathlib import Path; sys.path.insert(0, {str(HO_A)!r});"
            "import transcript_a as TR; sys.path.insert(0, " + repr(str(H)) + "); import banned_g;"
            "TR.banned_a = banned_g;"
            f"doc = json.loads(Path({str(path)!r}).read_text(encoding='utf-8'));"
            "v = TR.check_events(doc['events'], doc['prompts'], Path('/srv'), 'claude-opus-5-5');"
            "print(json.dumps(sorted({x.rule for x in v if x.level == 'error'}), ensure_ascii=False),"
            " json.dumps(sorted(TR.BLINDING_RULES)))")
    errors, rules = _subprocess(code).split(" ", 1)
    assert json.loads(errors) == [] and json.loads(rules) == ["t_banned", "t_init", "t_memory", "t_path", "t_tool"]


def test_k0_a_leaking_transcript_fails(tmp_path):
    path, _ = _compliant_run(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["events"][1]["message"]["content"][0]["thinking"] = "Compare with the T-rows arm from gen_layer."
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    code = (f"import json, sys; from pathlib import Path; sys.path.insert(0, {str(HO_A)!r});"
            "import transcript_a as TR; sys.path.insert(0, " + repr(str(H)) + "); import banned_g;"
            "TR.banned_a = banned_g;"
            f"doc = json.loads(Path({str(path)!r}).read_text(encoding='utf-8'));"
            "v = TR.check_events(doc['events'], doc['prompts'], Path('/srv'), 'claude-opus-5-5');"
            "print(json.dumps(sorted({(x.rule, x.level) for x in v}), ensure_ascii=False))")
    found = {tuple(x) for x in json.loads(_subprocess(code))}
    assert ("t_memory", "error") in found and ("t_banned_agent", "warn") in found


def test_bt_commands_of_the_compliant_transcript_pass_the_pinned_guard(tmp_path):
    spec = importlib.util.spec_from_file_location("bt_guard_for_gen_test", HO_TOOLS / "bt_guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    pinned = "a81cba6e153bdb39b8c1a3f10cb1ccccf7ac66dd2b46db587b713a45fd1835ab"
    assert GC.sha256_file(HO_TOOLS / "bt_guard.py") == pinned
    path, _ = _compliant_run(tmp_path)
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    cmds = [c["input"]["command"] for e in events if e["type"] == "assistant" for c in e["message"]["content"]
            if c.get("type") == "tool_use" and c["name"] == "Bash"]
    assert len(cmds) == 2 and all(guard.check_command(c) is None for c in cmds)


# ---------------------------------------------------------------- with the real cue words (gencard)
def _gencard_cues():
    try:
        with B.override_cue_literals(None):
            return B.cue_literals()
    except (ImportError, RuntimeError) as err:
        pytest.skip(f"gencard not importable yet: {err}")


def test_real_cue_literals_keep_every_synthetic_render_clean():
    cues = _gencard_cues()
    assert cues and all(isinstance(c, str) and c for c in cues)
    with B.override_cue_literals(cues):
        names = fake_names()
        for pf in P.default_prompts():
            assert B.prompt_hits(pf.path.read_text(encoding="utf-8")) == []
        P.check_schemas()
        for row, q in ((ROW_F1, Q_F1), (ROW_F5, Q_F5), (ROW_MK, Q_MK), (ROW_11, Q_11)):
            P.render_writer(row, names, "Q09")
            P.render_audit("依創世記，柯梅幾歲時茵德出生？" + "、".join(cues) + "？", row, "Q09", names)
            P.render_fix("audit", row, names, "Q09", draft(row, q), (P.Issue.tool(P.GOLD_MISMATCH_HINT),
                                                                    P.Issue.tool(P.AMBIGUITY_HINT)))


# ---------------------------------------------------------------- store: the 58 pool slots with real names
def _chain_doc_from_layer() -> dict:
    gl = GC.read_json(GC.GEN_LAYER)
    nodes = sorted(gl["nodes"], key=lambda n: (n["chapter"], n["order"]))
    return names_doc(chain=[{"id": n["id"], "name": n["name"], "chapter": n["chapter"]} for n in nodes],
                     cain_line=[], abram_family=[], extra_persons=[], other_books=[], lexicon_blockers=[])


def _check_58(names: "P.Names") -> None:
    pool = GC.read_json(GC.POOL)["pool"]
    assert len(pool) == 58
    markers = []
    for k, row in enumerate(pool):
        r = P.render_writer(row, names, f"Q{k + 1:02d}")
        spec = P.slot_spec(row, names, f"Q{k + 1:02d}")
        text = r.system + r.user
        assert B.prompt_hits(text) == [] and B.prompt_hits(json.dumps(r.schema, ensure_ascii=False)) == []
        assert not re.search(rf"(?<![0-9]){row['gold']}(?![0-9])", text.replace(f"Q{k + 1:02d}", ""))
        assert row["x"] not in text and row["y"] not in text and row["sid"] not in r.user
        assert (spec.marker is not None) == row["marker_required"]
        if spec.marker:
            markers.append(spec)
            assert spec.marker_end == "Y" and spec.marker_person not in spec.path and r.user.count(spec.marker) == 1
        else:
            assert f"name exactly {spec.x} and {spec.y} and no other person" in r.user
        a = P.render_audit(f"依創世記，{spec.y}和{spec.x}？", row, spec.qid, names)   # tool parts get the full check
        assert ("means the father of" in a.user) == bool(spec.marker) and "means the son of" not in a.user
    assert len(markers) == 6


@needs_store
def test_58_pool_slots_render_writer_prompts_with_the_layer_chain():
    _check_58(P.Names.from_doc(_chain_doc_from_layer()))


def real_names() -> "P.Names":
    """Store gen_names.json; before names_g has written it, names_g.build() (read-only, nothing written)."""
    if GC.GEN_NAMES.is_file():
        return P.load_names()
    try:
        import names_g
        return P.Names.from_doc(names_g.build())
    except (ImportError, OSError) as err:
        pytest.skip(f"gen_names.json missing and names_g.build() unavailable: {err}")


@needs_store
def test_58_pool_slots_render_writer_prompts_with_gen_names():
    names = real_names()
    assert [p.id for p in names.chain] == [c["id"] for c in _chain_doc_from_layer()["chain"]]
    _check_58(names)
    with B.override_cue_literals(_gencard_cues()):
        _check_58(names)


@needs_store
def test_58_writer_prompts_pass_with_the_real_cue_words():
    cues = _gencard_cues()
    with B.override_cue_literals(cues):
        _check_58(P.Names.from_doc(_chain_doc_from_layer()))


@pytest.mark.skipif(not TEXT_UNITS.is_file(), reason="text layer not mounted")
def test_banned_and_memory_terms_never_occur_in_the_text_layer():
    texts = [json.loads(ln)["text"] for ln in TEXT_UNITS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(texts) > 30000
    hits = [h.term for t in texts for h in B.transcript_hits(t)]
    assert hits == []


@pytest.mark.skipif(not TEXT_UNITS.is_file(), reason="text layer not mounted")
def test_no_test_string_or_template_shares_an_8_character_window_with_the_text_layer():
    texts = [json.loads(ln)["text"] for ln in TEXT_UNITS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    windows = {t[i:i + 8] for t in texts for i in range(len(t) - 7)}
    mine = [Path(__file__), Path(__file__).with_name("test_gen_confirm_mech.py"), H / "mech_g.py", H / "prompts_g.py",
            H / "banned_g.py"]
    assert all(p.is_file() for p in mine)
    strings = [n.value for p in mine for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    strings += [pf.path.read_text(encoding="utf-8") for pf in P.default_prompts()]
    shared = [s for s in strings for i in range(len(s) - 7) if s[i:i + 8] in windows]
    assert len(strings) > 50 and shared == []

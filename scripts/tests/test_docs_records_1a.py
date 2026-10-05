"""Batch 1A (W1) pins of the mechanism docs and the planning records.

docs/ARCHITECTURE.md and docs/kg_construction_overview.md describe the 1A
relation pipeline: Step 6 without R2 (R5 opt-in) feeds the offline Step 6.05,
whose relations_clean.jsonl is all that 6.1 imports; edges carry source,
run_id, pp_version and confidence_raw instead of confidence; 10.3 is legacy
only. Their 6.05 drop lists include the LLM row that contradicts a prior, and
the overview's 從零 line keeps build_database's Step 0 gates and closing
registry check and says what 8a, 8b and 10.6 are. The batch-0 record and its
allowlist name the real SON_OF cause (stale properties of an older
onCreate-only import, REL-10) and call the 流珥 alias an ID-2 error. The
batch-1 plan's 1A cells carry the W1 recomputation, every number read from
w1_1A/sim2_final.json, §2.1 adds created_from to batch 0's MENTIONS property
residual in a dated note, and §9 records the 2026-10-05 decisions. The kg_fix
README names the archived scripts that need a32fbea.
"""
from __future__ import annotations

import json
import re

import yaml

from test_docs_alignment import ROOT, read, section

ARCH = ROOT / "docs" / "ARCHITECTURE.md"
OVERVIEW = ROOT / "docs" / "kg_construction_overview.md"
RECORDS = ROOT / "docs" / "records"
BATCH0 = RECORDS / "2026-10-04_kg_batch0_results.md"
ALLOW0 = ROOT / "config" / "kg_diff_allow_batch0.yaml"
PLAN1 = RECORDS / "2026-10-04_kg_batch1_plan.md"
KGFIX = RECORDS / "2026-10-04_kg_fix"
SIM2 = json.loads(read(KGFIX / "batch1" / "w1_1A" / "sim2_final.json"))
W1 = "【驗・W1 重算】"
KIN = ("FATHER_OF", "SON_OF", "DAUGHTER_OF", "SPOUSE_OF", "MOTHER_OF", "ANCESTOR_OF", "DESCENDANT_OF",
       "SIBLING_OF")
LIUER_PROBES = ("kin-jethro-not-son-of-esau", "kin-nahath-not-son-of-jethro")


def _n(value: int) -> str:
    return f"{value:,}"


def _line(text: str, prefix: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(prefix))


def _mermaid(text: str) -> str:
    return re.search(r"```mermaid\n(.*?)```", text, re.S)[1]


# ---------------------------------------------------------------- mechanism docs

def test_architecture_flow_imports_relations_clean_from_6_05():
    flow = _mermaid(section(read(ARCH), "3. 離線建庫管線"))
    clean = re.search(r'(\w+)\["output/relations_clean\.jsonl', flow)
    assert clean and "relation_postprocess.py" in flow, flow
    assert _line(flow.replace("    ", ""), f"{clean[1]} --> ").count("import_relations_neo4j.py") == 1, flow


def test_architecture_step6_has_no_r2_and_6_05_numbers_match_the_simulation():
    s35 = section(read(ARCH), "3.5 ")
    assert not re.search(r'\bR2\["', s35) and "--inverse" in s35, s35
    assert "prompt_signals" not in _line(s35, "**37 種關係本體**")
    assert "僅規則" not in s35
    for needle in ("Step 6.05", "relations_clean.jsonl", _n(SIM2["log"]["output"]), _n(SIM2["after_10_2"])):
        assert needle in s35, needle


def test_architecture_edges_carry_provenance_not_confidence():
    arch = read(ARCH)
    rows = (_line(section(arch, "3.7 "), "| `import_relations_neo4j.py`"), _line(arch, "- 關係抽取事實邊"))
    for row in rows:
        carried = re.search(r"邊帶 ([^,，;；]+)", row)[1]
        assert "`confidence`" not in carried and "confidence_raw" in carried and "不再寫" in row, row
        for field in ("source", "run_id", "pp_version", "evidence_span", "source_pericope_id"):
            assert field in row, (field, row)
    assert "relations_clean" in rows[0], rows[0]


def test_overview_runs_6_05_and_keeps_10_3_legacy_only():
    ov = read(OVERVIEW)
    assert 'r2["' not in ov and "--> r2" not in ov
    assert "共現關係搶救" not in _line(ov, '    curated["Step 10'), "mermaid still replays 10.3"
    edges = _line(ov, "三資料庫分工")
    assert "confidence_raw" in edges and "事實邊帶 confidence /" not in edges, edges
    step6 = section(ov, "Step 6–6.1")
    assert "regex 觸發訊號" not in step6 and "6,958 條進圖" not in step6, step6
    for needle in ("6.05", "relations_clean", _n(SIM2["log"]["output"]), _n(SIM2["after_10_2"])):
        assert needle in step6, needle
    step10 = section(ov, "Step 10 ·")
    for needle in ("--legacy-cooccurrence", "退出預設鏈", "6 → 6.05 → 6.1"):
        assert needle in step10, needle
    assert "10.2 先於 10.3" not in step10


def test_6_05_summaries_list_the_drop_that_contradicts_a_prior():
    # without it the listed drops do not reconcile with the 5,696 rows of relations_clean.jsonl
    ((relation, n),) = SIM2["drops"]["6_contradicts_prior_direction"].items()
    for doc, needle in ((ARCH, f"與 prior 方向相反的 {relation}({n})"), (OVERVIEW, f"與 prior 方向相反的 {relation} {n}")):
        assert needle in _line(read(doc), "- **Step 6.05 關係後處理**"), (doc.name, needle)


def test_overview_fresh_chain_keeps_the_step0_gates_and_the_registry_check():
    # build_database.md「執行順序」is the authority; a copied summary must not skip its mandatory checks
    fresh = _line(read(OVERVIEW), "> - 從零")
    steps = ("`process_bible.py`", "`check_step0.py`", "`validate_output.py`(必跑)", "→ 1 →", "6 → 6.05 → 6.1 → 8a",
             "→ 8b → 10.6 →", "`export_event_registry.py --check`", "最後才起 backend")
    at = [fresh.index(step) for step in steps]
    assert at == sorted(at), fresh
    for needle in ("8a 在", "8b 在", "10.6 是", "](build_database.md)「執行順序」"):
        assert needle in fresh, needle


# ---------------------------------------------------------------- batch-0 record

def test_batch0_record_names_the_stale_property_cause_and_the_liuer_alias_error():
    b0 = read(BATCH0)
    son_of = b0[b0.index("**SON_OF 差異的解釋**"):b0.index("## 環境現況")]
    for needle in ("REL-10", "onCreate-only", "0 個重複鍵", "phase 5", "0.891", "6.05", "SET"):
        assert needle in son_of, needle
    assert "最先匯入的那一份留下" not in b0 and "phase 歸屬不決定性" not in b0
    for part in (section(b0, "結論"), section(b0, "第 1 批之前")):
        liuer = [line for line in part.splitlines() if "流珥" in line]
        assert liuer and all("ID-2" in line and "C4" in line for line in liuer), liuer
        assert all(probe in part for probe in LIUER_PROBES), part
    assert "屬於第 1C 批的預期差異" not in b0 and "列為預期差異" not in b0


def test_batch0_allowlist_header_states_the_cause_and_the_entries_are_unchanged():
    text = read(ALLOW0)
    header = " ".join(line.lstrip("# ") for line in text.splitlines() if line.startswith("#"))
    assert "REL-10" in header and "one row per" in header, header
    assert "whichever row is imported first" not in header, header
    entries = [(e["section"], e["key"], e["delta"]) for e in yaml.safe_load(text)["allow"]]
    assert entries == [("ee_edges", "SON_OF phase=2 source=-", 1), ("ee_edges", "SON_OF phase=4 source=-", 3),
                       ("ee_edges", "SON_OF phase=5 source=-", -4)], entries


# ---------------------------------------------------------------- batch-1 plan

def _plan_1a_parts(plan: str) -> dict[str, str]:
    s01 = section(plan, "0.1 ")
    s6 = section(plan, "6. 與總計畫的偏離")
    return {"0.1": s01[s01.index("| W1·1A"):s01.index("| W1·1B")], "2.1": section(plan, "2.1 第 1A 批"),
            "6": "\n".join(line for line in s6.splitlines() if line.startswith(("| 1 |", "| 2 |")))}


def test_plan_1a_cells_are_recomputed_from_sim2_final():
    plan = read(PLAN1)
    parts = _plan_1a_parts(plan)
    assert not [name for name, part in parts.items() if "【待重算】" in part], parts
    assert W1 in plan[:plan.index("## 0.")] and "sim2_final.json" in plan[:plan.index("## 0.")]
    by_source, allpar, r6 = SIM2["after_10_2_by_source"], SIM2["allparent_after"], SIM2["r6_after_10_2"]
    children = f"{allpar['children_2plus_nonfemale_parents']}/{allpar['children']}"
    s01, s21 = parts["0.1"], parts["2.1"]
    expect = {
        _line(s01, "| | 語意邊總數"): [_n(SIM2["after_10_2"]), _n(by_source["prior"] + by_source["llm"]),
                                    _n(by_source["anchored_rule"])],
        _line(s01, "| | 親屬邊"): [_n(SIM2["after_10_2_kin"])],
        _line(s01, "| | 有 ≥2 個非女性父母"): [children],
        _line(s21, "| 錨定唯一鍵"): [_n(SIM2["log"]["anchored_unique"]), _n(SIM2["final_by_source"]["anchored_rule"])],
        _line(s21, "| R6 函數性"): [children, f"{r6['children_2plus_fathers']}/{r6['children']}",
                                 str(r6["functional_violation_rate"])],
        _line(s21, "- relationships"): [f"{rel} −{-SIM2['relationships_diff'][rel]:,}" for rel in KIN],
        _line(s21, "- ee_edges"): [f"anchored_rule {SIM2['ee_new_key_counts']['anchored_rule']} 鍵"
                                   f"（+{SIM2['ee_new_by_source']['anchored_rule']}）"],
        _line(parts["6"], "| 1 |"): [_n(SIM2["after_10_2_kin"])],
    }
    for row, needles in expect.items():
        assert W1 in row and all(needle in row for needle in needles), (needles, row)
    assert f"有 2 個以上父母的 {allpar['children_gt2_parents']} 個" in _line(s01, "| | 有 ≥2 個非女性父母")


def test_plan_1a_marks_the_pilot_and_the_h11_number():
    s21 = section(read(PLAN1), "2.1 第 1A 批")
    precision = _line(s21, "| 錨定精確率")
    for needle in ("≥0.91", "撤回", "試標", "非人工", "單一標註者", "20261005", "60/60", "51/60", "§9"):
        assert needle in precision, needle
    note = _line(s21, "> 註（H11")
    assert "H12" in note and "1D" in note and "C10" in note, note
    assert "§9" in _line(s21, "| 錨定規則人工抽樣")


def test_plan_2_1_keeps_its_residual_list_and_adds_created_from_in_a_dated_note():
    s21 = section(read(PLAN1), "2.1 第 1A 批")
    original = "- MENTIONS 屬性：start_pos 等欄位有 5,782 條不同，source_granularity 有 40,261 條不同。"
    assert original in s21   # history is not rewritten
    note = s21[s21.index(original) + len(original):].lstrip("\n").splitlines()[0]
    for needle in ("2026-10-06", "created_from", "106", "manual_patch", "mentions_props", "--check",
                   "end_pos", "backfilled", "verse_mention_freq"):
        assert needle in note, needle


def test_plan_section_9_records_the_w1_decisions_and_runbook_overrides():
    plan = read(PLAN1)
    s9 = section(plan, "9. W0 之後的決定")
    for needle in ("Q1", "text_correct", "id_correct", "60/60", "51/60", "Q2", "person:bide", "person:yuehan（shitu）",
                   "Q3", "list_stop: cont", "Q4", "C3c", "H12", "bible_rag-backend:w1", "docker save", "O1",
                   "087ab0d", "O7", "bible_entities_v3", "v4", "待 Kay 確認", "](../staging_promotion.md)"):
        assert needle in s9, needle
    s1 = section(plan, "1. 分波計畫")
    w2 = s1[s1.index("**W2 升版**"):]
    assert "O7" in _line(w2, "3. ") and "v4" in _line(w2, "3. ")
    assert "§9" in _line(s1[s1.index("**W1 升版**"):], "1. ")


# ---------------------------------------------------------------- archived evidence

def test_kg_fix_readme_names_the_scripts_that_need_a32fbea():
    assert not (ROOT / "scripts" / "relation_extraction" / "rule_classifier.py").exists()
    users = sorted(p.relative_to(KGFIX).as_posix() for p in KGFIX.rglob("*.py")
                   if "rule_classifier" in read(p))
    assert users == ["relations/sim.py", "relverify/exactsim.py"], users
    readme = read(KGFIX / "README.md")
    note = section(readme, "a32fbea")
    assert all(f"`{rel}`" in note for rel in users), note
    assert "git archive a32fbea scripts config" in note and "9c1c6c3" in note, note

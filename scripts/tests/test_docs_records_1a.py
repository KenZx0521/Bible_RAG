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
README names the archived scripts that need a32fbea. The archive READMEs say
what archiving changed, which root and hash seed a replay depends on, and what
the frozen-definition scripts still read (W1 review minors, docs_records 1).
The plan's §2.1 pilot gives the 57/60 id gate as history (Q1 moved the gate to
text_correct), and §9.1 records O5: expected files, fragments and the merged
allowlist's sha256 are registered before W1 step 2 (docs_records 2). §9.1's
dated block of Kay's 2026-10-06 decisions confirms O7 (Q6) and O5 with the
rejection rule and the batch-0 staging backup (Q7), times K8 after R4 (Q10),
and lists the long functions W1 touched as known debt (Q11), each length as
an AST scan measures it before W1 (f06cc7b) and at the W1 merge (69f3571).
"""
from __future__ import annotations

import ast
import json
import re
import subprocess

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
    # M371: children_with_gt2_parents is len(parents) > 2; 「2 個以上」 reads as ≥2 in these docs
    gt2 = f"超過 2 個父母（3 個以上）的 {allpar['children_gt2_parents']} 個"
    live = SIM2["allparent_live"]["children_gt2_parents"]
    rows = (_line(s01, "| | 有 ≥2 個非女性父母"), _line(s21, "| R6 函數性"))
    assert f"{gt2}（live {live}）" in rows[0] and gt2 in rows[1], rows
    assert not [row for row in rows if "2 個以上父母" in row], rows
    # M372: the 1A 【待重算】 markers were replaced, not kept
    legend = _line(plan, f"> - {W1}")
    assert "原本的值留著當紀錄" in legend and "1A 原有的【待重算】改成這個標記" in legend, legend
    assert "原本的值與標記留著" not in legend, legend


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
                   "087ab0d", "O7", "bible_entities_v3", "v4", "](../staging_promotion.md)"):
        assert needle in s9, needle
    s1 = section(plan, "1. 分波計畫")
    w2 = s1[s1.index("**W2 升版**"):]
    assert "O7" in _line(w2, "3. ") and "v4" in _line(w2, "3. ")
    # Kay confirmed O7 on 2026-10-06 (Q6): no pending marker is left on it
    assert "待 Kay 確認" not in plan and "Q6" in _line(s9, "- **O7") and "Q6" in _line(w2, "3. ")
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


# ---------------------------------------------------------------- review minors (docs_records 1)

W1_1A = KGFIX / "batch1" / "w1_1A"
W1_1B = KGFIX / "batch1" / "w1_1B"
FINAL_TAG = "gei_declared_ppg_cont_any_hom2_disany"


def _paragraph(text: str, needle: str) -> str:
    return next(p for p in text.split("\n\n") if needle in p)


def _ignored(path) -> bool:
    """Matched by a .gitignore pattern, tracked or not (--no-index)."""
    return subprocess.run(["git", "check-ignore", "-q", "--no-index", str(path)], cwd=ROOT).returncode == 0


def _w1_1a_note() -> str:
    return section(read(KGFIX / "README.md"), "W1 1A 重算")


def test_w1_1a_archive_note_lists_every_change_made_while_archiving():
    # M000: archiving also added argparse, sys.path and docstrings, not only the roots and the import name
    intro = _paragraph(_w1_1a_note(), "歸檔時")
    assert "其餘逐字未動" not in intro, intro
    for needle in ("`anchored_v2` → `anchored_w1`", "argparse", "`--out-dir`", "`--out`", "`sys.path`", "docstring",
                   "Usage", "計算邏輯逐字未動", "bak/20261005_w1_1A_evidence/"):
        assert needle in intro, needle
    for script in ("gen_fixture.py", "r4_final.py", "multi_parent.py"):
        assert f"`{script}`" in intro and "argparse.ArgumentParser()" in read(W1_1A / script), script
    for script in ("sim_1a_w1.py", "gen_fixture.py"):
        assert "sys.path.append(" in read(W1_1A / script) and f"`{script}`" in intro, script


def test_w1_1a_default_outputs_are_gitignored_and_the_archive_is_not():
    # M001: --out-dir/--out default to the script's own directory inside the tracked docs tree
    generated = [f"{kind}_{begot}_any_full_off_off{ext}" for begot in ("off", "father", "gei")
                 for kind, ext in (("sim2", ".json"), ("clean2", ".jsonl"), ("anch2", ".jsonl"))]
    generated += [f"sim2_{FINAL_TAG}.json", f"clean2_{FINAL_TAG}.jsonl", f"anch2_{FINAL_TAG}.jsonl",
                  "anchored_regression.jsonl"]
    assert not [name for name in generated if not _ignored(W1_1A / name)]
    tracked = subprocess.run(["git", "ls-files", str(W1_1A)], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked and not [path for path in tracked if _ignored(ROOT / path)], tracked
    assert "gitignore" in _line(_w1_1a_note(), "- 輸出寫到 `--out-dir`")


def test_w1_1a_replay_names_its_root_and_compares_sim2_without_the_probes():
    # M002/M324: the block reads the default (main) root; on a tree with 26bc252 sim2 differs only in probes
    note = _w1_1a_note()
    root = _line(note, "- 重放區塊不設 `BIBLE_RAG_ROOT`")
    for needle in ("export BIBLE_RAG_ROOT=$PWD", "26bc252", "`probes`", "after_10_2"):
        assert needle in root, needle
    block = re.search(r"```bash\n(.*?)```", note, re.S)[1]
    cmps = [line for line in block.splitlines() if line.startswith("cmp ")]
    assert len(cmps) == 3 and all(line.count("jq -S 'del(.probes)'") == 2 for line in cmps), cmps
    after = note[note.index("```", note.index("```bash") + 3) + 3:].lstrip("\n").split("\n\n")[0]
    for needle in ("26bc252", "`probes`", "逐位元相同", "14e2063"):
        assert needle in after, needle
    # M017: the 「但」 filter moved to geo_rules.py (7d9e680); cleanup_noise_entities re-exports it
    deps = _paragraph(note, "兩個 sha 只取決於")
    for needle in ("scripts/entity_extraction/geo_rules.py", "scripts/entity_extraction/stoplists.py", "7d9e680"):
        assert needle in deps, needle
    cleanup = read(ROOT / "scripts" / "cleanup_noise_entities.py")
    assert "from entity_extraction.geo_rules import compute_dan_keep_sources" in cleanup
    assert "from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST" in cleanup


def test_kg_fix_readme_says_what_the_frozen_definition_scripts_still_read_and_what_is_tested():
    # M005/M009: the definitions are frozen, the data side is not; the test guards 7 scripts and a ledger
    from test_supp_defs_frozen import ARCHIVED
    para = _paragraph(section(read(KGFIX / "README.md"), "路徑參數"), "自 1B 起")
    assert "所以在任何 HEAD 都能重放" not in para, para
    for needle in ("定義在任何 HEAD 都能重放", "`15ed2505…`", "`$W1_1B_EVIDENCE/neo4j_relationships_pre1b.jsonl`",
                   "`assert len(kept)==len(supp)`", "`CROSS_REF_ABBREV`", "`test_definition_ledger`", "XREF-2",
                   "X2", f"共 {len(ARCHIVED)} 支", "`ARCHIVED`"):
        assert needle in para, needle
    assert not [p for p in ARCHIVED if f"`{p.relative_to(KGFIX).as_posix()}`" not in para
                and f"`{p.name}`" not in para], para
    assert "assert len(kept)==len(supp)" in read(KGFIX / "xref" / "supp.py")
    assert "from bible_chunking.config import CROSS_REF_ABBREV" in read(KGFIX / "verifier_xref" / "mdpairs.py")


def test_w1_1b_readme_pins_the_hash_seed_and_names_the_relocated_reads():
    readme = read(W1_1B / "README.md")
    # M007: set iteration orders two stdout lines of sim_w1_1b.py by PYTHONHASHSEED
    assert "set(md_pairs) | set(supp_pairs)" in read(W1_1B / "sim_w1_1b.py")
    block = re.search(r"```bash\n(.*?)```", section(readme, "重放"), re.S)[1]
    assert block.index("export PYTHONHASHSEED=0") < block.index("for s in sim_w1_1b"), block
    verified = _paragraph(readme, "已驗證（2026-10-05）")
    for needle in ("PYTHONHASHSEED", "`xref_provenance`", "`xrefs by source`", "fingerprint"):
        assert needle in verified, needle
    # M008: inputs that moved to $W1_1B_EVIDENCE although no root literal named them
    bullet = _line(section(readme, "路徑參數"), "- 大型輸出")
    reads = [(p.name, name) for p in sorted(W1_1B.glob("*.py"))
             for name in re.findall(r"open\(W1_1B_EVIDENCE \+ '/([^']+)'\)", read(p))]
    assert sorted(reads) == [("ro_c1_probe.py", "pred_trans.json"), ("sim_backend_w1.py", "xref_new_w1.json")], reads
    assert not [r for r in reads if f"`{r[0]}` 讀 `$W1_1B_EVIDENCE/{r[1]}`" not in bullet], bullet


def test_plan_9_h11_note_lists_every_h11_metric():
    # M374: §9.1 copied five names from the §2.1 row; H11 reports seven
    from kg_validate.checks_h import _h11_row_tests
    names = [*_h11_row_tests(None, frozenset()), "undirected_pair_duplicates"]
    note = _line(section(read(PLAN1), "9. W0 之後的決定"), "- **H11 改號")
    assert len(names) == 7 and not [name for name in names if name not in note], note


# ---------------------------------------------------------------- review minors (docs_records 2)

def test_plan_2_1_pilot_states_the_id_gate_as_history():
    # M376: Q1 made text_correct the gate; the pilot's 57/60 id gate must not read as a live requirement
    precision = _line(section(read(PLAN1), "2.1 第 1A 批"), "| 錨定精確率")
    assert "id 閘門至少要" not in precision, precision
    for needle in ("當時以 id_correct 為閘門，需 57/60", "2026-10-05 Q1 改為 text_correct，見 §9.1"):
        assert needle in precision, needle


def test_plan_9_1_records_o5_and_supersedes_the_section_3_commit_timing():
    # M380: §9.1 recorded Q1–Q4, H11, the image note, O1 and O7 but not O5 (pre-registration before step 2)
    plan = read(PLAN1)
    s91 = section(plan, "9.1 W1 實作期間")
    o5 = _line(s91[s91.index("**執行面的更正"):], "- **O5 ")
    sha_file = "config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256"
    for needle in ("relations_allow.yaml", "residuals_allow.yaml", "xref_allow.yaml", "第 2 步", "之前 commit",
                   "W1 紀錄", "`--merge-out`", sha_file, "R2", "第 4 步經 Kay 核可", "R4", "ratchet",
                   "看過 staging 的 diff 之後", "§3", "「Kay 核可後 commit」"):
        assert needle in o5, needle
    # the quoted §3 text is still there (history is not rewritten), and the runbook registers the same sha file
    assert "Kay 核可後 commit" in _line(section(plan, "3. 跨批共用機制"), "| 期望檔")
    assert f"--sha-out {sha_file}" in section(read(ROOT / "docs" / "staging_promotion.md"), "R2")


# ---------------------------------------------------------------- Kay's decisions 2026-10-06 (DK2)

PRE_W1, W1_MERGE = "f06cc7b", "69f3571"   # tag kg-pre-batch1-w1 and the W1 merge commit
_DEBT = re.compile(r"`([\w/.-]+\.py)::([\w.]+)` (\d+)(?:→(\d+))?")


def _kay_1006() -> str:
    s91 = section(read(PLAN1), "9.1 W1 實作期間")
    return s91[s91.index("**Kay 的決定（2026-10-06"):]


def test_plan_9_1_records_kays_2026_10_06_decisions_on_o7_o5_and_k8():
    note = _kay_1006()
    q6, q7, q10 = (_line(note, f"- **{q} ") for q in ("Q6", "Q7", "Q10"))
    for needle in ("O7", "`bible_entities_v3`", "v4", "detB", "check_w1_registration", "`QDRANT_ENTITY_COLLECTION`",
                   "`scripts/tools/staging.env`", "Step 3", "INVALID", "--recreate", "v2"):
        assert needle in q6, needle
    for needle in ("O5", "M390", "§3", "「Kay 核可後 commit」", "第 2 步之前", "第 4 步", "不改", "prod 不動",
                   "從 Step 5", "`pg_dump -Fc`", "bible_rag_staging", "7688", "Qdrant", "residuals_expect",
                   "R0 第 9 項", "](../staging_promotion.md)"):
        assert needle in q7, needle
    for needle in ("K8", "M364", "R4", "只報告", "事前登記", "不回滾", "−0.005", "§7", "`:w1`", "R2", "staging 只有一個",
                   "W1 升版第 1、2 步之間"):
        assert needle in q10, needle
    # the plan's pointers (§5.3, O1) to the W1 promotion sections resolve through a dated note, not a rewrite
    moved = _line(note, "**文件位置（2026-10-06）**")
    for needle in ("](../staging_promotion_w1.md)", "§5.3", "O1", "「W1 的 /api/v1/entity 比對」", "原文不變"):
        assert needle in moved, needle
    assert "](../staging_promotion.md)「W1 的 /api/v1/entity 比對」" in section(read(PLAN1), "5.3")


def _functions(rev: str, path: str) -> dict[str, tuple[int, str]]:
    """{dotted name: (lines, source)} of every function in `path` at `rev`; {} when the file is not there."""
    out = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return {}
    found = {}

    def walk(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = (child.end_lineno - child.lineno + 1,
                                              ast.get_source_segment(out.stdout, child))
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
    walk(ast.parse(out.stdout), "")
    return found


def _w1_long_functions() -> dict[tuple[str, str], tuple[int | None, int]]:
    """{(path, name): (lines before, lines at the merge)} of the production functions (backend/, scripts/, no
    tests) that W1 changed or added and that are ≥ 50 lines on either side."""
    files = subprocess.run(["git", "diff", "--name-only", PRE_W1, W1_MERGE, "--", "backend", "scripts"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    found = {}
    for path in (f for f in files if f.endswith(".py") and "/tests/" not in f):
        before, after = _functions(PRE_W1, path), _functions(W1_MERGE, path)
        for name, (lines, source) in after.items():
            old_lines, old_source = before.get(name, (None, None))   # a function new in W1 counts as changed
            if old_source != source and max(lines, old_lines or 0) >= 50:
                found[(path, name)] = (old_lines, lines)
    return found


def test_plan_9_1_q11_lists_the_long_functions_w1_touched_as_measured():
    q11 = _line(_kay_1006(), "- **Q11 ")
    entries = {(path, name): (int(first), int(second or first)) for path, name, first, second in _DEBT.findall(q11)}
    for (path, name), (first, second) in entries.items():
        before, after = _functions(PRE_W1, path).get(name, (None,))[0], _functions(W1_MERGE, path)[name][0]
        assert (first, second) == (before or after, after), (path, name, before, after)
    archive = {key for key in entries if key[0].startswith("docs/records/")}
    assert archive == {("docs/records/2026-10-04_kg_fix/batch1/w1_1A/sim_1a_w1.py", "main")}, archive
    measured = _w1_long_functions()
    debt = {key for key, (before, after) in measured.items() if after >= 50}
    assert len(debt) == 8 and {key for key in entries if entries[key][1] >= 50} - archive == debt, debt
    assert all(before and before >= 50 for key, (before, _) in measured.items() if key in debt)   # none new in W1
    assert {key for key in entries if entries[key][1] < 50} == set(measured) - debt   # paid down by W1
    for needle in ("W1 改到", "已知債", "R2 之前不重構", "逐字", "AST", PRE_W1, W1_MERGE, "router.py", "不是債"):
        assert needle in q11, needle

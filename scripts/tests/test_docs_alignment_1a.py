"""Batch 1A (W1) pins of the staging runbook, docs/staging_promotion.md.

test_docs_alignment.py holds the shared helpers and the batch-0 and 1B pins and
is near the 800-line limit, so 1A's runbook pins live here: the 1A rows of the
inventory; K9 pre-registered and labelled before the 1A expected files, both
before the W1 rebuild (decisions Q1, O5); the --replace props digest and the
1A R2 gates, among them the batch-0 MENTIONS property residual re-read with
residuals_expect --check, both per-side digests and the counts, and named again at R4
(plan §2.1), and the W1 README crediting diff_kg, not --check, with the K10
mention_count residuals; the /api/v1/entity identity check as a prod before/after on one
image (decision O1); the K8 staging-P1 control after R4 on the same image; the
W1 staging entity collection v3 (decision O7, pending Kay); 1A's share of the
single R4 ratchet; two 1B leftovers (backend-staging without deps, and
when Step 9's second run happens); and the registration pre-flight
check_w1_registration: in the W1 chain right after 6.05 and before Step 3 (Step 5
empties the batch-0 staging residuals_expect reads), the gate of R1 item 5, and
the files, merge order and merged-sha256 file it checks equal to the ones the
runbook registers (diff_kg --merge-out --sha-out), and the three expected files'
content it validates named where the runbook and the chain row describe it.

W1 review minors on the build side, docs/build_database.md and the README
pipeline: the chain rows carry what their W1 step needs (check_merged_inputs
quotes the plan's sha pins and restores before comparing, 6.05 points to the
registered output, 6.1 to the --replace re-imports, 10.6 runs the exact Step
10.6 commands plus v3 == detB); the 從零 line swaps Step 1 only when the
artifacts were restored; Step 6.05 dates its R2/R5 rows and says run_id
leaves out the mode (the K8 control shares W1's); a new R11 target is
edited, since --accept moves only the value; every backend-staging up skips
deps; and the README pipeline, under a pointer to 「執行順序」, runs the Step 0
gates first and sketches the 從零 chain (8a/8b around 10.x, Step 7, 10.6 on
prod, export_event_registry --check last).
"""
from __future__ import annotations

import json
import re

import import_relations_neo4j as imp
import validate_kg as vk
from scripts.tools import check_merged_inputs as cmi
from scripts.tools import check_w1_registration as cwr
from scripts.tools import residuals_expect as rx
from test_docs_alignment import (D_GUARD, ROOT, _blocks, _commands, _documented_flags, _first, _in_order, _positions,
                                 _rebuild_chain, doc_text, headings, help_text, read, section, staging_text)
from test_relation_postprocess import _run

SEED = "20261007"
EXPECT = "config/kg_expect/batch1_w1/"
SIM = "docs/records/2026-10-04_kg_fix/batch1/w1_1A/"
W1A = "W1 的關係層檢查"
API = "W1 的 /api/v1/entity 比對"
K8 = "W1 的 K8 對照組"
# plan §5.3: the W1 ids whose /api/v1/entity answer must not change
API_IDS = ["person:make", "person:liwei", "place:dan", "group:yehehua", "event:shanshangbaoxun",
           "person:yeteluo", "event:jinniudushijian"]
# the PROBES ids 1A fixes (plan §6 #5); W1 leaves 7 of the 13 stored ids failing
FIXED_1A = ("edge-no-dan-orphan-nehemiah-wall", "kin-leah-not-father-of-isaac",
            "kin-leah-not-father-of-reuben", "kin-lot-not-father-of-terah")
NORMALISE = "jq -S '.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)'"
REG = "check_w1_registration"
W1_README = ROOT / "evaluation" / "experiments" / "2026-10-05_kg_w1" / "README.md"
# mentions_props.sha256 of the candidate read 2026-10-06 while 7688 still held the batch-0 build
MENTIONS_SHA = ("cd458a0bf25390821a391502a46ecf1fd1768e7e60b1b695f45528a5c80b5cb0",
                "17eefb2751e5dd383b68aa9529ce6b0f7ad15c5153c6edccab81f77db74daa77")


def _row(name: str) -> str:
    return next(line for line in staging_text().splitlines() if line.startswith(f"| {name}"))


def _heading(heads: list[str], prefix: str) -> int:
    return next(i for i, head in enumerate(heads) if head.startswith(prefix))


def test_inventory_lists_the_1a_tools_and_the_importer_contract():
    for name in ("relation_extraction/relation_postprocess.py", "tools/check_merged_inputs.py",
                 "tools/kin_review.py", f"tools/{REG}.py"):
        assert _row(name).count("| — ") >= 3, _row(name)   # no database at all
    for name in ("tools/check_edge_set.py", "tools/relations_expect.py", "tools/residuals_expect.py"):
        assert "check_identity" in _row(name) and "唯讀" in _row(name), _row(name)
    importer = _row("import_relations_neo4j.py")
    for needle in ("relations_clean", "拒絕", "--replace", "KG_TARGET=staging"):
        assert needle in importer, needle
    assert "--sha-out" in _row("tools/diff_kg.py") and "Step 3" in _row(f"tools/{REG}.py")
    legacy = _row("backfill_event_relations.py")
    assert "--legacy-cooccurrence" in legacy and "結束碼 2" in legacy and "K8" in legacy, legacy


def test_k9_is_preregistered_and_gates_on_text_correct_only():
    # decision Q1: text_correct gates (anchored n = 60, Wilson lower bound >= 0.85); id_correct is reported
    w1a = section(staging_text(), W1A)
    commands = _commands(w1a)
    samples = [c for c in commands if "kin_review.py --mode sample" in c]
    assert [re.search(r"--source (\S+)", c)[1] for c in samples] == ["anchored_rule", "llm", "prior"], samples
    assert all(f"--seed {SEED}" in c for c in samples), samples
    assert "--n 60" in samples[0] and "--n 30" in samples[1] and "--all" in samples[2], samples
    scores = [c for c in commands if "kin_review.py --mode score" in c]
    gate = next(c for c in scores if "anchored.json" in c)
    assert not re.search(r"--report-only|--gate-field|--min-lb", gate), gate   # the defaults gate
    assert gate.count("--labels") == 2 and "--spotcheck" in gate, gate
    assert len(scores) == 2 and "--report-only" in scores[1], scores
    words = " ".join(help_text("kin_review").split())
    assert "default text_correct" in words and "default 0.85" in words
    for needle in ("20261005", "text_correct", "id_correct", "0.85", "57/60", "非人工", "空目錄", "Kay 抽查",
                   "enabled: false", "sim2_no_anchored.json", "不重抽", "第 0 批圖上失敗的探針清單"):
        assert needle in w1a, needle
    # the fallback's probe edits name the tests that pin the probe lists: they must exist under those names
    pp_tests = read(ROOT / "scripts" / "tests" / "test_relation_postprocess_output.py")
    for test in ("test_final_edge_set", "test_batch0_graph_r6_and_failing_probes"):
        assert test in w1a and f"def {test}(" in pp_tests, test


def test_1a_expected_files_follow_k9_and_come_from_the_tools():
    commands = _commands(section(staging_text(), W1A))
    _in_order(commands, ("kin_review.py --mode sample", "kin_review.py --mode score", "relations_expect.py",
                         "validate_kg.py --live --target prod --json", "residuals_expect.py"))
    rel = commands[_first(commands, "relations_expect.py")]
    assert f'--expect-edge-set-sha "$(jq -r .after_10_2_sha256 {SIM}sim2_final.json)"' in rel, rel
    assert f"--out {EXPECT}relations_expected.json --allow-out {EXPECT}relations_allow.yaml" in rel, rel
    res = commands[_first(commands, "residuals_expect.py")]
    assert "--a prod --b staging" in res, res
    assert f"--out {EXPECT}residuals_expected.json --allow-out {EXPECT}residuals_allow.yaml" in res, res
    assert [c for c in commands if c.startswith("(source scripts/tools/staging.env && ")
            and "validate_kg.py --live --target staging --json" in c], commands
    for name, prefix in (("sim2_final.json", "661cfc62"), ("sim2_no_anchored.json", "bbc5c830")):
        assert json.loads(read(ROOT / SIM / name))["after_10_2_sha256"].startswith(prefix), name


def test_rebuild_checks_the_registered_6_05_output_and_replaces_twice():
    # 1A-C5d: --replace right after 6.1; after 10.2 the endpoint check refuses (the generic Events are gone)
    w1a = section(staging_text(), W1A)
    commands = _commands(w1a)
    registered = f"scripts/tools/{REG}.py"
    assert not [c for c in commands if "jq -r .output_sha256" in c], commands   # the tool checks all three shas
    reads = [_first(commands, f"props_sha > bak/$D/props_{n}.txt") for n in range(3)]
    replaces = [i for i, c in enumerate(commands) if "import_relations_neo4j.py --replace" in c]
    assert _first(commands, registered) < reads[0] < replaces[0] < reads[1] < replaces[1] < reads[2], commands
    # one cmp per line: set -e ignores a failing cmp that is not the last of an && list (M389)
    assert reads[2] < _first(commands, "cmp bak/$D/props_0.txt bak/$D/props_1.txt") < _first(
        commands, "cmp bak/$D/props_1.txt bak/$D/props_2.txt")
    assert not [c for c in commands if c.startswith("cmp ") and "&&" in c], commands
    layer = "NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']"
    assert layer in imp._LAYER and layer in w1a   # the importer's semantic layer, nothing else
    for needle in ("apoc.map.sortedProperties(properties(r))", "ORDER BY h, ty, t, p", "5,696", "10.2 之前"):
        assert needle in w1a, needle


def test_r2_runs_the_1a_gates_on_the_w1_build():
    w1a = section(staging_text(), W1A)
    commands = _commands(w1a)
    probes = commands[_first(commands, ".checks.PROBES.metrics.failing.fixed")]
    assert all(f'"{pid}"' in probes for pid in FIXED_1A) and "bak/$D/validate_staging_w1.json" in probes
    for needle in ("d3_gate.py --label w1 --control-url http://localhost:8000 "
                   "--treatment-url http://localhost:8001 --route-residual-max 0",
                   "--graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_w1",
                   "for c in bible_entities_v3 bible_entities_detB; do", "collections/$c/points/scroll"):
        assert any(needle in c for c in commands), needle
    for needle in ("check_edge_set", "待 Kay 確認", "Step 10.6", "kg_diff_allow_batch1w1.yaml", "7 個 id"):
        assert needle in w1a, needle


def test_r2_rechecks_the_registered_mentions_residual_and_r4_names_its_counts():
    # plan §2.1: diff_kg counts MENTIONS but never compares their properties; W1 ships batch 0's residual
    w1a = section(staging_text(), W1A)
    check = f"residuals_expect.py --a prod --b staging --check {EXPECT}residuals_expected.json"
    _in_order(_commands(w1a), ("import_relations_neo4j.py --replace", check))   # after the rebuild
    gate = w1a[w1a.index("4. **R2 閘門**"):]
    for needle in (check.split(" --a")[0], "乾淨的 shell", "bolt://localhost:7688", "46,205", "40,261", "5,782",
                   "created_from 106", "W1 紀錄"):
        assert needle in gate, needle
    moved = next(line for line in section(staging_text(), "R4").splitlines() if "1A 移動的指標" in line)
    assert "labels、MENTIONS 不變" not in moved
    for needle in ("labels 與 MENTIONS 的條數不變", "40,261", "5,782", "created_from 106", "W1 紀錄"):
        assert needle in moved, needle
    assert "R2（`--check`）" in _row("tools/residuals_expect.py")


def test_r2_check_requires_both_mentions_digests_and_r4_and_the_inventory_say_so():
    # W1 does not change MENTIONS: counts alone miss a change confined to already-differing edges
    gate = section(staging_text(), W1A)
    gate = gate[gate.index("4. **R2 閘門**"):]
    item = gate[gate.index("- MENTIONS 屬性的第 0 批殘差"):gate.index("- entity collection")]
    registered = [f"`{sha[:12]}…`" for sha in MENTIONS_SHA]
    for needle in ("逐邊摘要", "`sha256.a`", "`sha256.b`", "條數不變", "沒有摘要", *registered):
        assert needle in item, needle
    moved = next(line for line in section(staging_text(), "R4").splitlines() if "1A 移動的指標" in line)
    assert "逐邊摘要" in moved and "逐邊摘要" in _row("tools/residuals_expect.py")
    assert "逐邊摘要" in rx.PREMISE and "逐屬性條數" in rx.PREMISE


def test_w1_readme_credits_diff_kg_with_the_mention_count_residuals():
    # the K10 mention_count residuals are diff_kg's exact deltas from residuals_allow.yaml (R2 item 2);
    # residuals_expect --check reads only the MENTIONS properties
    block = section(read(W1_README), "為什麼受 mention_count 影響")
    line = next(text for text in block.splitlines() if text.startswith("W1 不改實體與 MENTIONS"))
    for needle in ("R2 第 2 項", "diff_kg", "`residuals_allow.yaml`", "`--fail-on-unused`", "MENTIONS 屬性"):
        assert needle in line, needle
    assert line.index("diff_kg") < line.index("residuals_allow.yaml") < line.index("residuals_expect.py --check")


def test_r2_starts_backend_staging_without_deps():
    # compose would otherwise converge neo4j-staging (and from a staging shell, interpolate prod services)
    ups = [c for c in _commands(section(staging_text(), "R2")) if re.search(r"docker compose .* up ", c)]
    assert len(ups) >= 2 and all("--no-deps" in c.split() for c in ups), ups


def test_r2_and_step9_agree_that_both_step9_runs_are_in_the_rebuild():
    item = next(line for line in section(staging_text(), "W1 的交叉引用檢查").splitlines()
                if line.startswith("2. **Step 9 連跑兩次**"))
    for needle in ("重建時", "緊接著", "10.1 之前", "R2 不再跑 Step 9"):
        assert needle in item, needle
    assert "緊接著再跑一次" in section(doc_text(), "Step 9:")


def _loop_ids(block: list[str]) -> list[str]:
    loop = next(c for c in block if c.startswith("for id in "))
    return re.match(r"for id in (.+); do$", loop)[1].split()


def test_api_identity_is_a_prod_before_and_after_on_the_w1_image():
    # decision O1: same W1 image and PG, only Neo4j changes; never :8000 against :8001 at R2
    text = staging_text()
    heads = headings(text)
    at = _heading(heads, API)
    assert heads[at - 1].startswith("W1 升版第 1 步") and heads[at + 1].startswith("W1 升版第 1、2 步之間")
    before, early, after = _blocks(section(text, API))
    w1_prod = "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend)\" = \"$(cat bak/$D/images/backend_w1.id)\""
    assert before[:4] == ["(", "set -eu -o pipefail -o noclobber", D_GUARD, w1_prod], before
    assert after[:4] == ["(", "set -eu -o pipefail", D_GUARD, w1_prod], after
    assert "test \"$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j)\" = healthy" in after
    for block, out in ((before, "before"), (after, "after")):
        assert _loop_ids(block) == API_IDS and not [c for c in block if "8001" in c], block
        curl = next(c for c in block if c.startswith("curl "))
        assert "localhost:8000/api/v1/entity/$id" in curl and NORMALISE in curl, curl
        assert curl.endswith(f'> "bak/$D/api/{out}/$id.json"'), curl
    assert 'cmp "bak/$D/api/before/$id.json" "bak/$D/api/after/$id.json"' in after
    assert _loop_ids(early) == API_IDS and any("8000 8001" in c for c in early), early
    case = next(c for c in early if c.startswith("case "))
    assert "person:yeteluo|event:shanshangbaoxun) " in case and "del(.aliases)" in case, case
    assert "/api/v1/entity/" not in " ".join(_commands(section(text, "R2")))
    assert API in section(text, "W1 升版第 1 步") and API in section(text, "W1 升版第 2 步")


def test_plan_5_3_says_the_related_queries_are_ordered():
    s53 = section(read(ROOT / "docs" / "records" / "2026-10-04_kg_batch1_plan.md"), "5.3")
    assert "沒有 ORDER BY" not in s53 and "087ab0d" in s53, s53
    assert "](../staging_promotion.md)" in s53


def test_r4_checks_1a_on_prod_before_the_single_ratchet_and_names_its_values():
    text = staging_text()
    heads = headings(section(text, "R4"))
    assert _heading(heads, "W1 的關係層升版後檢查") < _heading(heads, "W1 的交叉引用升版後檢查"), heads
    _in_order(_commands(section(text, "W1 的關係層升版後檢查")), (
        "validate_kg.py --live --target prod --json > bak/$D/validate_prod_w1.json",
        "jq -e '.failures == [] and .regressions - [\"R1\"] == []' bak/$D/validate_prod_w1.json",
        f"check_edge_set.py --target prod --expect {EXPECT}relations_expected.json"))
    moved = next(line for line in section(text, "R4").splitlines() if "1A 移動的指標" in line)
    for needle in ("R1（1,938 → 2,124", "15,926 → 5,616", "H3 374 → 0", "0.5357 → 0.0638", "剩 7 個 id",
                   "failing_probes", *FIXED_1A):
        assert needle in moved, needle


def test_k8_builds_the_p1_control_twice_after_r4_on_the_w1_image():
    text = staging_text()
    heads = headings(section(text, "R4"))
    assert _heading(heads, K8) > _heading(heads, "W1 的交叉引用升版後檢查"), heads
    k8 = section(text, K8)
    _in_order(_commands(k8), (
        "relation_postprocess --rules none --out output/relations_p1.jsonl --report output/relations_p1.report.json",
        "import_relations_neo4j.py output/relations_p1.jsonl", "backfill_event_relations.py --legacy-cooccurrence",
        "--graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_p1a",
        "--graph-strategies entity_path --top-k 5 --metric-k 6 --label ep_p1b",
        "ab_compare.py results_quick/ep_p1a.json results_quick/ep_p1b.json",
        "ab_compare.py results_quick/ep_p1a.json results_quick/ep_w1.json"))
    for needle in ("−0.005", "只報告", "雜訊地板", "W1 升版第 1、2 步之間", "bak/$D/promote/", "`validate_p1b.json`",
                   "不可覆寫 R2 的 `bak/$D/validate_staging_w1.json`", "兩次 `--replace`", "`bak/$D/props_*.txt`"):
        assert needle in k8, needle
    # M363: the W1 chain's 10.6 writes R2's gate report; P1's own report goes to k8/, and R2 recorded its sha256
    _in_order(_commands(k8), ("backfill_event_relations.py --legacy-cooccurrence", "mkdir -p bak/$D/k8",
                              "validate_kg.py --live --target staging --json > bak/$D/k8/validate_p1a.json"))
    assert not [c for c in _commands(k8) if "validate_staging_w1.json" in c], _commands(k8)
    _in_order(_commands(section(text, W1A)), (".checks.PROBES.metrics.failing.fixed",
                                               "(cd bak/$D && sha256sum ./validate_staging_w1.json >> SHA256SUMS)"))


def test_w1_staging_writes_bible_entities_v3_pending_kay():
    # decision O7 (pending Kay): v2 stays the batch-0 control; W1's 8a/8b --recreate only touch v3
    r0 = section(staging_text(), "R0")
    for needle in ("bible_entities_v3", "scripts/tools/staging.env", "待 Kay 確認"):
        assert needle in r0, needle
    assert "bible_entities_v3" in section(staging_text(), "拓撲")


def test_r1_points_to_the_1a_preregistration_and_times_the_w1_chain():
    r1 = section(staging_text(), "R1")
    assert f"「{W1A}」" in r1 and "K8" in r1, r1
    row = next(line for line in r1.splitlines() if line.strip().startswith("|") and "check_merged_inputs" in line)
    assert "6.05" in row and "1(merge)" not in row and "10.1–10.5" not in row, row
    assert row.index("6.05（兩次）") < row.index(REG) < row.index("、3、"), row


def test_r1_gates_the_w1_rebuild_on_the_registration_check():
    item = next(line for line in section(staging_text(), "R1").splitlines() if line.startswith("5. "))
    for needle in (f"`scripts/tools/{REG}.py`", "Step 3 之前", "結束碼不是 0 就停", "residuals_expect", "7688"):
        assert needle in item, needle


def test_w1_chain_checks_the_registration_right_after_6_05_and_before_step_3():
    labels, rows = _rebuild_chain(doc_text())
    table = [row[0] for row in rows]
    for steps in (labels, table):
        at = _positions(steps, ("check_merged_inputs", "6.05", REG, "3", "5"))
        assert at == sorted(at) and at[2] == at[1] + 1 and at[3] == at[2] + 1, steps
    row = rows[table.index(REG)]
    assert row[1] == f"`scripts/tools/{REG}.py`", row
    for needle in ("結束碼 0", "residuals_expect", "Step 5", "不連庫"):
        assert needle in row[2], needle
    prereg = next(line for line in section(doc_text(), "執行順序").splitlines() if line.startswith("- **事前登記**"))
    for needle in (cwr.MERGED_SHA, "--sha-out", REG, "R4 之後"):
        assert needle in prereg, needle


def test_the_registration_check_reads_what_the_runbook_registers():
    r2 = section(staging_text(), "R2")
    commands = _commands(r2)
    merge = " ".join(commands[_first(commands, "diff_kg.py --merge-out")].split())
    assert merge.endswith(f"diff_kg.py --merge-out {cwr.MERGED} --sha-out {cwr.MERGED_SHA} "
                          + " ".join(f"--allow {rel}" for rel in cwr.FRAGMENTS)), merge
    written = " ".join(" ".join(c.split()) for c in commands)
    for rel in cwr.REGISTERED:   # every registered file is one a documented command writes
        assert any(f"{flag} {rel}" in written for flag in ("--out", "--allow-out", "--sha-out")), rel
    assert f"`sha256sum -c {cwr.MERGED_SHA}`" in r2
    assert cwr.DEFAULT_REPORT.as_posix() == "output/relations_clean.report.json"
    assert "合併檔要到 R4 之後才 commit" in r2   # plan §3: what is registered before the rebuild is its sha256


def test_the_registration_check_validates_the_expected_files_content():
    # a residuals_expected.json without mentions_props passed while only committed-ness was checked
    assert set(cwr.CONTENT) == {cwr.RELATIONS_EXPECTED, f"{EXPECT}residuals_expected.json", f"{EXPECT}xref.json"}
    chain = " ".join(_chain_rows()[REG])
    for text in (chain, _row(f"tools/{REG}.py")):
        for needle in ("內容", "mentions_props", "逐邊摘要", "INVALID"):
            assert needle in text, needle
    assert "--check" in chain and "結束碼 2" in chain   # what the old format would have hit, after Step 5


# ---------------------------------------------------------------- build side: the W1 chain rows and texts

PLAN1 = ROOT / "docs" / "records" / "2026-10-04_kg_batch1_plan.md"
# plan §1 W1 chain: sha256 of entities.jsonl and entity_mentions.jsonl, 「不符就停」
PINS = ("9f2d1f39", "ba7ed188")
W1A_ITEM = "「W1 的關係層檢查」第 {} 項"


def _chain_rows() -> dict[str, list[str]]:
    return {row[0]: row for row in _rebuild_chain(doc_text())[1]}


def test_check_merged_inputs_row_quotes_the_plan_pins_and_restores_before_comparing():
    # the tool trusts the manifest, which freeze-grounded --force rewrites; its HAZARD extracts, then compares
    row = " ".join(_chain_rows()["check_merged_inputs"])
    w1 = next(line for line in read(PLAN1).splitlines() if line.startswith("0 → check_step0 → validate_output"))
    for pin in PINS:
        assert f"`{pin}…`" in row and f"={pin}…" in w1, pin
    assert "`extract_entities.py --stage freeze-grounded --force`" in row, row
    assert "還原兩檔後以 `bak/$D/output/MANIFEST.sha256` 核對，再重跑本檢查" in row, row
    assert "先以 `MANIFEST.sha256` 核對" not in row
    assert cmi.HAZARD.index("tar -C") < cmi.HAZARD.index("MANIFEST.sha256")


def test_w1_chain_rows_point_to_the_registered_output_the_replace_reimports_and_v3_detb():
    rows = _chain_rows()
    for needle in (REG, "output_sha256", "relations_expected.json", W1A_ITEM.format(3)):
        assert needle in rows["6.05"][2], needle
    assert rows["6.1"][1] == "`scripts/import_relations_neo4j.py`", rows["6.1"]
    for needle in ("8a 之前", "`--replace` 重匯兩次", "`props_0/1/2`", W1A_ITEM.format(3)):
        assert needle in rows["6.1"][2], needle
    for needle in ("`v3 == detB`", W1A_ITEM.format(4), "待 Kay 確認"):
        assert needle in rows["10.6"][2], needle
    xref = rows["xref_probe expect"][2]
    assert "「W1 步驟」第 2 步" in xref and "不是升版第 2 步" in xref, xref


def test_w1_chain_10_6_row_runs_the_exact_step_10_6_commands():
    # check_edge_set without --expect lets a regenerated report certify itself (plan §3)
    cell = _chain_rows()["10.6"][1]
    spans = re.findall(r"`([^`]+)`", cell)
    s106 = _commands(section(doc_text(), "10.6"))
    assert len(spans) == 3 and all(f"uv run --project scripts python {span}" in s106 for span in spans), spans
    for needle in (f"--expect {EXPECT}relations_expected.json", "--json > bak/$D/validate_staging_w1.json"):
        assert needle in cell, needle


def test_step10_6_entity_collection_points_to_the_runbook_command():
    bullet = next(line for line in section(doc_text(), "10.6").splitlines()
                  if line.strip().startswith("- entity collection"))
    assert f"R2{W1A_ITEM.format(4)}" in bullet and "w0_results" not in bullet, bullet


def test_step10_6_edits_a_new_r11_target_since_accept_moves_only_the_value():
    baseline = vk.load_baseline(ROOT / "config" / "kg_quality_baseline")
    spec = next(c for c in baseline["checks"] if c["id"] == "R11")
    before = spec["metrics"]["tsk_votes_edges"]
    assert spec["severity"] == "hard" and before["target"] == 250358, spec
    measured = vk.CheckResult({"tsk_votes_edges": 1, "tsk_flag_without_votes": 0})
    moved = vk.apply_ratchet(baseline, {"R11": measured}, False, {"R11"}, {"at": "test"})
    after = next(c for c in moved["checks"] if c["id"] == "R11")["metrics"]["tsk_votes_edges"]
    assert after == {**before, "value": 1}   # --accept adopts the value; the hard target stays
    bullet = next(line for line in section(doc_text(), "10.6").splitlines() if line.strip().startswith("- R11："))
    assert "`R11.tsk_votes_edges.target`" in bullet and "第 2D 批要重新 `--accept R11`" not in bullet, bullet


def test_step6_05_dates_the_r2_and_r5_rows_to_the_2026_05_run():
    s605 = section(doc_text(), "Step 6.05:")
    assert "\nStep 6 寫出各 phase" not in s605
    for needle in ("2026-05 那次的 Step 6（第 1A 批之前）", "第 1A 批起 Step 6 不再產生 R2 列", "R5 只在 `--inverse` 時才有"):
        assert needle in s605, needle


def test_fresh_chain_swaps_step1_for_check_merged_inputs_only_when_restored():
    # without restored artifacts there is no grounded manifest: check_merged_inputs exits 2
    fresh = next(line for line in section(doc_text(), "執行順序").splitlines() if line.startswith("- **從零**"))
    assert "還原了這些產物時，第 1 批期間 Step 1 照重灌鏈換成 `check_merged_inputs.py`" in fresh, fresh
    assert "沒有還原就照常跑完整的 Step 1" in fresh, fresh


def test_every_backend_staging_up_skips_deps():
    # compose would otherwise converge neo4j-staging, and from a staging shell interpolate prod services
    paths = [*sorted((ROOT / "docs").glob("*.md")), ROOT / "README.md", ROOT / "docker-compose.staging.yml"]
    ups = [(p.name, line) for p in paths for line in read(p).splitlines()
           if re.search(r"\bup -d\b.*\bbackend-staging\b", line)]
    assert {"build_database.md", "docker-compose.staging.yml"} <= {name for name, _ in ups}, ups
    assert all("--no-deps" in line.split() for _, line in ups), ups


def test_r2_names_all_three_10_6_checks_for_the_staging_shell():
    r2 = section(staging_text(), "R2")
    assert "10.6 的兩項" not in r2
    assert "10.6 的三項（validate_kg、check_identity、第 1A 批起的 check_edge_set）則要在 staging 的 shell 跑" in r2


def test_readme_pipeline_runs_the_step0_gates_before_entity_extraction():
    # decision O3: validate_output is mandatory before any store write
    commands = _commands(section(read(ROOT / "README.md"), "Data Pipeline"))
    _in_order(commands, ("process_bible.py", "check_step0.py", "validate_output.py output", "extract_entities.py",
                         "import_postgres.py", "import_neo4j.py"))


README_CHECKED = ("validate_kg", "check_identity", "export_event_registry", "desc_generator", "check_merged_inputs")


def test_readme_pipeline_sketches_the_fresh_chain_and_defers_to_the_build_order():
    # 從零 line: … 6.1 → 8a → 9 → 10.1 … 10.5 → 7 → 8b → 10.6 (--target prod) → export_event_registry --check
    block = section(read(ROOT / "README.md"), "Data Pipeline")
    commands = _commands(block)
    _in_order(commands, ("import_relations_neo4j.py", "embed_entities.py --recreate", "import_tsk_crossrefs.py",
                         "backfill_aliases.py", "backfill_manual_patches.py --apply",
                         "relation_extraction.desc_generator", "validate_kg.py --live --target prod",
                         "check_identity.py --target prod --fail-on id", "export_event_registry.py --check"))
    embeds = [i for i, command in enumerate(commands) if "embed_entities.py" in command]
    assert len(embeds) == 2 and all("--recreate" in commands[i] for i in embeds), commands   # 8a and 8b
    assert embeds[1] > _first(commands, "desc_generator") and "export_event_registry.py --check" in commands[-1]
    lead = block.split("```", 1)[0]
    for needle in ("](docs/build_database.md)「執行順序」為準", "`check_merged_inputs.py`", "`--replay --fail-on-stale`"):
        assert needle in lead, needle
    missing = {(s, f) for s in README_CHECKED for f in _documented_flags(s, ROOT / "README.md") if f not in help_text(s)}
    assert not missing, missing


def test_step6_05_says_run_id_leaves_out_the_mode():
    # the K8 control (--rules none) and W1 report one run_id for different outputs
    (_, everything), (_, none) = _run("all"), _run("none")
    assert everything["run_id"] == none["run_id"] and everything["output"]["sha256"] != none["output"]["sha256"]
    s605 = section(doc_text(), "Step 6.05:")
    report = next(line for line in s605.splitlines() if line.startswith("- pp_version"))
    for needle in ("不含 mode", "`--rules none` 對照組與 W1 的 run_id 相同", "rules.mode", "output 的 sha256"):
        assert needle in report, needle
    start = s605.index("# K8 的 staging-P1 對照組")
    k8 = s605[start:s605.index("--rules none", start)]
    assert "# run_id 不含 mode，與 W1 的相同；紀錄要連同 rules.mode 與 output 的 sha256 引用" in k8, k8

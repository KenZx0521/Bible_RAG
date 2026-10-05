"""Batch 1A (W1) pins of the staging runbook, docs/staging_promotion.md.

test_docs_alignment.py holds the shared helpers and the batch-0 and 1B pins and
is near the 800-line limit, so 1A's runbook pins live here: the 1A rows of the
inventory; K9 pre-registered and labelled before the 1A expected files, both
before the W1 rebuild (decisions Q1, O5); the --replace props digest and the
1A R2 gates; the /api/v1/entity identity check as a prod before/after on one
image (decision O1); the K8 staging-P1 control after R4 on the same image; the
W1 staging entity collection v3 (decision O7, pending Kay); 1A's share of the
single R4 ratchet; and two 1B leftovers (backend-staging without deps, and
when Step 9's second run happens).
"""
from __future__ import annotations

import json
import re

import import_relations_neo4j as imp
from test_docs_alignment import (D_GUARD, ROOT, _blocks, _commands, _first, _in_order, doc_text, headings,
                                 help_text, read, section, staging_text)

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


def _row(name: str) -> str:
    return next(line for line in staging_text().splitlines() if line.startswith(f"| {name}"))


def _heading(heads: list[str], prefix: str) -> int:
    return next(i for i, head in enumerate(heads) if head.startswith(prefix))


def test_inventory_lists_the_1a_tools_and_the_importer_contract():
    for name in ("relation_extraction/relation_postprocess.py", "tools/check_merged_inputs.py",
                 "tools/kin_review.py"):
        assert _row(name).count("| — ") >= 3, _row(name)   # no database at all
    for name in ("tools/check_edge_set.py", "tools/relations_expect.py", "tools/residuals_expect.py"):
        assert "check_identity" in _row(name) and "唯讀" in _row(name), _row(name)
    importer = _row("import_relations_neo4j.py")
    for needle in ("relations_clean", "拒絕", "--replace", "KG_TARGET=staging"):
        assert needle in importer, needle
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
                   "enabled: false", "sim2_no_anchored.json", "不重抽"):
        assert needle in w1a, needle


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
    registered = f"jq -r .output_sha256 {EXPECT}relations_expected.json"
    reads = [_first(commands, f"props_sha > bak/$D/props_{n}.txt") for n in range(3)]
    replaces = [i for i, c in enumerate(commands) if "import_relations_neo4j.py --replace" in c]
    assert _first(commands, registered) < reads[0] < replaces[0] < reads[1] < replaces[1] < reads[2], commands
    cmp = "cmp bak/$D/props_0.txt bak/$D/props_1.txt && cmp bak/$D/props_1.txt bak/$D/props_2.txt"
    assert _first(commands, cmp) > reads[2]
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
    for needle in ("−0.005", "只報告", "雜訊地板", "W1 升版第 1、2 步之間", "bak/$D/promote/"):
        assert needle in k8, needle


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

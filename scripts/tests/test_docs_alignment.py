"""The rebuild docs must match the scripts they tell people to run.

The runbook is split in two: docs/build_database.md (Step 0-10, rebuild order)
and docs/staging_promotion.md (staging, R0-R5 promotion). Every script name
with flags in either doc is checked against that script's real --help (and
--stage/--target choices), so a renamed or removed flag fails here instead of
in the middle of a rebuild. Also pins the batch-0 rebuild order (replay after
the curated overlay) in both the doc and the fix plan, whose batch-1+ details
live in a companion file, and checks that the cross links survive the split.
Batch 1B (W1) pins the cross-reference runbook: the expectation registered
before the rebuild and only re-checked during it, backend before data (the
R2-tested image itself, its id checked; the rollback image's id recorded and
saved to bak/ once, in fail-closed blocks), the opt-in A/B window on that
image, the deploy-guard as the first command of the data load, one ratchet
for the wave, the U3 count grep, the image never rolled
back ahead of the data and rolled back by the recorded id (compose with
--no-deps from a clean main-checkout shell), and no votes=999 sentinel left
in the mechanism docs. Batch 1A (W1) pins the single W1 rebuild chain (Step 1
replaced by check_merged_inputs, the offline 6.05 before any store write, no
10.3), the same order in the from-scratch chain and the README pipeline, and
the 1A hard checks and gates of Step 10.6.
"""
from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "build_database.md"
STAGING_DOC = ROOT / "docs" / "staging_promotion.md"
DOCS = (DOC, STAGING_DOC)
PLAN = ROOT / "docs" / "records" / "2026-10-04_kg_data_layer_fix_plan.md"
PLAN_BATCHES = ROOT / "docs" / "records" / "2026-10-04_kg_data_layer_fix_plan_batches.md"
PLANS = (PLAN, PLAN_BATCHES)
PY = str(ROOT / "scripts" / ".venv" / "bin" / "python")
CHECK_STEP0 = ROOT / "scripts" / "tools" / "check_step0.py"
# docs that describe the current cross-reference mechanism (not experiment-time values)
MECHANISM_DOCS = (ROOT / "docs" / "ARCHITECTURE.md", ROOT / "docs" / "kg_construction_overview.md",
                  ROOT / "evaluation" / "README.md")

# script name as it appears in the doc -> argv that prints its --help
HELP_ARGV = {
    "extract_entities": [PY, "scripts/extract_entities.py", "--help"],
    "desc_generator": [PY, "-m", "scripts.relation_extraction.desc_generator", "--help"],
    "export_live_state": [PY, "scripts/tools/export_live_state.py", "--help"],
    "validate_kg": [PY, "scripts/validate_kg.py", "--help"],
    "check_identity": [PY, "scripts/check_identity.py", "--help"],
    "diff_kg": [PY, "scripts/tools/diff_kg.py", "--help"],
    "kg_target": [PY, "scripts/kg_target.py", "--help"],
    "export_event_registry": [PY, "scripts/export_event_registry.py", "--help"],
    "check_step0": [PY, "scripts/tools/check_step0.py", "--help"],
    "backfill_manual_patches": [PY, "scripts/backfill_manual_patches.py", "--help"],
    "cleanup_noise_entities": [PY, "scripts/cleanup_noise_entities.py", "--help"],
    "import_tsk_crossrefs": [PY, "scripts/import_tsk_crossrefs.py", "--help"],
    "import_qdrant": [PY, "scripts/import_qdrant.py", "--help"],
    "import_neo4j": [PY, "scripts/import_neo4j.py", "--help"],
    "xref_probe": [PY, "scripts/tools/xref_probe.py", "--help"],
    "extract_relations": [PY, "-m", "scripts.relation_extraction.extract_relations", "--help"],
    "relation_postprocess": [PY, "-m", "scripts.relation_extraction.relation_postprocess", "--help"],
    "import_relations_neo4j": [PY, "scripts/import_relations_neo4j.py", "--help"],
    "backfill_event_relations": [PY, "scripts/backfill_event_relations.py", "--help"],
    "check_merged_inputs": [PY, "scripts/tools/check_merged_inputs.py", "--help"],
    "check_edge_set": [PY, "scripts/tools/check_edge_set.py", "--help"],
    "kin_review": [PY, "scripts/tools/kin_review.py", "--help"],
    "relations_expect": [PY, "scripts/tools/relations_expect.py", "--help"],
    "residuals_expect": [PY, "scripts/tools/residuals_expect.py", "--help"],
}
_SCRIPT_RE = re.compile(r"\b(" + "|".join(sorted(HELP_ARGV, key=len, reverse=True)) + r")(?:\.py)?\b")
_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


@functools.lru_cache(maxsize=None)
def help_text(script: str) -> str:
    out = subprocess.run(HELP_ARGV[script], cwd=ROOT, capture_output=True, text=True, timeout=300)
    return out.stdout + out.stderr


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def doc_text() -> str:
    return read(DOC)


def staging_text() -> str:
    return read(STAGING_DOC)


def plan_text() -> str:
    return read(PLAN)


def batches_text() -> str:
    return read(PLAN_BATCHES)


def _name(path: Path) -> str:
    return path.name


def mask_code(text: str) -> str:
    """Blank out fenced code (same length) so shell comments ("# ...") are not taken for headings."""
    return re.sub(r"```.*?```", lambda c: re.sub(r"[^\n]", "x", c.group(0)), text, flags=re.S)


def section(text: str, heading: str) -> str:
    """Text from a markdown heading to the next heading of the same or higher level."""
    masked = mask_code(text)
    m = re.search(rf"^(#+) {re.escape(heading)}.*$", masked, re.M)
    assert m, heading
    level = len(m.group(1))
    nxt = re.compile(rf"^#{{1,{level}}} ", re.M).search(masked, m.end())
    return text[m.start(): nxt.start() if nxt else len(text)]


def headings(text: str) -> list[str]:
    return re.findall(r"^#+ (.+)$", mask_code(text), re.M)


def code_snippets(text: str):
    """Inline code spans and fenced-block command lines (continuations joined)."""
    fenced = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    for block in fenced:
        yield from block.replace("\\\n", " ").splitlines()
    yield from re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))


def _git_ignored(path: Path) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT).returncode == 0


# ---------------------------------------------------------------- both runbook docs

@pytest.mark.parametrize("path", DOCS + PLANS, ids=_name)
def test_doc_stays_within_800_lines(path):
    assert len(read(path).splitlines()) <= 800


@pytest.mark.parametrize("path", DOCS, ids=_name)
def test_every_documented_flag_exists_in_that_scripts_cli(path):
    missing = []
    for snippet in code_snippets(read(path)):
        scripts = set(_SCRIPT_RE.findall(snippet))
        if len(scripts) != 1:
            continue
        (script,) = scripts
        args = snippet[_SCRIPT_RE.search(snippet).end():].split("#", 1)[0]
        for flag in _FLAG_RE.findall(args):
            if flag not in help_text(script):
                missing.append((script, flag, snippet.strip()))
    assert not missing, missing


@pytest.mark.parametrize("path", DOCS, ids=_name)
def test_documented_stage_and_target_values_are_valid_choices(path):
    text = read(path)
    stages = set(re.findall(r"--stage ([a-z-]+)", text))
    assert stages <= {"ner", "freeze-grounded", "merge"}, stages
    targets = set(re.findall(r"--(?:target|a|b) ([a-z]+)", text))
    assert targets <= {"prod", "staging"}, targets


@pytest.mark.parametrize("path", DOCS + PLANS, ids=_name)
def test_relative_links_resolve(path):
    broken = []
    for target in _LINK_RE.findall(mask_code(read(path))):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        dest = path.parent / target.split("#", 1)[0]
        if not dest.exists() and not _git_ignored(dest):
            broken.append(target)
    assert not broken, broken


# ---------------------------------------------------------------- the split

_STAGING_HEADINGS = ("拓撲", "環境變數契約", "執行前檢查", "R0", "R1", "R2", "R3", "R4", "R5", "收尾")


def test_staging_chapter_lives_in_its_own_doc_with_a_summary_left_behind():
    stub = section(doc_text(), "Staging 與升版流程")
    assert "](staging_promotion.md)" in stub
    for step in ("R0", "R1", "R2", "R3", "R4", "R5"):
        assert step in stub, step
    build_heads, staging_heads = headings(doc_text()), headings(staging_text())
    for name in _STAGING_HEADINGS:
        assert not [h for h in build_heads if h.startswith(name)], name
        assert [h for h in staging_heads if h.startswith(name)], name
    assert "](build_database.md)" in staging_text().split("\n## ", 1)[0]


# references to the moved chapter (or its sub-sections) from build_database.md
_TO_STAGING = re.compile(r"「Staging 與升版流程」|「執行前檢查」|見 R[0-5]\b|R0 的 `llm_artifacts")
# references from the moved chapter back to build_database.md sections
_TO_BUILD = re.compile(r"「執行順序」|見 Step \d")


def test_build_database_refs_to_the_staging_chapter_link_the_new_doc():
    text = doc_text()
    stub = section(text, "Staging 與升版流程")
    rest = mask_code(text.replace(stub, ""))
    unlinked = [line for line in rest.splitlines()
                if _TO_STAGING.search(line) and "staging_promotion.md" not in line]
    assert not unlinked, unlinked


def test_staging_doc_refs_to_build_steps_link_build_database():
    unlinked = [line for line in mask_code(staging_text()).splitlines()
                if _TO_BUILD.search(line) and "build_database.md" not in line]
    assert not unlinked, unlinked


# ---------------------------------------------------------------- build_database.md

def test_step1_documents_ner_manifest_and_guards():
    s1 = section(doc_text(), "Step 1:")
    for needle in ("ner_manifest.json", "--accept-grounded-drift", "NER half differs",
                   "sampled", "缺", "5%", "freeze-grounded --force", "embedding_queue"):
        assert needle in s1, needle
    assert "merge 不檢查 NER 半邊從哪來" not in s1
    outputs = section(s1, "輸出")
    assert "ner_manifest.json" in outputs


def test_step1_documents_g4_input_sha_behaviour():
    s1 = section(doc_text(), "Step 1:")
    # G4: merge compares ner_manifest.input.sha256 with the current embedding_queue
    assert re.search(r"輸入.{0,40}sha.{0,80}embedding_queue|embedding_queue.{0,80}sha.{0,40}不符", s1, re.S)


def test_validate_kg_exit_code_comment_covers_error_and_unmeasured():
    s106 = section(doc_text(), "10.6")
    assert "unmeasured" in s106 and "error" in s106


def test_step7_explains_the_expected_stale_procedure():
    s7 = section(doc_text(), "Step 7:")
    for needle in ("1A", "1C", "1D", "--fail-on-stale", "紀錄", "kg_diff_allow"):
        assert needle in s7, needle


# ---------------------------------------------------------------- staging_promotion.md

def test_r0_tarball_carries_the_ner_half_and_its_manifest():
    r0 = section(staging_text(), "R0")
    files = " ".join(re.findall(r'FILES="([^"]*)"', r0))
    for name in ("ner_entities.jsonl", "ner_mentions.jsonl", "ner_manifest.json"):
        assert name in files, name
    assert "--stage ner" in r0


def test_staging_precheck_requires_the_staging_target():
    text = staging_text()
    assert "scripts/kg_target.py --require-staging neo4j postgres qdrant" in text
    for path in DOCS:
        assert "kg_target.assert_target(\"neo4j\", \"postgres\", \"qdrant\")' && echo" not in read(path)


def test_diff_kg_command_allowlist_and_clean_shell_are_documented():
    r2 = section(staging_text(), "R2")
    s106 = section(doc_text(), "10.6")
    for part in (r2, s106):
        assert re.search(r"diff_kg\.py --a prod --b staging --allow config/kg_diff_allow_", part), part[:200]
    assert "乾淨" in r2 and "staging.env" in r2
    assert "kg_diff_allow_batch0.yaml" in r2
    row = next(line for line in staging_text().splitlines() if line.startswith("| tools/diff_kg.py"))
    for flag in ("--a", "--b", "--allow"):
        assert flag in row, flag
    assert "參數以 `--help` 為準" not in s106


def test_r4_rationale_reflects_the_prod_guard():
    r4 = section(staging_text(), "R4")
    assert "不擋「prod 檢查讀到 staging」" not in r4
    assert "拒絕" in r4 and "export_event_registry" in r4


def test_inventory_rows_are_current():
    lines = staging_text().splitlines()
    ci = next(line for line in lines if line.startswith("| check_identity.py"))
    assert "--target prod" in ci


# ---------------------------------------------------------------- batch 1B: cross references

def _documented_flags(script: str, *paths: Path) -> set[str]:
    """Flags written after `script` in the code snippets of `paths` (one script per snippet)."""
    flags = set()
    for path in paths:
        for snippet in code_snippets(read(path)):
            if set(_SCRIPT_RE.findall(snippet)) == {script}:
                args = snippet[_SCRIPT_RE.search(snippet).end():].split("#", 1)[0]
                flags.update(_FLAG_RE.findall(args))
    return flags


def _commands(text: str) -> list[str]:
    """Fenced-block command lines in order: continuations joined, runs of whitespace collapsed,
    comments and blanks dropped."""
    lines = []
    for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            line = " ".join(re.sub(r"\s+#\s.*$", "", line).split())
            if line and not line.startswith("#"):
                lines.append(line)
    return lines


def _first(commands: list[str], needle: str) -> int:
    return next(i for i, command in enumerate(commands) if needle in command)


def test_w1_runbook_documents_the_xref_probe_and_diff_kg_flags():
    # with test_every_documented_flag_exists_in_that_scripts_cli these must exist in --help
    probe = _documented_flags("xref_probe", *DOCS)
    assert {"--expect", "--target", "--container", "--seeds", "--pred", "--measured", "--edges",
            "--edges-out", "--output-dir", "--tsk", "--pericopes", "--questions", "--out"} <= probe, probe
    assert {"--fail-on-unused", "--merge-out"} <= _documented_flags("diff_kg", STAGING_DOC)


def test_step0_documents_the_xref_gate_and_that_1b_leaves_pericopes_alone():
    s0 = section(doc_text(), "Step 0:")
    for needle in ("validate_output.py", "932", "162", "159/159", "-?", "neo4j_relationships.jsonl"):
        assert needle in s0, needle
    assert "第 1B、2D 批會改 pericopes.jsonl" not in s0
    assert "1B/2D touch pericopes.jsonl" not in read(CHECK_STEP0)


def test_step5_and_step9_document_the_1b_properties_gates_and_rollback():
    s5 = section(doc_text(), "Step 5:")
    # 8,371 rows and the md_anchors example come from the W1 Step 0 output (sha256 d2389c73…)
    for needle in ("curated_sources", "supp_anchors", "md_anchors", "no duplicate pair", "8,371",
                   "`1ch 10:?>1sa 31:1-13`"):
        assert needle in s5, needle
    assert "8,209" not in s5 and "mrk 1:?>psa 2:7" not in s5
    s9 = section(doc_text(), "Step 9:")
    for needle in ("--dry-run", "同向", "250,358", "249,434", "924", "250,366", "created 0",
                   "xref_probe.py fingerprint --target staging --expect", "從 Step 5",
                   "curated 邊至少一條", "不在指紋內", "validate_output"):
        assert needle in s9, needle
    assert "DELETE r" not in s9


def test_10_6_lists_the_hard_1b_checks_with_their_w1_values():
    s106 = section(doc_text(), "10.6")
    for needle in ("H8", "R4", "R11", "250,358", "unflagged", "misaligned_any_verse"):
        assert needle in s106, needle


def test_r2_runs_the_xref_checks_and_the_merged_allowlist_gate():
    r2 = section(staging_text(), "R2")
    for needle in ("xref_provenance", "mention_count", "kg_diff_allow_batch1w1.yaml --fail-on-unused",
                   "不能再當閘門重跑", "xref_probe.py expect", "created 0",
                   "xref_probe.py fingerprint --target staging --expect",
                   "xref_probe.py deploy-guard --container bible_rag_backend_staging", "--edges",
                   "HEAD 已提交的檔案（`git show HEAD:`，不看工作目錄）", "expected_edges.jsonl 約 20 MB"):
        assert needle in r2, needle
    assert "每個檔約 2 MB" not in r2


def test_r2_preregisters_the_xref_expectation_before_the_rebuild_and_only_rechecks_it():
    # decision O5, plan §3: the expect file and 1B's fragment exist before W1 step 2; the
    # rebuild recomputes the expectation into bak/ and compares it, never rewriting the registered file
    r2 = section(staging_text(), "R2")
    commands = _commands(r2)
    recheck = "--out bak/$D/xref_probe/xref_rebuild.json"
    expects = [c for c in commands if "xref_probe.py expect" in c]
    assert len(expects) == 2, expects
    assert "--out config/kg_expect/batch1_w1/xref.json" in expects[0] and recheck in expects[1], expects
    _in_order(commands, ("xref_probe.py expect", "xref_probe.py allow", recheck,
                         "cmp bak/$D/xref_probe/xref_rebuild.json config/kg_expect/batch1_w1/xref.json"))
    for needle in ("事前登記", "第 2 步（staging 重建）之前", "不可覆寫登記的期望檔", "第 4 步經 Kay 核可"):
        assert needle in r2, needle
    assert "第 4 步經 Kay 核可才 commit" not in r2 and "**建置之前**" not in r2
    r1 = section(staging_text(), "R1")
    assert "事前登記" in r1 and "R2「W1 的交叉引用檢查」第 1 項" in r1
    s9 = section(doc_text(), "Step 9:")
    assert "期望檔在建置前產生" not in s9 and "第 2 步之前登記" in s9


def test_r2_generates_the_1b_allowlist_fragment_and_leaves_mention_count_to_1a():
    # 1B's fragment comes from xref_probe allow, never from retyped prose; the four
    # K10 mention_count entries come only from 1A's residuals_allow.yaml (decision O2)
    r2 = section(staging_text(), "R2")
    commands = _commands(r2)
    allow = " ".join(commands[_first(commands, "xref_probe.py allow")].split())
    assert ("xref_probe.py allow --expect config/kg_expect/batch1_w1/xref.json "
            "--out config/kg_expect/batch1_w1/xref_allow.yaml") in allow, allow
    assert _first(commands, "xref_probe.py expect") < _first(commands, "xref_probe.py allow")
    assert "mention_count 段的 4 筆 K10 殘差（第 0 批就有，加了這一段才看得到）只來自 1A 的 `residuals_allow.yaml`" in r2
    for typed in ("−249,502", "+249,434", "−774", "event:shanshangbaoxun", "event:baoluoxushuguizhudejingguo",
                  "event:baoluoxushuguizhujingguo", "person:yeteluo"):
        assert typed not in r2, typed


W1_FRAGMENTS = ("relations_allow.yaml", "residuals_allow.yaml", "xref_allow.yaml")


def test_r2_merges_the_w1_fragments_at_the_yaml_level_before_the_rebuild():
    # a cat of whole fragments keeps only the last `allow:`; --merge-out joins the lists
    r2 = section(staging_text(), "R2")
    commands = _commands(r2)
    merge = " ".join(commands[_first(commands, "diff_kg.py --merge-out")].split())
    assert merge.endswith("diff_kg.py --merge-out config/kg_diff_allow_batch1w1.yaml " + " ".join(
        f"--allow config/kg_expect/batch1_w1/{name}" for name in W1_FRAGMENTS)), merge
    for needle in ("不可用 `cat` 串接", "條數等於各片段之和", "sha256 記進 W1 紀錄", "第 2 步（staging 重建）之前",
                   "第 1 批起預先登錄，不依 R2 的 diff 建立"):
        assert needle in r2, needle
    assert "片段串接而成" not in r2 and "R2 時依實際 diff 建立，與該批紀錄一起 commit" not in r2
    help_words = " ".join(help_text("diff_kg").split())
    assert "--merge-out" in help_words and "repeated mapping key" in help_words


def test_r2_and_diff_kg_help_say_a_repeated_allow_key_is_an_error():
    # --merge-out joins the fragments' lists: an overlap fails at the merge, not as unused at R2
    assert "同一個 section 下逐字相同的 key" in section(staging_text(), "R2")
    assert "same section and key" in " ".join(help_text("diff_kg").split())


ROLLBACK_TAR = "bak/$D/images/backend_kg-pre-batch1-w1.tar.gz"
ROLLBACK_ID = "bak/$D/images/backend_kg-pre-batch1-w1.id"
W1_ID_FILE = "bak/$D/images/backend_w1.id"
SMOKE_JSON = "results_quick/w1_step1_smoke.json"
D_GUARD = ': "${D:?set D to the W1 R0 date}"'


def _in_order(commands: list[str], keys) -> list[int]:
    missing = [key for key in keys if not any(key in command for command in commands)]
    assert not missing, (missing, commands)
    positions = [_first(commands, key) for key in keys]
    assert positions == sorted(positions), (keys, commands)
    return positions


def _blocks(text: str) -> list[list[str]]:
    """_commands of each fenced block, in order."""
    return [_commands(f"```\n{block}```") for block in re.findall(r"```[a-z]*\n(.*?)```", text, re.S)]


def _assert_fail_closed(block: list[str], last_echo: str, options: str = "set -eu -o pipefail") -> None:
    """A subshell under set -e: any failing line stops it before its closing echo. A test chained
    with && or || would not stop it (set -e ignores all but the last command of such a list)."""
    assert block[:3] == ["(", options, D_GUARD] and block[-2:] == [f"echo '{last_echo}'", ")"], block
    assert not [c for c in block if c.startswith("test ") and re.search(r"&&|\|\|", c)], block


def test_w1_step1_ships_the_backend_first_and_gates_on_the_exact_compare():
    step1 = section(staging_text(), "W1 升版第 1 步")
    keys = ("kg-pre-batch1-w1", "docker tag bible_rag-backend:w1 bible_rag-backend:latest", "up -d --no-deps",
            "smoke20_ids.txt", "deploy-guard --container bible_rag_backend", "probes.xref_measure",
            "predict", "compare")
    _in_order(_commands(step1), keys)
    for needle in ("087ab0d", "9bc112a6", "1,279", "57/262", "5,820"):
        assert needle in step1, needle
    record = next(line for line in step1.splitlines() if line.startswith("- W1 紀錄"))
    for needle in ("backend_w1.id", "backend_kg-pre-batch1-w1.id", "sha256"):
        assert needle in record, needle


def test_w1_step1_saves_once_then_deploys_in_fail_closed_blocks_before_verifying():
    save, deploy, verify = _blocks(section(staging_text(), "W1 升版第 1 步"))
    # noclobber: a re-run cannot overwrite the recorded rollback id or the archive
    _assert_fail_closed(save, "rollback image saved", "set -eu -o pipefail -o noclobber")
    _assert_fail_closed(deploy, "prod runs :w1")
    assert "smoke20_ids.txt" in verify[0], verify


def test_w1_step1_pins_and_saves_the_rollback_image_before_switching():
    # handoff §4: on 2026-10-05 `docker image prune -a` removed tagged rollback images
    save = _blocks(section(staging_text(), "W1 升版第 1 步"))[0]
    _in_order(save, (
        f"W1=$(cat {W1_ID_FILE})", "PROD=$(docker inspect -f '{{.Image}}' bible_rag_backend)",
        'test "$PROD" != "$W1"', f"test ! -e {ROLLBACK_TAR}", f'echo "$PROD" > {ROLLBACK_ID}',
        'docker tag "$PROD" bible_rag-backend:kg-pre-batch1-w1',
        "docker create --name bible_rag_backend_kg_pre_batch1_w1 bible_rag-backend:kg-pre-batch1-w1",
        f"docker save bible_rag-backend:kg-pre-batch1-w1 | gzip > {ROLLBACK_TAR}.part",
        f"gunzip -c {ROLLBACK_TAR}.part | tar -tf - >/dev/null", f"mv {ROLLBACK_TAR}.part {ROLLBACK_TAR}",
        "(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)"))
    r0 = section(staging_text(), "R0")
    assert "docker save" in r0 and "W1 升版第 1 步" in r0


def test_w1_step1_deploys_the_r2_tested_image_and_waits_for_health():
    r2 = _commands(section(staging_text(), "R2"))
    record = f"docker image inspect -f '{{{{.Id}}}}' bible_rag-backend:w1 > {W1_ID_FILE}"
    up = _in_order(r2, ("w1_image.yml build backend", record, "w1_image.yml up -d backend-staging"))[2]
    assert W1_ID_FILE in r2[up + 1] and "bible_rag_backend_staging)" in r2[up + 1], r2[up + 1]
    step1 = section(staging_text(), "W1 升版第 1 步")
    deploy = _blocks(step1)[1]
    # the saved rollback and an unchanged :w1 gate the retag; prod must then run the R2 id
    up = _in_order(deploy, (
        f"W1=$(cat {W1_ID_FILE})", f"PRE=$(cat {ROLLBACK_ID})",
        "grep -qF ' ./images/backend_kg-pre-batch1-w1.tar.gz' bak/$D/SHA256SUMS",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend_kg_pre_batch1_w1)\" = \"$PRE\"",
        "test \"$(docker image inspect -f '{{.Id}}' bible_rag-backend:w1)\" = \"$W1\"",
        "docker tag bible_rag-backend:w1 bible_rag-backend:latest", "docker compose up",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend)\" = \"$W1\""))[6]
    assert {"--no-deps", "--no-build", "--wait"} <= set(deploy[up].split()), deploy[up]
    assert not [c for c in _commands(step1) if re.search(r"(?<![\w-])--build\b", c) or c.startswith("curl")]


def test_w1_step1_smoke_cannot_pass_on_a_stale_result_and_checks_pred_trans():
    commands = _commands(section(staging_text(), "W1 升版第 1 步"))
    parts = [part.strip() for part in commands[_first(commands, "smoke20_ids.txt")].split("&&")]
    assert parts[1] == f"rm -f {SMOKE_JSON}", parts
    assert parts[2].startswith("uv run python quick_retrieval_eval.py") and SMOKE_JSON in parts[3], parts
    compare = ("xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_step1.json "
               "--measured bak/20261005_w1_1b_evidence/pred_trans.json")
    _in_order(commands, ("xref_probe.py predict", compare))
    readme = read(ROOT / "evaluation" / "experiments" / "2026-10-05_kg_w1" / "README.md")
    assert f"rm -f {SMOKE_JSON}" in readme and "up -d --build backend" not in readme


def test_xref_ab_window_restarts_staging_on_w1_and_reports_ci_by_stratum():
    # R2 item 3 stops backend-staging; plan §5.2 wants Δvrec CI and win/loss, in-sample apart from held-out
    ab = section(staging_text(), "W1 升版第 1、2 步之間")
    restart, *rest = _blocks(ab)
    _assert_fail_closed(restart, "both arms run :w1")
    _in_order(restart, (
        f"W1=$(cat {W1_ID_FILE})",
        "test \"$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j_staging)\" = healthy",
        "> /tmp/w1_image.yml",
        "-f /tmp/w1_image.yml up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)\" = \"$W1\"",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend)\" = \"$W1\""))
    evals = [command for block in rest for command in block]
    # a bare `cd evaluation` would leave the operator in evaluation/ for step 2's repo-root paths
    assert evals and all(c.startswith("(cd evaluation && ") and c.endswith(")") for c in evals), evals
    _in_order(evals, ("rm -f results_quick/xref_old_w1.json results_quick/xref_new_w1.json", "--label xref_old_w1",
                      "BACKEND_URL=http://localhost:8001", "xref_ab_slice.py",
                      "ab_compare.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json"))
    for needle in ("95% CI", "W/L", "`[legacy]`", "`[expanded]`", "held-out",
                   "](records/2026-10-05_kg_batch1_w0_results.md)「補記"):
        assert needle in ab, needle
    assert "§9" not in ab


def test_w1_data_load_starts_with_the_deploy_guard():
    step2 = section(staging_text(), "W1 升版第 2 步")
    first = _commands(step2)[0]
    assert re.search(r"xref_probe\.py deploy-guard --container bible_rag_backend$", first), first
    assert "不載入" in step2
    # the guard's timeout as its --help states it: a hung docker exec stops the load, never stalls it
    seconds = re.search(r"GUARD_TIMEOUT_S \((\d+) s\)", " ".join(help_text("xref_probe").split()))
    assert seconds and f"`timed out after {seconds[1]} s`" in step2


def test_r4_and_r5_cover_the_xref_promotion():
    r4 = section(staging_text(), "R4")
    for needle in ("xref_probe.py fingerprint --target prod --expect", "probes.xref_measure",
                   "H8", "R11", "sec3_kg.tex", "appendix.tex", "sec6_experiments.tex"):
        assert needle in r4, needle
    r5 = section(staging_text(), "R5")
    for needle in ("kg-pre-batch1-w1", "不可先於資料", "deploy-guard", "760", "86/262"):
        assert needle in r5, needle


def test_r4_ratchets_the_whole_wave_once_with_the_merged_allowlist():
    import validate_kg as vk
    r4 = section(staging_text(), "R4")
    ratchets = [c for c in _commands(r4) if "--ratchet" in c or "--accept" in c]
    assert ratchets == ["uv run --project scripts python scripts/validate_kg.py --live --target prod "
                        "--ratchet --accept W,R1,R11"], ratchets
    assert {"W", "R1", "R11"} <= set(vk.CHECKS)
    for needle in ("H8.no_provenance 916 → 0", "H8.unflagged 250,418 → 0", "kg_diff_allow_batch1w1.yaml"):
        assert needle in r4, needle
    assert "`--accept R11`" not in r4


U3_GREP = "grep -n '250,418\\|319,988\\|142 條\\|916 條' README.md evaluation/README.md docs/*.md"


def test_r4_u3_names_every_doc_the_count_grep_hits():
    # line lists drift; the grep recipe finds the docs that state the counts W1 changes
    r4 = section(staging_text(), "R4")
    u3 = r4[r4.index("**R4 之後的文件更新（U3）**"):]
    assert U3_GREP in _commands(u3), _commands(u3)
    pattern = re.compile(U3_GREP.split("'")[1].replace("\\|", "|"))
    targets = [ROOT / "README.md", ROOT / "evaluation" / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    hits = [p.relative_to(ROOT).as_posix() for p in targets if pattern.search(read(p))]
    prose = mask_code(u3)
    missing = [rel for rel in hits if not re.search(rf"(?<![\w/]){re.escape(rel)}", prose)]
    assert {"README.md", "docs/ARCHITECTURE.md", "docs/kg_construction_overview.md"} <= set(hits), hits
    assert not missing, missing


def test_staging_doc_headings_are_unique():
    # a repeated heading gets the same markdown anchor as the first one
    names = headings(staging_text())
    assert len(names) == len(set(names)), sorted({n for n in names if names.count(n) > 1})


def test_r3_and_r5_compose_runs_without_deps_from_a_clean_main_checkout_shell():
    # a shell that sourced staging.env would make compose recreate prod postgres (POSTGRES_DB)
    for name in ("R3", "R5"):
        ups = [s for s in code_snippets(section(staging_text(), name)) if "docker compose up" in s]
        assert len(ups) >= 2 and all("--no-deps" in s.split() for s in ups), (name, ups)
    r5 = section(staging_text(), "R5")
    for needle in ("主 checkout", "乾淨", "staging.env", "POSTGRES_DB"):
        assert needle in r5, needle


def test_r5_rolls_back_to_the_recorded_image_id_and_reloads_it_when_pruned():
    w1 = next(b for b in _blocks(section(staging_text(), "R5")) if "docker load" in " ".join(b))
    _assert_fail_closed(w1, "prod runs kg-pre-batch1-w1")
    # by id, not by tag: a moved tag still rolls back to the image recorded at step 1
    _in_order(w1, (
        f"PRE=$(cat {ROLLBACK_ID})", f'docker image inspect "$PRE" >/dev/null || gunzip -c {ROLLBACK_TAR} | docker load',
        'docker tag "$PRE" bible_rag-backend:kg-pre-batch1-w1',
        "docker tag bible_rag-backend:kg-pre-batch1-w1 bible_rag-backend:latest",
        "docker compose up -d --no-deps --no-build --wait --wait-timeout 300 backend",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend)\" = \"$PRE\""))


def test_staging_compose_sends_new_backend_code_to_a_separate_tag():
    words = " ".join(line.lstrip("# ").strip() for line in read(ROOT / "docker-compose.staging.yml").splitlines())
    assert "`docker compose build backend` first" not in words
    for needle in ("bible_rag-backend:w1", "docs/staging_promotion.md R2"):
        assert needle in words, needle


def test_evaluation_readme_tree_lists_the_w1_xref_ab_tool_and_experiment_dir():
    tree = read(ROOT / "evaluation" / "README.md").split("```", 2)[1]
    for needle in ("xref_ab_slice.py", "experiments/", "2026-10-05_kg_w1/"):
        assert needle in tree, needle


@pytest.mark.parametrize("path", MECHANISM_DOCS, ids=_name)
def test_mechanism_docs_describe_the_curated_flag_not_the_votes_sentinel(path):
    stale = [line for line in read(path).splitlines()
             if ("999" in line and re.search(r"votes|哨兵|sentinel|curated|手工", line))
             or re.search(r"916 (?:條 )?curated", line)]
    assert not stale, stale


# ---------------------------------------------------------------- batch 1A: the W1 rebuild chain

def _rebuild_chain(text: str) -> tuple[list[str], list[list[str]]]:
    """The bold `**0 → …**` line's steps and the cells of the table right under it, found the
    way test_export_live_state finds them (first such line; a non-table line ends the table)."""
    chain = re.search(r"^\s*\*\*(0 → .+?)\*\*\s*$", text, re.M)
    assert chain, "no **0 → …** chain line"
    rows = []
    for line in text[chain.end():].lstrip("\n").splitlines():
        if not line.strip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] and cells[0] != "順序" and not set(cells[0]) <= {"-", ":"}:
            rows.append(cells)
    return [step.strip() for step in chain.group(1).split("→")], rows


_STEP1 = re.compile(r"^1(?![\d.])")   # a Step-1 label (1, 1(merge)), not 10.x


def test_w1_chain_skips_step1_and_runs_6_05_before_any_store_write():
    # plan §6 #10: a W1 merge drops person:liuer; 6.05 is offline, so its input errors stop the
    # chain before Step 3/5 write anything. Decision O3: validate_output and 1B's xref checks are in it.
    labels, rows = _rebuild_chain(doc_text())
    table = [row[0] for row in rows]
    for steps in (labels, table):
        assert not [s for s in steps if _STEP1.match(s) or s.startswith("10.3") or "–" in s], steps
        order = _positions(steps, ("check_merged_inputs", "6.05", "3", "5", "6.1", "10.5", "7"))
        assert order == sorted(order), steps
    order = _positions(labels, ("check_step0", "validate_output（必跑）", "xref_probe expect", "check_merged_inputs"))
    assert order == sorted(order), labels
    step9 = labels[_positions(labels, ("9",))[0]]
    assert "連跑兩次" in step9 and "fingerprint --expect" in step9, step9
    assert _positions(table, ("0", "xref_probe expect", "check_merged_inputs")) == [0, 1, 2], table
    command = {row[0]: row[1] for row in rows}
    assert "validate_output.py output" in command["0"] and "（選）" not in " ".join(rows[0]), rows[0]
    assert "xref_rebuild.json" in command["xref_probe expect"], command["xref_probe expect"]
    assert "fingerprint --target staging --expect" in command["9"], command["9"]
    assert command["6.1"] == "`scripts/import_relations_neo4j.py`", command["6.1"]   # no --replace, default input
    assert "bible_entities_v3" in " ".join(rows[table.index("8a")]), rows[table.index("8a")]
    assert "person:liuer" in section(doc_text(), "執行順序")


def test_fresh_chain_runs_validate_output_and_6_05_and_leaves_10_3_out():
    fresh = next(line for line in section(doc_text(), "執行順序").splitlines() if line.startswith("- **從零**"))
    assert "→ `validate_output.py`（必跑" in fresh and "（選）" not in fresh, fresh
    assert "→ 5 → 6 → 6.05 → 6.1 → 8a → 9 → 10.1 → 10.2 → 10.4 → 10.5 → 7 → 8b → 10.6" in fresh, fresh
    assert "10.3" not in fresh and "10.1–10.5" not in fresh, fresh


def test_readme_pipeline_runs_6_05_before_6_1_and_keeps_10_3_legacy_only():
    block = section(read(ROOT / "README.md"), "Data Pipeline")
    commands = _commands(block)
    _in_order(commands, ("relation_extraction.extract_relations", "relation_extraction.relation_postprocess",
                         "import_relations_neo4j.py", "backfill_aliases.py", "cleanup_noise_entities.py",
                         "backfill_head_events.py", "backfill_manual_patches.py --apply"))
    assert not [c for c in commands if "backfill_event_relations" in c], commands
    assert "# python scripts/backfill_event_relations.py --legacy-cooccurrence" in block
    assert "--legacy-cooccurrence" in help_text("backfill_event_relations")
    assert "共現關係搶救、" not in block


def test_steps_6_to_10_document_6_05_the_new_6_1_and_the_retired_10_3():
    text = doc_text()
    s605 = section(text, "Step 6.05:")
    for needle in ("relations_clean.jsonl", "relations_clean.report.json", "--rules none", "enabled: false",
                   "752", "772", "319", "5,696", "5,616", "661cfc62", "bbc5c830", "cmp", "kin_review"):
        assert needle in s605, needle
    s6 = section(text, "Step 6:")
    assert "R2 Rule Classifier" not in s6 and "--inverse" in s6 and "priors only" in s6
    s61 = section(text, "Step 6.1:")
    assert "idempotent" not in s61 and "output/relations.jsonl" not in s61 and "--replace" in s61
    s7 = section(text, "Step 7:")
    assert "（1A、1C、1D）" not in s7 and "第 1A、1B 批" in s7
    s10 = section(text, "Step 10:")
    assert not [c for c in _commands(s10) if "backfill_event_relations" in c]
    assert "backfill_event_relations.py --legacy-cooccurrence" in s10 and "共現關係搶救、" not in s10
    assert "bible_entities_v3" in section(text, "Step 8:")


def test_10_6_lists_the_hard_1a_checks_and_their_w1_gates():
    s106 = section(doc_text(), "10.6")
    for needle in ("第 1A 批起的硬門檻：H3、H9、H11、R6", "D1", "jq -e '.failures == [] and .regressions - [\"R1\"] == []'",
                   "residuals_expected.json", "relations_expected.json", "PROBES", "bible_entities_detB",
                   "check_edge_set.py --target staging --expect config/kg_expect/batch1_w1/relations_expected.json"):
        assert needle in s106, needle


# ---------------------------------------------------------------- plan

_ORDER = ("5", "6.1", "8a", "10.1", "7", "8b", "10.6")
_MOVED_BATCHES = ("1A", "1B", "1C", "1D", "2A", "2B", "2C", "2D", "延後-A", "延後-B", "延後-C")


def _positions(labels, keys):
    return [next(i for i, label in enumerate(labels) if label.startswith(key)) for key in keys]


def _batch_heading(batch: str) -> re.Pattern:
    return re.compile(rf"^(?:第 {re.escape(batch)} 批|{re.escape(batch)})：")


def test_plan_target_pipeline_runs_k7_after_curated_overlay():
    block = section(plan_text(), "3.2")
    lines = block.splitlines()
    kc = next(i for i, line in enumerate(lines) if line.startswith("Kc "))
    k7 = next(i for i, line in enumerate(lines) if line.startswith("K7 "))
    assert kc < k7
    assert "freeze-grounded" in next(line for line in lines if line.startswith("K1b"))


def test_plan_batch0_chain_is_the_implemented_order():
    b0 = section(plan_text(), "第 0 批")
    line = next(line for line in b0.splitlines() if "**管線順序變更**" in line)
    labels = [s.strip() for s in line.split("改為", 1)[1].split("→")]
    positions = _positions(labels, _ORDER)
    assert positions == sorted(positions), labels
    assert "與原計畫的偏離與理由" in b0
    dev = b0[b0.index("與原計畫的偏離與理由"):]
    for needle in ("titles_sha", "10.5", "8a", "8b", "live"):
        assert needle in dev, needle
    assert "ner|grounded|merge" not in b0


def test_plan_section4_keeps_batch0_and_summarises_the_moved_batches():
    s4 = section(plan_text(), "4. 分批計畫")
    assert [h for h in headings(s4) if h.startswith("第 0 批")]
    assert "](2026-10-04_kg_data_layer_fix_plan_batches.md)" in s4
    plan_heads, batch_heads = headings(plan_text()), headings(batches_text())
    for batch in _MOVED_BATCHES:
        assert re.search(rf"^\| {re.escape(batch)} \|", s4, re.M), batch
        assert not [h for h in plan_heads if _batch_heading(batch).match(h)], batch
        assert [h for h in batch_heads if _batch_heading(batch).match(h)], batch
    assert "](2026-10-04_kg_data_layer_fix_plan.md)" in batches_text().split("\n## ", 1)[0]


def test_plan_batch1d_replays_after_10_5():
    d = section(batches_text(), "第 1D 批")
    line = next(line for line in d.splitlines() if "**管線順序變更**" in line)
    labels = [s.strip().strip("*") for s in line.split("：", 1)[1].split("→")]
    assert _positions(labels, ("10.5", "7(replay)", "8b", "10.6")) == sorted(
        _positions(labels, ("10.5", "7(replay)", "8b", "10.6"))), labels
    assert _positions(labels, ("8a",))[0] < _positions(labels, ("10.4",))[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

"""docs/build_database.md must match the scripts it tells people to run.

Every script name with flags in the doc is checked against that script's real
--help (and --stage/--target choices), so a renamed or removed flag fails here
instead of in the middle of a rebuild. Also pins the batch-0 rebuild order
(replay after the curated overlay) in both the doc and the fix plan.
"""
from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "build_database.md"
PLAN = ROOT / "docs" / "records" / "2026-10-04_kg_data_layer_fix_plan.md"
PY = str(ROOT / "scripts" / ".venv" / "bin" / "python")

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
}
_SCRIPT_RE = re.compile(r"\b(" + "|".join(sorted(HELP_ARGV, key=len, reverse=True)) + r")(?:\.py)?\b")
_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


@functools.lru_cache(maxsize=None)
def help_text(script: str) -> str:
    out = subprocess.run(HELP_ARGV[script], cwd=ROOT, capture_output=True, text=True, timeout=300)
    return out.stdout + out.stderr


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def plan_text() -> str:
    return PLAN.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """Text from a markdown heading to the next heading of the same or higher level."""
    # mask fenced code so shell comments ("# ...") are not taken for headings
    masked = re.sub(r"```.*?```", lambda c: re.sub(r"[^\n]", "x", c.group(0)), text, flags=re.S)
    m = re.search(rf"^(#+) {re.escape(heading)}.*$", masked, re.M)
    assert m, heading
    level = len(m.group(1))
    nxt = re.compile(rf"^#{{1,{level}}} ", re.M).search(masked, m.end())
    return text[m.start(): nxt.start() if nxt else len(text)]


def code_snippets(text: str):
    """Inline code spans and fenced-block command lines (continuations joined)."""
    fenced = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    for block in fenced:
        yield from block.replace("\\\n", " ").splitlines()
    yield from re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))


# ---------------------------------------------------------------- build_database.md

def test_doc_stays_within_800_lines():
    assert len(doc_text().splitlines()) <= 800


def test_every_documented_flag_exists_in_that_scripts_cli():
    missing = []
    for snippet in code_snippets(doc_text()):
        scripts = set(_SCRIPT_RE.findall(snippet))
        if len(scripts) != 1:
            continue
        (script,) = scripts
        args = snippet[_SCRIPT_RE.search(snippet).end():].split("#", 1)[0]
        for flag in _FLAG_RE.findall(args):
            if flag not in help_text(script):
                missing.append((script, flag, snippet.strip()))
    assert not missing, missing


def test_documented_stage_and_target_values_are_valid_choices():
    text = doc_text()
    stages = set(re.findall(r"--stage ([a-z-]+)", text))
    assert stages <= {"ner", "freeze-grounded", "merge"}, stages
    targets = set(re.findall(r"--(?:target|a|b) ([a-z]+)", text))
    assert targets <= {"prod", "staging"}, targets


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


def test_r0_tarball_carries_the_ner_half_and_its_manifest():
    r0 = section(doc_text(), "R0")
    files = " ".join(re.findall(r'FILES="([^"]*)"', r0))
    for name in ("ner_entities.jsonl", "ner_mentions.jsonl", "ner_manifest.json"):
        assert name in files, name
    assert "--stage ner" in r0


def test_staging_precheck_requires_the_staging_target():
    text = doc_text()
    assert "scripts/kg_target.py --require-staging neo4j postgres qdrant" in text
    assert "kg_target.assert_target(\"neo4j\", \"postgres\", \"qdrant\")' && echo" not in text


def test_diff_kg_command_allowlist_and_clean_shell_are_documented():
    text = doc_text()
    r2 = section(text, "R2")
    s106 = section(text, "10.6")
    for part in (r2, s106):
        assert re.search(r"diff_kg\.py --a prod --b staging --allow config/kg_diff_allow_", part), part[:200]
    assert "乾淨" in r2 and "staging.env" in r2
    assert "kg_diff_allow_batch0.yaml" in r2
    row = next(line for line in text.splitlines() if line.startswith("| tools/diff_kg.py"))
    for flag in ("--a", "--b", "--allow"):
        assert flag in row, flag
    assert "參數以 `--help` 為準" not in s106


def test_validate_kg_exit_code_comment_covers_error_and_unmeasured():
    s106 = section(doc_text(), "10.6")
    assert "unmeasured" in s106 and "error" in s106


def test_r4_rationale_reflects_the_prod_guard():
    r4 = section(doc_text(), "R4")
    assert "不擋「prod 檢查讀到 staging」" not in r4
    assert "拒絕" in r4 and "export_event_registry" in r4


def test_step7_explains_the_expected_stale_procedure():
    s7 = section(doc_text(), "Step 7:")
    for needle in ("1A", "1C", "1D", "--fail-on-stale", "紀錄", "kg_diff_allow"):
        assert needle in s7, needle


def test_inventory_rows_are_current():
    lines = doc_text().splitlines()
    ci = next(line for line in lines if line.startswith("| check_identity.py"))
    assert "--target prod" in ci


# ---------------------------------------------------------------- plan

_ORDER = ("5", "6.1", "8a", "10.1", "7", "8b", "10.6")


def _positions(labels, keys):
    return [next(i for i, label in enumerate(labels) if label.startswith(key)) for key in keys]


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


def test_plan_batch1d_replays_after_10_5():
    d = section(plan_text(), "第 1D 批")
    line = next(line for line in d.splitlines() if "**管線順序變更**" in line)
    labels = [s.strip().strip("*") for s in line.split("：", 1)[1].split("→")]
    assert _positions(labels, ("10.5", "7(replay)", "8b", "10.6")) == sorted(
        _positions(labels, ("10.5", "7(replay)", "8b", "10.6"))), labels
    assert _positions(labels, ("8a",))[0] < _positions(labels, ("10.4",))[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

"""W1 integration pins of the staging runbook, docs/staging_promotion.md.

The W1 promotion runs from the main checkout once both streams are merged, so
these pins span 1A and 1B. R0 item 0: the pre-merge commit of the main
checkout's branch is tagged kg-pre-batch1-w1, w1/1a (which holds w1/1b) is
merged into it, the three suites pass and the status is clean but for one
named untracked file; R0-R5 then run from that checkout, and the W1 record
keeps HEAD at pre-registration, at the rebuild and at the R2 image build.
W1 promotion step 2, the only step that writes prod data, is one fail-closed
block: the deploy-guard first, prod still on the R2-tested image, the staging
re-verified READ against the registered expectations, a complete dump with
its sha256 recorded, and only then prod stopped and loaded; the generic R3
step 1 stays for the other batches. The step 1-2 window adds K10's
report-only graph_event slice (the GT questions whose text holds a trigger of
the K10 events, both arms on :w1) and plan §5.2's conditional answer side,
and names every cause of xref_ab_slice's exit 2, the empty kg_xref slice
included.
"""
from __future__ import annotations

import functools
import json
import re
import subprocess

import pytest

from test_docs_alignment import (_FLAG_RE, D_GUARD, ROOT, _assert_fail_closed, _blocks, _commands, _first,
                                 _in_order, read, section, staging_text)

MAIN = "/home/kenzx0521/Bible_RAG"
BRANCH = "feat/graph-strategy-gating"
ALLOWED_UNTRACKED = "?? docker-compose.yml.bak-20260730-160725"
EXPECT = "config/kg_expect/batch1_w1/"
DUMP = "bak/$D/promote/neo4j_staging.dump"
HEAD_FILE = "bak/$D/images/backend_w1.head"
W1_DIR = ROOT / "evaluation" / "experiments" / "2026-10-05_kg_w1"
GE_IDS = "experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt"
WINDOW = "W1 升版第 1、2 步之間"
# K10 (plan §7): the batch-0 mention_count residual of these Events ships with W1. The
# fourth residual entity, person:yeteluo, is no Event, so graph_event never reaches it.
K10_EVENTS = ("event:shanshangbaoxun", "event:baoluoxushuguizhudejingguo", "event:baoluoxushuguizhujingguo")


def _item(text: str, number: str) -> str:
    """One top-level item of a numbered markdown list, up to the next one."""
    m = re.search(rf"^{number}\. .*?(?=^\d+\. |\Z)", text, re.S | re.M)
    assert m, number
    return m.group(0)


# ---------------------------------------------------------------- R0 item 0: the checkout

def test_r0_item_0_tags_the_pre_merge_commit_and_merges_both_streams_into_main():
    r0 = section(staging_text(), "R0")
    item = _item(r0, "0")
    assert r0.index(item) < r0.index("1. `git tag kg-pre-<批次>`")
    for needle in (f"`{MAIN}`", f"`{BRANCH}`", "`w1/1a`", "`w1/1b`", "R0–R5", "`git status --porcelain`",
                   f"`{ALLOWED_UNTRACKED}`", "合併前的 commit", "W1 紀錄"):
        assert needle in item, needle
    merge, suites = _blocks(item)
    assert merge[0] == f"cd {MAIN}", merge
    for block in (merge[1:], suites):
        assert block[:3] == ["(", "set -eu -o pipefail", f'test "$(git rev-parse --show-toplevel)" = {MAIN}'], block
        assert block[-2].startswith("echo ") and block[-1] == ")", block
    # the tag names the commit before the merge; --no-ff keeps it the merge's first parent
    _in_order(merge, (f'test "$(git branch --show-current)" = {BRANCH}', "PRE=$(git rev-parse HEAD)",
                      'git tag kg-pre-batch1-w1 "$PRE"', "git merge --no-ff --no-edit w1/1a"))
    _in_order(suites, (
        "git merge-base --is-ancestor w1/1b HEAD",
        'test "$(git rev-parse kg-pre-batch1-w1)" = "$(git rev-parse HEAD^1)"', "scripts/tests/run.sh",
        "backend/.venv/bin/python -m pytest backend/tests -q",
        "(cd evaluation && uv run --offline python -m pytest tests -q)",
        "S=$(git status --porcelain)", f"case \"$S\" in ''|'{ALLOWED_UNTRACKED}') ;;"))
    assert "第 0 項" in _item(r0, "1")


def test_the_w1_record_keeps_head_at_registration_rebuild_and_image_build():
    text = staging_text()
    item = _item(section(text, "R0"), "0")
    for needle in ("`git rev-parse HEAD`", "事前登記", "R1 第 5 項", f"`{HEAD_FILE}`"):
        assert needle in item, needle
    assert "git rev-parse HEAD" in _item(section(text, "R1"), "5")
    prereg = next(line for line in section(text, "W1 的交叉引用檢查").splitlines()
                  if line.strip().startswith("期望檔與片段跟 1A 的期望檔一樣"))
    assert "git rev-parse HEAD" in prereg, prereg
    r2 = _commands(section(text, "R2"))
    _in_order(r2, ("w1_image.yml build backend", f"git rev-parse HEAD > {HEAD_FILE}",
                   "w1_image.yml up -d --no-deps backend-staging"))


# ---------------------------------------------------------------- W1 step 2: the prod data load

def test_w1_step2_is_one_fail_closed_block_that_dumps_completely_before_prod_stops():
    step2 = section(staging_text(), "W1 升版第 2 步")
    load = next(b for b in _blocks(step2) if any("database load" in c for c in b))
    _assert_fail_closed(load, "prod neo4j loaded")
    assert load[2] == D_GUARD and load[3].endswith("xref_probe.py deploy-guard --container bible_rag_backend"), load
    at = _in_order(load, (
        "W1=$(cat bak/$D/images/backend_w1.id)",
        "test \"$(docker inspect -f '{{.Image}}' bible_rag_backend)\" = \"$W1\"",
        f"xref_probe.py fingerprint --target staging --expect {EXPECT}xref.json",
        f"check_edge_set.py --target staging --expect {EXPECT}relations_expected.json",
        f"residuals_expect.py --a prod --b staging --check {EXPECT}residuals_expected.json",
        f"test ! -e {DUMP}", "docker stop -t 60 bible_rag_neo4j_staging",
        f"database dump neo4j --to-stdout > {DUMP}.part", f"test -s {DUMP}.part", f"mv {DUMP}.part {DUMP}",
        "(cd bak/$D && sha256sum ./promote/neo4j_staging.dump >> SHA256SUMS)",
        f"database load neo4j --from-stdin --overwrite-destination=true < {DUMP}"))
    stop_prod = load.index("docker stop -t 60 bible_rag_neo4j")   # exact: not the staging container
    assert at[-2] < stop_prod < at[-1] and load[at[-1] + 1] == "docker start bible_rag_neo4j", load
    for needle in ("唯一寫入 prod 資料", "`.part`", "SHA256SUMS", "R5", "`docker start bible_rag_neo4j_staging`"):
        assert needle in step2, needle
    assert "通過後才做上面 R3 第 1 步" not in step2


def test_r3_keeps_the_generic_neo4j_step_and_sends_w1_to_its_own_block():
    r3 = section(staging_text(), "R3")
    generic = r3[:r3.index("### W1 升版第 1 步")]
    note = next(line for line in generic.splitlines() if line.startswith("第 1 批 W1"))
    assert "第 2 步才做這裡的第 1 步" not in note and "「W1 升版第 2 步」" in note, note
    _in_order(_commands(generic), ("docker stop -t 60 bible_rag_neo4j_staging",
                                   "database dump neo4j --to-stdout > bak/$D/promote/neo4j_staging.dump",
                                   "database load neo4j --from-stdin"))


# ---------------------------------------------------------------- step 1-2 window: graph_event (K10)

def _k10_trigger_questions() -> list[str]:
    events = json.loads(read(ROOT / "backend" / "data" / "event_registry.json"))["events"]
    assert set(K10_EVENTS) <= {e["id"] for e in events}
    triggers = {t for e in events if e["id"] in K10_EVENTS for t in e["triggers"]}
    questions = json.loads(read(ROOT / "ground_truth.json"))["questions"]
    return [q["question_id"] for q in questions if any(t in q["question"] for t in triggers)]


def test_graph_event_ids_are_the_gt_questions_naming_a_k10_trigger():
    ids = (W1_DIR / "graph_event_k10_ids.txt").read_text(encoding="utf-8").split()
    assert ids and ids == _k10_trigger_questions(), ids
    readme = read(W1_DIR / "README.md")
    for needle in ("graph_event_k10_ids.txt", "K10", *K10_EVENTS, *ids):
        assert needle in readme, needle


def _window_evals() -> list[str]:
    return [c for block in _blocks(section(staging_text(), WINDOW))[1:] for c in block]


def test_window_runs_the_graph_event_slice_on_both_w1_arms_and_records_it_with_k10():
    window = section(staging_text(), WINDOW)
    evals = _window_evals()
    run = f"quick_retrieval_eval.py --ids-file {GE_IDS} --graph-strategies graph_event --top-k 5 --metric-k 6 --label"
    parts = [part.strip() for part in evals[_first(evals, "ge_old_w1")].split("&&")]
    assert parts == ["(cd evaluation", "rm -f results_quick/ge_old_w1.json results_quick/ge_new_w1.json",
                     f"uv run python {run} ge_old_w1",
                     f"BACKEND_URL=http://localhost:8001 uv run python {run} ge_new_w1)"], parts
    _in_order(evals, ("--label xref_new_w1", "--label ge_old_w1",
                      "ab_compare.py results_quick/ge_old_w1.json results_quick/ge_new_w1.json --label w1_graph_event"))
    for needle in ("K10", "保羅歸主", "山上寶訓", "只報告", "K10 的 accept", "重問"):
        assert needle in window, needle
    assert window.rindex("停掉 backend-staging") > window.index("w1_graph_event")


def test_window_names_every_xref_ab_slice_exit_2_cause():
    # an empty kg_xref slice (a legacy-100 run, a wrong --ids) once printed "0 → 0", the expected no gain
    bullet = next(line for line in section(staging_text(), WINDOW).splitlines()
                  if line.startswith("- xref_ab_slice 結束碼 2"))
    for needle in ("metric_version", "found_by", "`--ids` 檔不是 qid 清單", "kg_xref 切片在兩邊都沒有有效題", "不存報告"):
        assert needle in bullet, needle


def test_window_states_plan_5_2s_conditional_answer_side_run():
    bullet = next(line for line in section(staging_text(), WINDOW).splitlines() if line.startswith("- **答案端"))
    for needle in ("實質差異", "coverage", "faithfulness strict", "0.97", "0.060", "§5.2", "W1 紀錄"):
        assert needle in bullet, needle


@functools.lru_cache(maxsize=None)
def _eval_help(script: str) -> str:
    out = subprocess.run([str(ROOT / "evaluation" / ".venv" / "bin" / "python"), script, "--help"],
                         cwd=ROOT / "evaluation", capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.mark.parametrize("script", ("quick_retrieval_eval.py", "ab_compare.py", "xref_ab_slice.py"))
def test_window_evaluation_flags_exist_in_that_scripts_cli(script):
    flags = {flag for command in _window_evals() for part in command.split("&&") if script in part
             for flag in _FLAG_RE.findall(part.split(script, 1)[1])}
    assert flags and flags <= set(_FLAG_RE.findall(_eval_help(script))), (script, flags)

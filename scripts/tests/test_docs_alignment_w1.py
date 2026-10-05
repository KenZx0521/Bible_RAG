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
included. The review minors (docs_promotion) pin what the runbook's blocks
and sentences claim against the code and data they describe: the rollback
archive carries the prod image id, step 1 deploys only over that image or
:w1, R2 records the :w1 id in a fail-closed block, the smoke check reads the
applied-strategy tally, a failed ratchet run leaves baseline files to restore,
and K8's P1 rebuild never overwrites R2's gate report.
"""
from __future__ import annotations

import functools
import gzip
import inspect
import io
import json
import re
import shlex
import subprocess
import sys
import tarfile

import pytest
import validate_kg as vk
from scripts.tools import diff_kg as dk
from scripts.tools import xref_probe as xp

from test_docs_alignment import (_FLAG_RE, D_GUARD, ROOT, SMOKE_JSON, U3_GREP, W1_ID_FILE, _assert_fail_closed, _blocks,
                                 _commands, _first, _in_order, read, section, staging_text)

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


# ---------------------------------------------------------------- review minors (docs_promotion)

STEP1 = "W1 升版第 1 步"
PROD_ID = "sha256:" + "ab" * 32
SMOKE_PASS = "20 0 [] " + str({"event_registry": 20})   # what print() shows for the tally


def _bash(script: str, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True, timeout=60)


def _rollback_archive(root, member: str, suffix: str) -> None:
    """bak/x/images/ holding the rollback id file and a gzipped tar listing `member`."""
    images = root / "bak" / "x" / "images"
    images.mkdir(parents=True)
    (images / "backend_kg-pre-batch1-w1.id").write_text(PROD_ID + "\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name in ("oci-layout", member):
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
    (images / f"backend_kg-pre-batch1-w1.tar.gz{suffix}").write_bytes(gzip.compress(buf.getvalue()))


def _step1_bullet(start: str) -> str:
    return next(line for line in section(staging_text(), STEP1).splitlines() if line.startswith(start))


def test_r2_allowlist_bounds_cover_the_count_sections_and_mention_count():
    # M181: W1's residuals_allow.yaml bounds its four mention_count entries with an exact delta
    entry = {"key": "event:x", "reason": "r", "delta": -22}
    assert dk._entry_problem({**entry, "section": "mention_count"}) is None
    assert all(dk._entry_problem({**entry, "section": s}) for s in set(dk.SECTIONS) - set(dk.NUMERIC_SECTIONS))
    assert set(dk.NUMERIC_SECTIONS) == {*dk.COUNT_SECTIONS, "mention_count"}
    r2 = section(staging_text(), "R2")
    assert "計數類與 mention_count 最多再加一個 `delta`（b − a）或 `max_abs_delta`（其他段加 bound 直接報錯）" in r2


def test_r2_checks_the_registered_allowlist_sha256_right_before_the_w1_diff():
    # M313: the merged allowlist stays uncommitted until R4 (O5); its registered sha is the guard
    commands = _commands(section(staging_text(), "R2"))
    at = _first(commands, "kg_diff_allow_batch1w1.yaml --fail-on-unused")
    assert commands[at - 1] == f"sha256sum -c {EXPECT}kg_diff_allow_batch1w1.sha256", commands[at - 1]


def test_r2_scopes_the_uncommitted_change_claim_to_the_three_guard_files():
    # M293: deploy-guard compares GUARD_FILES only; any other uncommitted change still ships in the image
    xref = section(staging_text(), "W1 的交叉引用檢查")
    assert len(xp.GUARD_FILES) == 3 and all(f"`{name}`" in xref for name in xp.GUARD_FILES), xp.GUARD_FILES
    for needle in ("GUARD_FILES 這三個檔沒提交的改動即使建進 image 也會被擋下", "其他檔的改動 deploy-guard 看不到",
                   "建 image 前工作目錄要乾淨"):
        assert needle in xref, needle
    assert "（沒提交的改動即使建進 image 也會被擋下）" not in xref


def test_r2_item_3_builds_and_records_the_w1_image_in_a_fail_closed_block():
    # M307: an unset D, a missing :w1 (empty id file) or a missing staging container stops it before the measures
    blocks = _blocks(section(staging_text(), "W1 的交叉引用檢查"))
    build = next(b for b in blocks if any("w1_image.yml build backend" in c for c in b))
    _assert_fail_closed(build, "staging runs :w1")
    record = f"docker image inspect -f '{{{{.Id}}}}' bible_rag-backend:w1 > {W1_ID_FILE}"
    up = _in_order(build, ("w1_image.yml build backend", "mkdir -p bak/$D/images", record, f"test -s {W1_ID_FILE}",
                           "w1_image.yml up -d --no-deps backend-staging"))[-1]
    identity = f"test \"$(docker inspect -f '{{{{.Image}}}}' bible_rag_backend_staging)\" = \"$(cat {W1_ID_FILE})\""
    assert build[up + 1] == identity, build
    measure = blocks[blocks.index(build) + 1]
    assert measure[0].endswith("xref_probe.py deploy-guard --container bible_rag_backend_staging"), measure


@pytest.mark.parametrize("member, ok", [(f"blobs/sha256/{PROD_ID[7:]}", True), (f"./blobs/sha256/{PROD_ID[7:]}", True),
                                        (f"blobs/sha256/{'cd' * 32}", False), (f"blobs/sha256/{PROD_ID[7:]}0", False)])
def test_w1_step1_archive_check_requires_the_prod_image_id_blob(tmp_path, member, ok):
    # M302: R5 loads the archive back by this id (the index digest under the containerd store)
    save = _blocks(section(staging_text(), STEP1))[0]
    check = save[_first(save, "tar -tf -")]
    _rollback_archive(tmp_path, member, ".part")
    run = _bash(f"set -eu -o pipefail -o noclobber; D=x; PROD={PROD_ID}; {check}; echo ok", tmp_path)
    assert (run.returncode == 0 and run.stdout == "ok\n") is ok, run
    bullet = _step1_bullet("- **回滾 image 在換 image 之前保住**")
    for needle in ("`blobs/sha256/<id>`", "index digest", "`docker load`", "不加 `-q`"):
        assert needle in bullet, needle


@pytest.mark.parametrize("member, ok", [(f"blobs/sha256/{PROD_ID[7:]}", True), (f"blobs/sha256/{'cd' * 32}", False)])
def test_w1_step1_says_how_to_finish_when_only_the_sha256_append_failed(tmp_path, member, ok):
    # M306: a re-run of block 1 stops at `test ! -e …tar.gz`, block 2 at the SHA256SUMS grep
    bullet = _step1_bullet("- **第一段只做一次**")
    spans = re.findall(r"`([^`]+)`", bullet)
    recheck = next(span for span in spans if "tar -tf -" in span)
    append = "(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)"
    assert append in spans and append in _blocks(section(staging_text(), STEP1))[0], spans
    assert bullet.index(recheck) < bullet.index(append)
    for needle in ("SHA256SUMS 沒有它", "不要重跑第一段"):
        assert needle in bullet, needle
    _rollback_archive(tmp_path, member, "")
    run = _bash(f"D=x; {recheck}", tmp_path)
    assert (run.returncode == 0 and run.stdout == f"blobs/sha256/{PROD_ID[7:]}\n") is ok, run


@pytest.mark.parametrize("prod, ok", [("pre", True), ("w1", True), ("other", False), ("", False)])
def test_w1_step1_deploy_stops_unless_prod_runs_the_rollback_image_or_w1(tmp_path, prod, ok):
    # M303: prod could change between R0, block 1 and block 2 (an unrelated `up -d --build`)
    deploy = _blocks(section(staging_text(), STEP1))[1]
    case = deploy[_first(deploy, 'case "$P" in')]
    run = _bash(f"set -eu -o pipefail; PRE=pre; W1=w1; P={shlex.quote(prod)}; {case}; echo ok", tmp_path)
    assert (run.returncode == 0 and run.stdout == "ok\n") is ok, run
    bullet = _step1_bullet("- **上線的是 R2 測過的 image")
    assert "prod 仍是第一段記下的 id（重跑時已是 `backend_w1.id`）" in bullet, bullet


def test_w1_smoke_requires_the_default_path_to_apply_event_registry_alone(tmp_path):
    # M206: quick_retrieval_eval records the backend-reported tally under config.graph_strategies_applied
    assert '"graph_strategies_applied": applied_counts(applied_by_q)' in read(ROOT / "evaluation" / "quick_retrieval_eval.py")
    result = tmp_path / SMOKE_JSON
    result.parent.mkdir()
    result.write_text(json.dumps({"n": 20, "n_invalid": 0, "per_question": {f"q{i}": {"strategy_errors": []} for i in range(20)},
                                  "config": {"graph_strategies_applied": {"event_registry": 20}}}))
    for text in (section(staging_text(), STEP1), read(W1_DIR / "README.md")):
        commands = _commands(text)
        code = re.fullmatch(r'\s*python3 -c "(.*)"\)?', commands[_first(commands, "smoke20_ids.txt")].split("&&")[-1])
        assert code, commands
        out = subprocess.run([sys.executable, "-c", code[1]], cwd=tmp_path, capture_output=True, text=True, timeout=60)
        assert out.stdout == SMOKE_PASS + "\n", out
        assert f"`{SMOKE_PASS}`" in text and "`20 0 []`" not in text


def test_r4_restores_the_baseline_files_when_the_ratchet_run_fails():
    # M305: validate_kg writes the ratcheted baseline before evaluate() decides the exit code
    main = inspect.getsource(vk.main)
    assert main.index("save_baseline(") < main.index("evaluate(") < main.index('return report["exit_code"]')
    assert vk.DEFAULT_BASELINE == ROOT / "config" / "kg_quality_baseline"
    r4 = section(staging_text(), "R4")
    after = r4[r4.index("--ratchet --accept W,R1,R11"):r4.index("1B 移動的指標")]
    for needle in ("結束碼不是 0", "`git checkout -- config/kg_quality_baseline/`", "不 commit"):
        assert needle in after, needle


def test_r4_u3_lists_the_overview_line_that_dates_the_graph_counts():
    # M309: the closing 圖譜數字時點 line holds 319,988 and its date; the file-level U3 check cannot see it
    u3 = section(staging_text(), "R4").split("**R4 之後的文件更新（U3）**", 1)[1]
    pattern = re.compile(U3_GREP.split("'")[1].replace("\\|", "|"))
    dated = [line for line in read(ROOT / "docs" / "kg_construction_overview.md").splitlines() if "圖譜數字時點" in line]
    assert len(dated) == 1 and pattern.search(dated[0]), dated
    update = next(line for line in u3.splitlines() if "描述現行圖譜的要改" in line)
    assert ":399（末段「圖譜數字時點」" in update, update


def test_window_does_not_call_the_expanded_stratum_held_out():
    # M310: every kg_xref question 1B's design used is an expanded one, so all 68 sit in ab_compare's [expanded]
    sel = json.loads(read(ROOT / "docs" / "records" / "2026-10-04_kg_fix" / "batch1" / "inputs" / "kg_xref" / "sel.json"))
    assert len(sel) == 68 and not [row for row in sel if row["family"] == "legacy_head"]
    bullet = next(line for line in section(staging_text(), WINDOW).splitlines() if line.startswith("- ab_compare 補上"))
    for needle in ("kg_xref 68 題都在這一段", "不是乾淨的 held-out", "xref_ab_slice 另報"):
        assert needle in bullet, needle
    assert "（擴充的 400 題，held-out）" not in bullet

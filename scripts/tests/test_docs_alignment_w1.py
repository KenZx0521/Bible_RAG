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
and K8's P1 rebuild never overwrites R2's gate report. The second group
(docs_promotion 2) pins the rest: K9's empty adjudication file, label schema
and spot-check coverage, the fallback's re-pinned output test, the 6.05
report's path in report_sha256, E1 before the v3 bump and the PG drop (with
backend-staging stopped first), fail-closed rebuild-time blocks under ${D:?},
Step 9's teed runs, every retrieval run naming its backend, every
backend-staging start waiting for health, check_identity on ids only until 1D
with its output kept, 1A's paper lines in U3, and R5 verifying the prod data
before the image goes back.
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

from scripts.relation_extraction import relation_postprocess as pp
from scripts.tools import check_w1_registration as cwr
from scripts.tools import kin_review as kr
from test_docs_alignment import (_FLAG_RE, D_GUARD, DOC, ROOT, SMOKE_JSON, STAGING_DOC, STAGING_W1_DOC, U3_GREP,
                                 W1_ID_FILE, _assert_fail_closed, _blocks, _commands, _first, _in_order, code_snippets,
                                 doc_text, help_text, read, section, staging_text)
from test_kin_review import counted, write_labels, write_sample
from test_relation_postprocess import _run

MAIN = "/home/kenzx0521/Bible_RAG"
BRANCH = "feat/graph-strategy-gating"
COMPOSE_BACKUP = "docker-compose.yml.bak-20260730-160725"   # 2026-07-30 manual copy, never committed
EXPECT = "config/kg_expect/batch1_w1/"
DUMP = "bak/$D/promote/neo4j_staging.dump"
HEAD_FILE = "bak/$D/images/backend_w1.head"
W1_DIR = ROOT / "evaluation" / "experiments" / "2026-10-05_kg_w1"
GE_IDS = "experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt"
WINDOW = "W1 升版第 1、2 步之間"
# every backend-staging start waits for its healthcheck (start_period 120 s) before D3 or a measure (M392)
WAIT_UP = "up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging"
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
                   f"`{COMPOSE_BACKUP}`", "合併前的 commit", "W1 紀錄"):
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
        "git merge-base --is-ancestor kg-pre-batch1-w1 HEAD", "git merge-base --is-ancestor w1/1b HEAD",
        "scripts/tests/run.sh",
        "backend/.venv/bin/python -m pytest backend/tests -q",
        "(cd evaluation && uv run --offline python -m pytest tests -q)",
        f"X=$(git status --porcelain -- . ':(exclude){COMPOSE_BACKUP}'", 'test -z "$X"'))
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
                   f"w1_image.yml {WAIT_UP}"))


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
    # since 2026-10-06 the W1 steps live in staging_promotion_w1.md; R3 keeps only the generic steps
    generic = section(read(STAGING_DOC), "R3")
    assert "### W1 升版第 1 步" not in generic and "## W1 升版第 1 步" in read(STAGING_W1_DOC)
    note = next(line for line in generic.splitlines() if line.startswith("第 1 批 W1"))
    assert "第 2 步才做這裡的第 1 步" not in note and "「W1 升版第 2 步」" in note, note
    assert "](staging_promotion_w1.md)" in note, note
    _in_order(_commands(generic), ("docker stop -t 60 bible_rag_neo4j_staging",
                                   "database dump neo4j --to-stdout > bak/$D/promote/neo4j_staging.dump",
                                   "database load neo4j --from-stdin"))


def test_r3_and_r5_compose_runs_without_deps_from_a_clean_main_checkout_shell():
    # a shell that sourced staging.env would make compose recreate prod postgres (POSTGRES_DB);
    # R3's W1 steps (one `up` each in step 1 and R5) live in staging_promotion_w1.md since 2026-10-06
    for name, text in (("R3", section(read(STAGING_DOC), "R3") + read(STAGING_W1_DOC)),
                       ("R5", section(staging_text(), "R5"))):
        ups = [s for s in code_snippets(text) if "docker compose up" in s]
        assert len(ups) >= 2 and all("--no-deps" in s.split() for s in ups), (name, ups)
    r5 = section(staging_text(), "R5")
    for needle in ("主 checkout", "乾淨", "staging.env", "POSTGRES_DB"):
        assert needle in r5, needle


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
                     f"BACKEND_URL=http://localhost:8000 uv run python {run} ge_old_w1",
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
    for needle in ("GUARD_FILES 這三個檔沒提交的改動即使建進 image 也會被擋下", "其他檔的改動 deploy-guard 看不到"):
        assert needle in xref, needle
    assert "（沒提交的改動即使建進 image 也會被擋下）" not in xref


def test_r2_item_3_builds_and_records_the_w1_image_in_a_fail_closed_block():
    # M307: an unset D, a missing :w1 (empty id file) or a missing staging container stops it before the measures
    blocks = _blocks(section(staging_text(), "W1 的交叉引用檢查"))
    build = next(b for b in blocks if any("w1_image.yml build backend" in c for c in b))
    _assert_fail_closed(build, "staging runs :w1")
    record = f"docker image inspect -f '{{{{.Id}}}}' bible_rag-backend:w1 > {W1_ID_FILE}"
    up = _in_order(build, ("w1_image.yml build backend", "mkdir -p bak/$D/images", record, f"test -s {W1_ID_FILE}",
                           f"w1_image.yml {WAIT_UP}"))[-1]
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


# ---------------------------------------------------------------- review minors (docs_promotion 2)

W1A = "W1 的關係層檢查"
XREF = "W1 的交叉引用檢查"
PP_TEST = "scripts/tests/test_relation_postprocess_output.py"
SIM = ROOT / "docs" / "records" / "2026-10-04_kg_fix" / "batch1" / "w1_1A"
PAPER = ROOT / "paper" / "latex"
STEP9_RUNS = ("bak/$D/step9_run1.log", "bak/$D/step9_run2.log")


def _block(heading: str, needle: str, text: str | None = None) -> list[str]:
    return next(b for b in _blocks(section(text or staging_text(), heading)) if any(needle in c for c in b))


def _script(block: list[str], drop: str = "\0") -> str:
    """A fail-closed block as one bash script, its lines holding `drop` left out (the ones that need a store)."""
    return "\n".join(c for c in block if drop not in c)


@pytest.mark.parametrize("adjudication, code", [("empty", 0), ("missing", 2)])
def test_k9_agreeing_labellings_take_an_empty_adjudication_file(tmp_path, adjudication, code):
    # M367: both score lines always pass --adjudication; kin_review reads an empty file and refuses a missing one
    adj = tmp_path / "adj.jsonl"
    if adjudication == "empty":
        adj.write_text("", encoding="utf-8")
    labels = counted(60, 58, 50)
    argv = ["--mode", "score", "--sample", write_sample(tmp_path, 60),
            "--labels", write_labels(tmp_path, "a.jsonl", labels, "ai:a"),
            "--labels", write_labels(tmp_path, "b.jsonl", labels, "ai:b"),
            "--adjudication", str(adj), "--out", str(tmp_path / "report.json")]
    assert kr.main(argv) == code
    w1a = section(staging_text(), W1A)
    scores = [c for c in _commands(w1a) if "kin_review.py --mode score" in c]
    assert len(scores) == 2 and all("--adjudication $K/" in c for c in scores), scores
    assert "省略 `--adjudication`" not in w1a
    for needle in ("裁決檔建成空檔", "`: > $K/", "檔案不存在則結束碼 2"):
        assert needle in w1a, needle


def test_k9_documents_the_label_rows_and_enforces_kays_spot_check_coverage():
    # M394: kin_review reports the spot-check and never gates on it; the runbook's jq does
    words = " ".join(help_text("kin_review").split())
    schema = "{item_id, text_correct, id_correct, annotator, note}"
    assert schema in words and "'ai:<session>'" in words
    w1a = section(staging_text(), W1A)
    for needle in (f"`{schema}`", "`ai:<session>`", "全部裁決項目", "另加至少 10 項"):
        assert needle in w1a, needle
    gate = _block(W1A, "--sample $K/anchored.json")
    _assert_fail_closed(gate, "K9 anchored passed")
    assert _first(gate, "kin_review.py --mode score") < _first(gate, "jq -e --slurpfile kay $K/anchored_kay.jsonl")


@pytest.mark.parametrize("spot, disagree, ok", [(12, 2, True), (11, 2, False), (12, 0, True), (9, 0, False),
                                                (13, 3, False)])
def test_k9_spot_check_jq_wants_every_adjudicated_item_plus_ten(tmp_path, spot, disagree, ok):
    gate = _block(W1A, "--sample $K/anchored.json")
    check = gate[_first(gate, "jq -e --slurpfile kay")]
    ids = [f"item{i:03d}" for i in range(60)]
    (tmp_path / "anchored_report.json").write_text(json.dumps(
        {"disagreements": [{"item_id": i} for i in ids[:disagree]]}), encoding="utf-8")
    covered = ids[1:spot + 1] if spot == 13 else ids[:spot]   # 13: one adjudicated item left out
    (tmp_path / "anchored_kay.jsonl").write_text("".join(json.dumps({"item_id": i}) + "\n" for i in covered),
                                                 encoding="utf-8")
    run = _bash(f"K=.; {check}", tmp_path)
    assert (run.returncode == 0) is ok, run


def test_k9_fallback_names_the_output_test_and_its_repinned_values():
    # M370, M394: test_final_edge_set is a function of test_relation_postprocess_output.py, not a file
    fallback = next(line for line in section(staging_text(), W1A).splitlines() if "沒過時的唯一退路" in line)
    for needle in (f"`{PP_TEST}::test_final_edge_set`", "`sim2_no_anchored.json`", "列數", "by_source",
                   "FINAL_EDGE_SET_SHA256", "FINAL_AFTER_10_2_SHA256", "KINSHIP", "ee 鍵", "16 個探針", "test_stamps"):
        assert needle in fallback, needle
    source = read(ROOT / PP_TEST)
    for name in ("FINAL_EDGE_SET_SHA256 =", "FINAL_AFTER_10_2_SHA256 =", "KINSHIP =", "def test_final_edge_set(",
                 "def test_stamps(", "len(relation_probes) == 16", '"anchored_rule": (4, 319)'):
        assert name in source, name


def test_1a_expected_files_come_from_the_report_at_the_default_path(tmp_path):
    # M378: the report holds its own --out path, so report_sha256 depends on where 6.05 wrote
    rows, report = _run("all")
    written = []
    for name in ("a", "b"):
        out = tmp_path / name / "relations_clean.jsonl"
        out.parent.mkdir()
        pp.write_outputs(rows, report, out, out.with_name("relations_clean.report.json"))
        written.append((out.read_bytes(), out.with_name("relations_clean.report.json").read_bytes()))
    assert written[0][0] == written[1][0] and written[0][1] != written[1][1]
    assert "report_sha256" in cwr.SHA_FIELDS and cwr.DEFAULT_REPORT.as_posix() == "output/relations_clean.report.json"
    item = _item(section(staging_text(), W1A), "2")
    for needle in ("output.path", "report_sha256", "output/relations_clean.report.json", "不可 commit",
                   "check_w1_registration"):
        assert needle in item, needle


def test_e1_reads_the_batch0_staging_before_the_v3_bump_and_the_pg_drop():
    # M386: backend-staging holds a connection to bible_rag_staging; after the bump validate_kg's H5 reads v3
    text = staging_text()
    create = _item(section(text, "R1"), "2")
    _in_order(_commands(create), ("docker compose -f docker-compose.yml -f docker-compose.staging.yml stop backend-staging",
                                  "dropdb -U bible --if-exists bible_rag_staging", "createdb -U bible bible_rag_staging"))
    assert "being accessed by other users" in create and "E1" in create
    assert "E1" in _item(section(text, "R0"), "8") and "R0 第 8 項" in _item(section(text, "R1"), "5")
    e1 = _item(section(text, W1A), "2")
    for needle in ("R0 第 8 項", "R1 第 2 項", "bible_entities_v3", "H5", "不依賴 K9"):
        assert needle in e1, needle


@pytest.mark.parametrize("heading, needle, echo", [
    (XREF, "--out config/kg_expect/batch1_w1/xref.json", "xref expectation and oracle compare ok"),
    (XREF, "--out bak/$D/xref_probe/xref_rebuild.json", "xref expectation unchanged"),
    (XREF, STEP9_RUNS[1], "step 9: created 0, same fingerprint, expect matched"),
    (W1A, "kin_review.py --mode sample", "K9 samples drawn"),
    (W1A, "--sample $K/anchored.json", "K9 anchored passed"),
    (W1A, "--report-only", "K9 llm and prior reported"),
    (W1A, "residuals_expect.py --a prod --b staging --validate-a", "E1 read the batch-0 staging"),
    (W1A, "props_sha > bak/$D/props_0.txt", "props identical"),
])
def test_w1_rebuild_time_checks_are_fail_closed_blocks(heading, needle, echo):
    # M389: a bare command list leaves every exit code to the eye, and an unset D writes to bak/
    _assert_fail_closed(_block(heading, needle), echo)


def test_build_side_6_05_and_step9_blocks_are_fail_closed():
    determinism = _block("Step 6.05:", "cp output/relations_clean.jsonl", doc_text())
    _assert_fail_closed(determinism, "6.05 twice: byte-identical")
    _in_order(determinism, ("cp output/relations_clean.jsonl", "relation_postprocess",
                            "cmp output/relations_clean.jsonl", "cmp output/relations_clean.report.json"))
    step9 = _block("Step 9:", "step9_run", doc_text())
    _assert_fail_closed(step9, "step 9 twice: created 0, same fingerprint")
    tee = ("uv run --project scripts python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt "
           "| tee bak/$D/step9_run$n.log")
    assert step9[3] == "for n in 1 2; do" and step9[4] == tee, step9
    r2 = _block(XREF, STEP9_RUNS[1])
    assert step9[6:-2] == r2[3:-2], (step9, r2)   # R2 re-checks the logs the rebuild wrote, with the same lines
    row = next(line for line in doc_text().splitlines() if line.startswith("  | 9 |"))
    assert all(f"`{log}`" in row for log in STEP9_RUNS), row


_STEP9_OK = "After: created 0, attached_to_curated 924, matched 250,358\nfingerprint: {}\n"


@pytest.mark.parametrize("run1, run2, ok", [
    ("created 249,434\nfingerprint: aa\n", _STEP9_OK.format("aa"), True),
    ("created 249,434\nfingerprint: aa\n", _STEP9_OK.format("bb"), False),
    ("created 249,434\nfingerprint: aa\n", _STEP9_OK.format("aa").replace("created 0", "created 5"), False),
    ("created 249,434\n", _STEP9_OK.format("aa"), False),
])
def test_r2_step9_log_check_wants_created_0_and_one_fingerprint(tmp_path, run1, run2, ok):
    logs = tmp_path / "bak" / "x"
    logs.mkdir(parents=True)
    (logs / "step9_run1.log").write_text(run1, encoding="utf-8")
    (logs / "step9_run2.log").write_text(run2, encoding="utf-8")
    run = _bash(f"D=x\n{_script(_block(XREF, STEP9_RUNS[1]), 'xref_probe.py fingerprint')}", tmp_path)
    assert (run.returncode == 0) is ok, run


@pytest.mark.parametrize("digest, ok", [('edges, props_sha\n5696, "ab"\n', True), ('edges, props_sha\n5697, "ab"\n', False)])
def test_props_digest_pins_the_6_05_row_count(tmp_path, digest, ok):
    props = _block(W1A, "props_sha > bak/$D/props_0.txt")
    assert not [c for c in props if c.startswith("cmp ") and "&&" in c], props
    final = sum(json.loads(read(SIM / "sim2_final.json"))["final_by_source"].values())
    fallback = sum(json.loads(read(SIM / "sim2_no_anchored.json"))["final_by_source"].values())
    grep = props[_first(props, "grep ")]
    assert grep == f"grep '^{final}, \"' bak/$D/props_2.txt" and f"{fallback:,}" in _item(section(staging_text(), W1A), "3")
    (tmp_path / "props_2.txt").write_text(digest, encoding="utf-8")
    run = _bash(f"D=x; {grep.replace('bak/$D/', '')}", tmp_path)
    assert (run.returncode == 0) is ok, run


@pytest.mark.parametrize("code, ok", [(0, True), (1, True), (2, False)])
def test_e1_accepts_validate_kgs_expected_exit_1_only(tmp_path, code, ok):
    # before W1 both sides fail the 1A and 1B hard checks; residuals_expect reads only R1
    e1 = _block(W1A, "residuals_expect.py --a prod --b staging --validate-a")
    runs = [c for c in e1 if "validate_kg.py --live" in c]
    assert len(runs) == 2 and all(c.endswith(".json || test $? -eq 1") for c in runs), runs
    assert runs[1].startswith("(source scripts/tools/staging.env && uv run") and ") > bak/$D/e1/" in runs[1]
    run = _bash(f"set -eu -o pipefail; (exit {code}) > out.json || test $? -eq 1; echo ok", tmp_path)
    assert (run.stdout == "ok\n") is ok, run


def test_r0_tells_every_shell_to_reuse_the_r0_date():
    item = _item(section(staging_text(), "R0"), "3")
    for needle in ("`export D=<R0 的日期>`", "staging 的與乾淨的", "`$(date +%Y%m%d)`", "`${D:?}`"):
        assert needle in item, needle


@pytest.mark.parametrize("n_invalid, code", [(0, 0), (1, 1)])
def test_w1_smoke_check_exits_1_unless_it_prints_the_pass_line(tmp_path, n_invalid, code):
    # M389: the check printed `20 0 [] …` but never set an exit code
    result = tmp_path / SMOKE_JSON
    result.parent.mkdir()
    result.write_text(json.dumps({"n": 20, "n_invalid": n_invalid,
                                  "per_question": {f"q{i}": {"strategy_errors": []} for i in range(20)},
                                  "config": {"graph_strategies_applied": {"event_registry": 20}}}))
    for text in (section(staging_text(), STEP1), read(W1_DIR / "README.md")):
        commands = _commands(text)
        code_ = re.fullmatch(r'\s*python3 -c "(.*)"\)?', commands[_first(commands, "smoke20_ids.txt")].split("&&")[-1])
        out = subprocess.run([sys.executable, "-c", code_[1]], cwd=tmp_path, capture_output=True, text=True, timeout=60)
        assert out.returncode == code and out.stdout.startswith(f"20 {n_invalid} [] "), out


def test_every_w1_retrieval_run_names_its_backend():
    # M391: an exported BACKEND_URL=…:8001 would silently send a control arm to the staging backend
    runs = {}
    for text in (staging_text(), read(W1_DIR / "README.md")):
        for part in (p.strip() for c in _commands(text) for p in c.split("&&") if "quick_retrieval_eval.py" in p):
            m = re.fullmatch(r"BACKEND_URL=http://localhost:(800[01]) uv run python quick_retrieval_eval\.py .* "
                             r"--label ([^\s)]+)\)?", part)
            assert m, part
            runs.setdefault(m[2], set()).add(m[1])
    assert {label: ports for label, ports in runs.items() if "8000" in ports} == {
        "w1_step1_smoke": {"8000"}, "xref_old_w1": {"8000"}, "ge_old_w1": {"8000"}}, runs
    assert len(runs) == 8, runs
    bullet = next(line for line in section(staging_text(), "R2").splitlines() if "BACKEND_URL" in line)
    assert "不要 `export`" in bullet and "`BACKEND_URL=http://localhost:8001`" in bullet, bullet


def test_every_backend_staging_start_waits_for_health():
    # M392: D3 and ep_w1 ran right after an `up` that returned before the healthcheck passed
    ups = [(path.name, c) for path in (STAGING_DOC, STAGING_W1_DOC, DOC) for c in _commands(read(path))
           if re.search(r"\bup -d\b.*\bbackend-staging\b", c)]
    assert {name for name, _ in ups} == {STAGING_DOC.name, STAGING_W1_DOC.name, DOC.name} and len(ups) >= 4, ups
    assert all(WAIT_UP in c for _, c in ups), ups


def test_r4_runs_check_identity_on_ids_until_1d_and_keeps_the_outputs():
    # M388, M394: prod Qdrant keeps string aliases until 1D; plan §5.4 keeps check_identity's output and sha
    words = " ".join(help_text("check_identity").split())
    assert "(default: id,type,canonical,aliases,description)" in words and "until batch 1D" in words
    r4 = section(staging_text(), "R4")
    generic = next(line for line in r4.splitlines() if line.startswith("- 在 production 上執行"))
    assert "`check_identity.py --target prod --fail-on id`" in generic and "1D" in generic, generic
    w1 = section(staging_text(), "W1 的關係層升版後檢查")
    assert ("uv run --project scripts python scripts/check_identity.py --target prod --fail-on id --json "
            "> bak/$D/check_identity_prod_w1.json") in _commands(w1)
    assert "`(cd bak/$D && sha256sum ./validate_prod_w1.json ./check_identity_prod_w1.json >> SHA256SUMS)`" in w1
    staging = "scripts/check_identity.py --target staging --fail-on id --json > bak/$D/check_identity_staging_w1.json"
    assert f"uv run --project scripts python {staging}" in _commands(section(doc_text(), "10.6"))
    assert "(cd bak/$D && sha256sum ./check_identity_staging_w1.json >> SHA256SUMS)" in _commands(
        section(staging_text(), W1A))


def test_w1_step1_calls_the_exact_compare_c1s_criterion():
    # M394: the smoke check and the deploy-guard above it stop the step as well
    step1 = section(staging_text(), STEP1)
    assert "唯一的閘門" not in step1 and "- **C1 的判準是精確比對**" in step1


def test_r4_u3_lists_1a_paper_lines():
    # M382: plan §0.3 lists them; they describe the graph W1 replaces
    u3 = section(staging_text(), "R4").split("**R4 之後的文件更新（U3）**", 1)[1]
    current = next(line for line in u3.splitlines() if "論文中描述現行圖譜的地方" in line)
    for needle in ("sec3_kg.tex :164-185", "6.05", "`confidence_raw`", "sec7_discussion.tex :316"):
        assert needle in current, needle
    assert ":312-316" in next(line for line in u3.splitlines() if "實驗當時的數值保留" in line)
    sec3 = read(PAPER / "sec3_kg.tex").splitlines()
    assert "Inverse materialization" in sec3[163] and "752 inverse" in sec3[169]
    assert "Every fact edge carries \\code{confidence}" in sec3[181] and "confidence-filterable" in sec3[183]
    assert "now 84\\%/75.5\\%" in read(PAPER / "sec7_discussion.tex").splitlines()[315]
    sec6 = read(PAPER / "sec6_experiments.tex").splitlines()
    assert "Unclassified-relation rescue" in sec6[311] and "75.5" in sec6[315] and "TSK import" in sec6[316]


@pytest.mark.parametrize("counts, ok", [("nodes, count(r)\n13589, 319988\n", True),
                                        ("nodes, count(r)\n13589, 251616\n", False)])
def test_r5_checks_the_prod_data_before_the_image_goes_back(tmp_path, counts, ok):
    # M393: after the dump reload prod must predict pred_trans again and hold the R0 counts
    r5 = section(staging_text(), "R5")
    blocks = _blocks(r5)
    verify = _block("R5", "pred_prod_r5.json")
    rollback = next(b for b in blocks if any("docker load" in c for c in b))
    assert blocks.index(verify) < blocks.index(rollback)
    _assert_fail_closed(verify, "prod data back to R0")
    _in_order(verify, (
        "test \"$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j)\" = healthy",
        "xref_probe.py predict --target prod --seeds bak/$D/xref_probe/seeds.json --out bak/$D/xref_probe/pred_prod_r5.json",
        "xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_r5.json "
        "--measured bak/20261005_w1_1b_evidence/pred_trans.json",
        "RETURN nodes, count(r)\"' > bak/$D/r5_counts.txt", "grep -x '13589, 319988' bak/$D/r5_counts.txt"))
    (tmp_path / "r5_counts.txt").write_text(counts, encoding="utf-8")
    grep = verify[_first(verify, "grep -x")].replace("bak/$D/", "")
    assert (_bash(grep, tmp_path).returncode == 0) is ok
    for needle in ("`git revert` R4 的 ratchet", "13,589／319,988"):
        assert needle in r5, needle
    after = next(line for line in section(staging_text(), "W1 的 /api/v1/entity 比對").splitlines()
                 if line.startswith("第三段是閘門"))
    for needle in ("不做 R4 的 ratchet", "不自動走 R5", "Kay"):
        assert needle in after, needle

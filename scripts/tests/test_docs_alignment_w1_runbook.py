"""Final-review pins of the W1 runbook, docs/staging_promotion.md.

K8's P1 rebuild after R4 reruns the whole W1 chain, so it first makes every
fixed bak/$D path the chain wrote for R2 read-only (two of them have their
sha256 in SHA256SUMS) and sends its own outputs, Step 9's log reads included,
to bak/$D/k8/. The :w1 image is built only when nothing that goes into it
(Dockerfile, .dockerignore, the compose files, backend/, bible_chunking/,
scripts/) differs from HEAD; the merged allowlist (committed with the ratchet
after R4, its sha256 file registered and committed), the W1 record (committed
alone when W1 ends) and D3's results stay out of the image and out of the way.
R0's re-runnable block 2 survives a fix commit after the merge and lets the W1
record, the merged allowlist and the 2026-07-30 compose backup through. The
merged allowlist's sha256 check and the diff_kg run are one fail-closed block
at R2, run again before the step 2 dump, and the R4 commit stages the file and
ratchets only behind the same check. The props digest block follows the
sentence that introduces it. Plan §5.2's answer-side decision comes from
ab_compare's change ledger (re-asked under its own labels) and is made inside
the step 1-2 window, before backend-staging stops and before step 2. Kay's
approval (W1 step 4) is a checkpoint between R2 and promotion step 1.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from fnmatch import fnmatch

import pytest
from test_docs_alignment import (ROOT, _FLAG_RE, _assert_fail_closed, _blocks, _commands, _first, _in_order, doc_text,
                                 headings, read, section, staging_text)
from test_docs_alignment_1a import W1A
from test_docs_alignment_w1 import (DUMP, EXPECT, WINDOW, XREF, _bash, _block, _eval_help, _item,
                                    _window_evals)

from scripts.tools import check_w1_registration as cwr

K8 = "W1 的 K8 對照組"
KAY = "W1 第 4 步：Kay 核可"
STEP1 = "W1 升版第 1 步"
MERGED = "config/kg_diff_allow_batch1w1.yaml"
SHA_CHECK = f"sha256sum -c {EXPECT}kg_diff_allow_batch1w1.sha256"
W1_DIFF = f"diff_kg.py --a prod --b staging --allow {MERGED} --fail-on-unused --json"
RATCHET = "uv run --project scripts python scripts/validate_kg.py --live --target prod --ratchet --accept W,R1,R11"
TREE_W1 = "X=$(git status --porcelain -- "
TREE_R0 = "X=$(git status --porcelain -- . "
PATH_RE = re.compile(r"bak/\$D/[\w./$*{}-]+")
# a gold passage of the top-k moved in or out (or, in a legacy run, an unflagged one did)
SUBSTANTIVE = ("gold_in", "gold_out", "gold_swap", "changed")
SAME_GOLD = ("identical", "order_only", "nongold_swap")


# ---------------------------------------------------------------- (a) K8's P1 keeps R2's evidence

def _chain_paths() -> set[str]:
    """Fixed bak/$D paths the W1 chain writes: build_database.md's rows and blocks, plus the
    rebuild-time props digest and the 10.6 row's v3 == detB scroll (staging_promotion.md)."""
    found = set(PATH_RE.findall(doc_text()))
    found |= {p for p in PATH_RE.findall(section(staging_text(), W1A)) if "/props_" in p or "/qdrant_" in p}
    found = {p.rstrip("/.") for p in found if not p.startswith("bak/$D/k8/")}   # P1's own outputs
    return found - {"bak/$D/output/MANIFEST.sha256"}   # check_merged_inputs reads it


def _covered(path: str, patterns: list[str]) -> bool:
    concrete = path.replace("$n", "1").replace("$c", "x")
    return any(fnmatch(concrete, p) or fnmatch(concrete + "/x", p) for p in patterns)


def test_k8_p1_makes_every_fixed_r2_evidence_path_read_only_before_it_rebuilds():
    k8_text = section(staging_text(), K8)
    k8 = _commands(k8_text)
    assert k8[0].startswith("chmod a-w ") and k8[1] == "mkdir -p bak/$D/k8", k8   # before the first P1 command
    patterns = k8[0].split()[2:]
    paths = _chain_paths()
    assert {"bak/$D/step9_run$n.log", "bak/$D/check_identity_staging_w1.json", "bak/$D/validate_staging_w1.json",
            "bak/$D/xref_probe/xref_rebuild.json", "bak/$D/pp_run1", "bak/$D/props_0.txt"} <= paths, paths
    assert not [p for p in paths if not _covered(p, patterns)], (paths, patterns)
    prefixes = [p.split("*")[0] for p in patterns]
    assert not [c for c in k8[2:] for p in prefixes if p in c], k8
    pointer = next(line for line in doc_text().splitlines() if line.startswith("  **K8 的 P1 重建**"))
    assert f"R4「{K8}」" in pointer and "`bak/$D/k8/`" in pointer and "唯讀" in pointer, pointer
    assert any(c.endswith("check_identity.py --target staging --fail-on id --json > bak/$D/k8/check_identity_p1a.json")
               for c in k8), k8
    for needle in ("`bak/$D/k8/xref_rebuild_p1a.json`", "`xref_rebuild_p1b.json`", "`bak/$D/pp_run1/`",
                   "`check_identity_p1b.json`",
                   "不可覆寫 R2 的 `bak/$D/validate_staging_w1.json`、`bak/$D/check_identity_staging_w1.json`", "SHA256SUMS"):
        assert needle in k8_text, needle


def test_k8_p1_moves_every_step9_log_path_off_r2s_logs_including_the_greps():
    # moving only the tee would leave the greps checking R2's read-only logs, which pass whatever P1 did
    k8_text = section(staging_text(), K8)
    m = re.search(r"`(bak/\$D/step9_run)` 全部換成 `(bak/\$D/k8/step9_p1a_run)`", k8_text)
    assert m, k8_text
    step9 = next(b for b in _blocks(doc_text()) if any("import_tsk_crossrefs.py" in c and "| tee " in c for c in b))
    patterns = _commands(k8_text)[0].split()[2:]
    before = [p for c in step9 for p in PATH_RE.findall(c)]
    assert len(before) == 4 and all(_covered(p, patterns) for p in before), before   # the tee and three greps
    after = [p for c in step9 for p in PATH_RE.findall(c.replace(m[1], m[2]))]
    assert after and not [p for p in after if _covered(p, patterns)], after
    for needle in ("`bak/$D/k8/step9_p1b_run`", "grep", "`bak/$D/qdrant_*.sha256`", "O7", "待 Kay 確認"):
        assert needle in k8_text, needle


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the write bit")
def test_a_read_only_evidence_file_stops_a_redirect_and_a_tee(tmp_path):
    (tmp_path / "r2.json").write_text("{}")
    script = "set -eu -o pipefail\nchmod a-w r2.json\n{}\n"
    assert _bash(script.format("echo p1 > r2.json"), tmp_path).returncode != 0
    (tmp_path / "r2.json").chmod(0o644)
    assert _bash(script.format("echo p1 | tee r2.json"), tmp_path).returncode != 0
    assert (tmp_path / "r2.json").read_text() == "{}"


# ---------------------------------------------------------------- (b) what "clean" means for :w1

def _dockerfile_copy_roots() -> set[str]:
    roots = set()
    for line in read(ROOT / "Dockerfile").splitlines():
        parts = line.split()
        if parts[:1] == ["COPY"] and not parts[1].startswith("--"):
            roots |= {src.split("/")[0] for src in parts[1:-1]}
    return roots


def _image_inputs(command: str) -> set[str]:
    return set(command.split(" -- ", 1)[1].rstrip(")").split())


def test_w1_image_build_checks_only_what_goes_into_the_image():
    assert _dockerfile_copy_roots() == {"backend", "bible_chunking", "scripts"}
    # O5: only the merged file waits for R4; its sha256 file is registered, so committed before the rebuild
    assert cwr.MERGED == MERGED and MERGED not in cwr.REGISTERED and cwr.MERGED_SHA in cwr.REGISTERED
    xref = section(staging_text(), XREF)
    for needle in ("Dockerfile 只 COPY `backend/`、`bible_chunking/`、`scripts/`", "image 的輸入", f"`{MERGED}`",
                   "R4 之後", "`kg_diff_allow_batch1w1.sha256` 已 commit", "W1 紀錄", "`evaluation/results_quick/`",
                   "`docker-compose.yml.bak-20260730-160725`"):
        assert needle in xref, needle
    assert "建 image 前工作目錄要乾淨" not in xref and "只可以有兩行未追蹤的檔" not in xref
    build = _block(XREF, "w1_image.yml build backend")
    _in_order(build, (TREE_W1, 'test -z "$X"', "w1_image.yml build backend"))
    assert _image_inputs(build[_first(build, TREE_W1)]) == {
        "Dockerfile", ".dockerignore", "docker-compose.yml", "docker-compose.staging.yml", *_dockerfile_copy_roots()}


TRACKED = ("Dockerfile", ".dockerignore", "docker-compose.yml", "docker-compose.staging.yml", "backend/a.py",
           "bible_chunking/b.py", "scripts/c.py", "config/x.yaml", "docs/records/w0.md", "evaluation/e.py")
RECORD = "docs/records/2026-10-07_kg_batch1_w1_results.md"
LET_THROUGH = f"touch {MERGED} {RECORD} docker-compose.yml.bak-20260730-160725"   # by R0 block 2 too
CHANGES = {"clean": "", "let_through": LET_THROUGH, "results_quick": "touch evaluation/results_quick/d3_w1.json",
           "record_committed": f"touch {RECORD} && git add {RECORD} && git commit -qm r && echo y >> {RECORD}",
           "other_record": "touch docs/records/2026-10-07_other.md", "config": "echo y >> config/x.yaml",
           "scripts": "echo y >> scripts/c.py", "scripts_new": "mkdir scripts/tools && touch scripts/tools/new.py",
           "backend_staged": "echo y >> backend/a.py && git add backend/a.py", "dockerfile": "echo y >> Dockerfile",
           "dockerignore": "echo y >> .dockerignore", "compose": "echo y >> docker-compose.yml",
           "bible_chunking_new": "touch bible_chunking/n.py", "no_repo": "rm -rf .git"}


def _tree_check(repo, change: str, lines: list[str]) -> bool:
    """`lines` run in a repo laid out like the main checkout after `change`; True when they pass."""
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    for name in TRACKED:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n")
    (repo / "evaluation" / "results_quick").mkdir()
    (repo / "evaluation" / "results_quick" / "kept.json").write_text("{}")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    assert _bash(CHANGES[change] or "true", repo).returncode == 0
    return _bash("set -eu -o pipefail\n" + "\n".join(lines), repo).returncode == 0


@pytest.mark.parametrize("change, ok", [
    ("clean", True), ("let_through", True), ("results_quick", True), ("record_committed", True),
    ("other_record", True), ("config", True), ("scripts", False), ("scripts_new", False), ("backend_staged", False),
    ("dockerfile", False), ("dockerignore", False), ("compose", False), ("bible_chunking_new", False),
    ("no_repo", False)])
def test_w1_image_build_tree_check_stops_only_on_an_image_input(tmp_path, change, ok):
    build = _block(XREF, "w1_image.yml build backend")
    lines = [c for c in build if c.startswith(TREE_W1) or c == 'test -z "$X"']
    assert len(lines) == 2, build
    assert _tree_check(tmp_path, change, lines) is ok


@pytest.mark.parametrize("change, ok", [
    ("clean", True), ("let_through", True), ("record_committed", True), ("results_quick", False),
    ("other_record", False), ("config", False), ("scripts", False), ("no_repo", False)])
def test_r0_block_2_tree_check_lets_the_w1_record_and_the_merged_allowlist_through(tmp_path, change, ok):
    suites = _blocks(_item(section(staging_text(), "R0"), "0"))[1]
    lines = [c for c in suites if c.startswith(TREE_R0) or c == 'test -z "$X"']
    assert len(lines) == 2, suites
    assert _tree_check(tmp_path, change, lines) is ok


def test_r0_says_the_w1_record_is_committed_alone_when_w1_ends():
    item = _item(section(staging_text(), "R0"), "0")
    for needle in ("W1 結束", "單獨 commit", "W1 紀錄", "`docker-compose.yml.bak-20260730-160725`", f"`{MERGED}`"):
        assert needle in item, needle
    suites = _blocks(item)[1]
    record_glob = re.search(r":\(exclude\)(docs/records/[^']+)'", suites[_first(suites, TREE_R0)])[1]
    named = re.search(r"`(docs/records/<日期>_kg_batch1_w1_results\.md)`", section(staging_text(), KAY))[1]
    assert fnmatch(named.replace("<日期>", "2026-10-07"), record_glob), (named, record_glob)
    report = section(staging_text(), K8).rsplit("- **報告**", 1)[1]
    assert "W1 紀錄" in report and "單獨 commit" in report and "R0 第 0 項" in report, report


# ---------------------------------------------------------------- (c), (g) the merged allowlist guard

def test_r2_runs_the_merged_allowlist_sha_check_and_the_w1_diff_as_one_fail_closed_block():
    block = next(b for b in _blocks(section(staging_text(), "R2")) if any(W1_DIFF in c for c in b))
    _assert_fail_closed(block, "W1 diff_kg passed")
    at = _first(block, W1_DIFF)
    assert block[at - 1] == SHA_CHECK and block[at].endswith(f"{W1_DIFF} > bak/$D/diff_kg_staging_w1.json"), block


@pytest.mark.parametrize("failing, ran", [("sha256sum", ["sha256sum"]), ("git", ["sha256sum", "git"]),
                                          (None, ["sha256sum", "git", "uv"])])
def test_r4_commit_stages_the_allowlist_and_ratchets_only_after_the_sha_check(tmp_path, failing, ran):
    # R4: the same check right before the file is staged; a mismatch must not rewrite the baseline either
    r4 = section(staging_text(), "R4")
    chain = [c for c in _commands(r4) if "git add" in c]
    assert chain == [f"{SHA_CHECK} && git add {MERGED} && {RATCHET}"], chain
    stubs = "".join(f'{name}() {{ echo {name} >> calls; {"return 1" if name == failing else "true"}; }}\n'
                    for name in ("sha256sum", "git", "uv"))
    result = _bash(stubs + chain[0] + "\ntrue", tmp_path)
    assert result.returncode == 0 and (tmp_path / "calls").read_text().split() == ran, result
    for needle in ("看過 staging 的 diff 之後不可再改", "不 ratchet", "`&&`"):
        assert needle in r4, needle


def test_w1_step2_reruns_the_whole_r2_diff_and_wants_the_answer_side_lists_before_the_dump():
    step2 = section(staging_text(), "W1 升版第 2 步")
    load = next(b for b in _blocks(step2) if any("database load" in c for c in b))
    _in_order(load, (f"residuals_expect.py --a prod --b staging --check {EXPECT}residuals_expected.json",
                     "mkdir -p bak/$D/promote", SHA_CHECK, f"{W1_DIFF} > bak/$D/promote/diff_kg_w1.json",
                     "cat bak/$D/answer_side_xref.txt bak/$D/answer_side_graph_event.txt", f"test ! -e {DUMP}"))
    bullet = next(line for line in step2.splitlines() if line.startswith("- **staging 唯讀再驗一次"))
    for needle in ("diff_kg", "`--fail-on-unused`", "labels", "entity_ids", "descriptions", "aliases",
                   "mention_count", "registry", "prod 還沒載入"):
        assert needle in bullet, needle


# ---------------------------------------------------------------- (d) the colon introduces the props block

def test_the_props_digest_sentence_is_followed_by_the_props_block():
    item = _item(section(staging_text(), W1A), "3")
    sentence = "語意層的定義與 6.1 相同："
    rest = item[item.index(sentence) + len(sentence):]
    assert rest.lstrip(" \n").startswith("```bash"), rest[:120]
    assert "props_sha > bak/$D/props_0.txt" in _blocks(rest)[0]
    assert item.index("check_w1_registration.py") < item.index(sentence)


# ---------------------------------------------------------------- (e) the answer-side decision point

def _ledger_statuses() -> set[str]:
    src = read(ROOT / "evaluation" / "src" / "ab_stats.py")
    assert '"changed"' in src
    return {s.strip() for s in re.search(r"status: (.+)\n", src).group(1).split("|")} | {"changed"}


def _ab_labels() -> list[str]:
    return re.findall(r"ab_compare\.py \S+ \S+ --label (\w+)\)", "\n".join(_window_evals()))


@pytest.mark.parametrize("missing", [None, "w1_graph_event"])
def test_window_lists_the_answer_side_candidates_from_both_ab_ledgers(tmp_path, missing):
    assert _ledger_statuses() == {*SUBSTANTIVE, *SAME_GOLD}
    labels = _ab_labels()
    assert labels == ["w1_xref", "w1_graph_event"], labels
    fence = next(b for b in _blocks(section(staging_text(), WINDOW)) if any("answer_side_" in c for c in b))
    block = fence[fence.index("("):]   # after the graph_event slice's ab_compare, in the same fence
    _assert_fail_closed(block, "answer-side candidates listed")
    _in_order(block, ("rm -f bak/$D/answer_side_*.txt", "for r in xref graph_event"))
    quick = tmp_path / "evaluation" / "results_quick"
    quick.mkdir(parents=True)
    (tmp_path / "bak" / "x").mkdir(parents=True)
    for r in ("xref", "graph_event"):   # a previous run's lists: a re-run whose jq fails must not leave them
        (tmp_path / "bak" / "x" / f"answer_side_{r}.txt").write_text("STALE\n")
    ledger = {f"Q_{s}": {"status": s, "injected": [], "displaced": []} for s in _ledger_statuses()}
    for label in labels:
        if label != missing:
            (quick / f"ab_{label}.json").write_text(json.dumps({"ledger": ledger}))
    result = _bash("D=x\n" + "\n".join(block), tmp_path)
    assert (result.returncode == 0) is (missing is None), result
    # a failed jq leaves no list behind (an empty one would read as "no substantive difference")
    assert (tmp_path / "bak" / "x" / "answer_side_graph_event.txt").exists() is (missing is None)
    if missing is None:
        for r in ("xref", "graph_event"):
            got = (tmp_path / "bak" / "x" / f"answer_side_{r}.txt").read_text().split()
            assert sorted(got) == sorted(f"Q_{s}" for s in SUBSTANTIVE), got


def test_window_records_the_answer_side_decision_before_staging_stops_and_step_2():
    window = section(staging_text(), WINDOW)
    bullet = next(line for line in window.splitlines() if line.startswith("- **答案端"))
    for needle in ("第 2 步之前", "W1 紀錄", *(f"`{s}`" for s in SUBSTANTIVE + SAME_GOLD), "重問", "`run_eval.py`",
                   "BACKEND_URL=http://localhost:8000", "`http://localhost:8001`", "`evaluation/results/`",
                   "`answer_coverage`", "`ragas_faithfulness_strict`", "0.97", "0.060", "§5.2"):
        assert needle in bullet, needle
    runs = [s for s in re.findall(r"`([^`]+)`", bullet) if "run_eval.py" in s and "--" in s]
    flags = {f for s in runs for f in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", s)}
    assert flags and flags <= set(re.findall(r"--[a-z][a-z0-9-]*", _eval_help("run_eval.py"))), flags
    stop = window.rindex("停掉 backend-staging")
    assert stop > window.index("echo 'answer-side candidates listed'") and stop > window.index(bullet), window[stop:]
    last = window.rstrip().splitlines()[-1]
    assert "答案端" in last and "第 2 步" in last and "停掉 backend-staging" in last, last


REASK = {"xref": ("xref_old_w1_reask", "xref_new_w1_reask", "w1_xref_reask"),
         "graph_event": ("ge_old_w1_reask", "ge_new_w1_reask", "w1_graph_event_reask")}


def test_answer_side_reask_reads_the_candidate_list_under_its_own_labels():
    bullet = next(line for line in section(staging_text(), WINDOW).splitlines() if line.startswith("- **答案端"))
    spans = re.findall(r"`([^`]+)`", bullet)
    runs = [s for s in spans if "quick_retrieval_eval.py" in s]
    assert runs, bullet
    for run in runs:
        m = re.fullmatch(r"\(cd evaluation && BACKEND_URL=http://localhost:800[01] uv run python quick_retrieval_eval\.py "
                         r"--ids-file \.\./bak/\$D/answer_side_(\w+)\.txt (.*) --label (\w+)\)", run)
        assert m and m[3] == REASK[m[1]][0], run
        assert set(_FLAG_RE.findall(run)) <= set(_FLAG_RE.findall(_eval_help("quick_retrieval_eval.py"))), run
    used = {label for labels in REASK.values() for label in labels}
    assert not used & set(re.findall(r"--label (\w+)", "\n".join(_window_evals()))), used
    for needle in (*used, *(f"--label {ab}" for _, _, ab in REASK.values()), "`xref_new_w1_reask`"):
        assert needle in bullet, needle
    compare = next(s for s in spans if "ab_compare.py" in s)
    assert compare == ("(cd evaluation && uv run python ab_compare.py results_quick/xref_old_w1_reask.json "
                       "results_quick/xref_new_w1_reask.json --label w1_xref_reask)"), compare
    for needle in ("`results_quick/ab_w1_xref_reask.json`", "`ab_w1_graph_event_reask.json`", "舊清單"):
        assert needle in bullet, needle


# ---------------------------------------------------------------- (f) R0 block 2 after a fix commit

def _git(repo, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60, check=True)
    return out.stdout.strip()


def _w1_repo(repo, scenario: str) -> None:
    """main with the pre-merge tag; w1/1a holding w1/1b; then the scenario's merge and fix commits."""
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "w1/1b")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "1b")
    _git(repo, "checkout", "-q", "-b", "w1/1a")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "1a")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "handoff")
    _git(repo, "tag", "kg-pre-batch1-w1")
    if scenario == "reversed":   # merged the other way: the tag is not on HEAD's first-parent path
        _git(repo, "checkout", "-q", "w1/1a")
        _git(repo, "merge", "-q", "--no-ff", "--no-edit", "main")
    elif scenario not in ("unmerged", "tag_only"):
        _git(repo, "merge", "-q", "--no-ff", "--no-edit", "w1/1a")
    if scenario in ("fix", "unmerged"):
        _git(repo, "commit", "-q", "--allow-empty", "-m", "fix after the merge")


@pytest.mark.parametrize("scenario, ok", [("merged", True), ("fix", True), ("reversed", False), ("unmerged", False),
                                          ("tag_only", False)])
def test_r0_block_2_survives_a_fix_commit_after_the_merge(tmp_path, scenario, ok):
    _w1_repo(tmp_path, scenario)
    suites = _blocks(_item(section(staging_text(), "R0"), "0"))[1]
    checks = suites[3:_first(suites, "scripts/tests/run.sh")]
    assert not [c for c in checks if "HEAD^1" in c], checks
    _in_order(checks, ("git merge-base --is-ancestor kg-pre-batch1-w1 HEAD", "git rev-list --first-parent",
                       "git merge-base --is-ancestor w1/1a", "git merge-base --is-ancestor w1/1b HEAD"))
    result = _bash("set -eu -o pipefail\n" + "\n".join(checks), tmp_path)
    assert (result.returncode == 0) is ok, result
    item = _item(section(staging_text(), "R0"), "0")
    for needle in ("修正 commit", "不 amend", "W1 紀錄"):
        assert needle in item, needle


# ---------------------------------------------------------------- (h) Kay's approval, W1 step 4

def test_kay_approval_is_a_checkpoint_between_r2_and_promotion_step_1():
    text = staging_text()
    heads = headings(text)
    assert heads.index("R2 驗證") < heads.index(KAY) < _first(heads, STEP1), heads
    kay = section(text, KAY)
    for needle in ("第 1 批計畫", "§1", "`config/kg_expect/batch1_w1/`", f"`{SHA_CHECK}`", "`bak/$D/diff_kg_staging_w1.json`",
                   "`bak/$D/validate_staging_w1.json`", "`bak/$D/check_identity_staging_w1.json`", "residuals_expect",
                   "D3", "`evaluation/results_quick/d3_w1.json`", "K9", "`ep_w1`", "W1 紀錄",
                   "`docs/records/<日期>_kg_batch1_w1_results.md`", "不開始", "待 Kay 確認", "M390",
                   "不改任何已登記的檔", "從 Step 5"):
        assert needle in kay, needle
    assert list((ROOT / "docs" / "records").glob("*_kg_batch1_w0_results.md")), "W0 record naming"
    opening = section(text, STEP1).splitlines()[1]
    assert f"「{KAY}」" in opening and "W1 紀錄" in opening, opening

"""W1 pre-registration pre-flight (scripts/tools/check_w1_registration.py).

The W1 chain runs it after check_merged_inputs and 6.05, before Step 3. Step 5
empties the staging graph, and residuals_expect can only read it while it is
still the batch-0 build, so the chain must stop unless every expected file and
fragment, and the merged allowlist's sha256 file, is committed, the merged
allowlist is the registered one, and the fresh 6.05 output is the one
relations_expected.json registered. Each test builds a throwaway git checkout:
the fragments merged by the real diff_kg --merge-out --sha-out, the 6.05 output
and report written with relation_postprocess's own serialize and
expected_after_10_2 (test_check_edge_set.write_reference).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from relation_extraction import relation_postprocess as pp
from scripts.tools import check_edge_set as ces
from scripts.tools import check_w1_registration as cwr
from scripts.tools import diff_kg as dk
from test_check_edge_set import ROWS, write_reference

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
       "-c", "core.hooksPath=/dev/null")
E = "config/kg_expect/batch1_w1/"
FRAGMENT_ENTRIES = {
    "relations_allow.yaml": {"section": "relationships", "key": "FATHER_OF", "delta": -597, "reason": "1A"},
    "residuals_allow.yaml": {"section": "mention_count", "key": "event:shanshangbaoxun", "delta": -22,
                             "reason": "K10"},
    "xref_allow.yaml": {"section": "xrefs", "key": "source=tsk", "delta": -68, "reason": "1B"},
}
REPORT = "output/relations_clean.report.json"


def git(root: Path, *args: str) -> None:
    subprocess.run([*GIT, "-C", str(root), *args], check=True, capture_output=True)


def commit(root: Path, *paths: str) -> None:
    git(root, "add", "--", *paths)
    git(root, "commit", "-q", "-m", "register")


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_fragment(root: Path, name: str, **change) -> None:
    write(root, E + name, dk.render_allowlist([{**FRAGMENT_ENTRIES[name], **change}], [f"{name} fragment"]))


def merge(root: Path) -> None:
    argv = ["--merge-out", cwr.MERGED, "--sha-out", cwr.MERGED_SHA]
    assert dk.main([*argv, *[a for rel in cwr.FRAGMENTS for a in ("--allow", rel)]]) == 0


def write_605(root: Path, rows=ROWS) -> dict:
    """output/relations_clean.jsonl and its report; the shas relations_expect would register."""
    (root / "output").mkdir(exist_ok=True)
    report = write_reference(root / "output", rows)
    data = json.loads(report.read_bytes())
    return {"report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
            "output_sha256": data["output"]["sha256"],
            "edge_set_sha256": data["expected_after_10_2"]["edge_set_sha256"]}


def expected(shas: dict) -> str:
    return json.dumps({"version": 1, "pp_version": "pp-test", **shas}, indent=2) + "\n"


@pytest.fixture
def checkout(tmp_path, monkeypatch, capsys):
    """A checkout after W1 pre-registration: the six files and the merged sha256 committed, the merged
    allowlist written but not committed (that waits for R4), and a fresh 6.05 output in output/."""
    def no_target(*_, **__):
        raise AssertionError("the registration check must not resolve a database target")
    monkeypatch.setattr(dk, "resolve_target", no_target)
    monkeypatch.setattr(ces, "resolve_target", no_target)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    monkeypatch.chdir(root)   # diff_kg --merge-out runs from the project root, as the runbook says
    for name in FRAGMENT_ENTRIES:
        write_fragment(root, name)
    write(root, E + "xref.json", '{"fingerprint": "e522411e"}\n')
    write(root, E + "residuals_expected.json", '{"validate_kg": {"R1": {"a": 1938, "b": 2124}}}\n')
    write(root, cwr.RELATIONS_EXPECTED, expected(write_605(root)))
    merge(root)
    commit(root, *cwr.REGISTERED)
    capsys.readouterr()
    return root


def run(root: Path, capsys, *extra: str) -> SimpleNamespace:
    code = cwr.main(["--root", str(root), *extra])
    out = capsys.readouterr().out
    rows = {m.group(2): m.group(1) for m in re.finditer(r"^  ([A-Z]+) +(\S+)  ", out, re.M)}
    return SimpleNamespace(code=code, out=out, rows=rows)


def test_registered_checkout_exits_0(checkout, capsys):
    result = run(checkout, capsys)

    assert result.code == 0, result.out
    assert result.rows == {**{rel: "OK" for rel in cwr.REGISTERED}, cwr.MERGED: "OK", REPORT: "OK"}
    assert "continue with Step 3" in result.out
    status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"], capture_output=True, text=True)
    assert f"?? {cwr.MERGED}" in status.stdout   # the merged file itself is committed after R4


def test_runbook_names_and_merge_order():
    assert cwr.REGISTERED == tuple(E + name for name in (
        "relations_expected.json", "relations_allow.yaml", "residuals_expected.json", "residuals_allow.yaml",
        "xref.json", "xref_allow.yaml", "kg_diff_allow_batch1w1.sha256"))
    assert cwr.FRAGMENTS == tuple(E + name for name in FRAGMENT_ENTRIES)
    assert cwr.MERGED == "config/kg_diff_allow_batch1w1.yaml"
    assert cwr.MERGED_SHA == E + "kg_diff_allow_batch1w1.sha256"
    assert cwr._PROJECT_ROOT / cwr.DEFAULT_REPORT == pp.DEFAULT_REPORT   # where 6.05 writes it


@pytest.mark.parametrize("rel", [E + "residuals_expected.json", E + "xref.json", E + "relations_allow.yaml",
                                 E + "kg_diff_allow_batch1w1.sha256"])
def test_a_file_never_registered_exits_1_before_step_5(checkout, capsys, rel):
    """The case the check exists for: residuals_expect forgotten, Step 5 would wipe its b side for good."""
    git(checkout, "rm", "-q", "--", rel)
    git(checkout, "commit", "-q", "-m", "forget")

    result = run(checkout, capsys)

    assert result.code == 1
    assert result.rows[rel] == "MISSING"
    for needle in ("STOP: not as registered", "Do not run Step 3", "Step 5", "residuals_expect", "exit 2"):
        assert needle in result.out, needle


@pytest.mark.parametrize("staged", [False, True], ids=["untracked", "added"])
def test_a_file_written_but_not_committed_exits_1(checkout, capsys, staged):
    rel = E + "residuals_expected.json"
    git(checkout, "rm", "-q", "--cached", "--", rel)
    git(checkout, "commit", "-q", "-m", "untrack")
    if staged:
        git(checkout, "add", "--", rel)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[rel] == "UNCOMMITTED"
    assert "not committed at HEAD" in result.out


@pytest.mark.parametrize("staged", [False, True], ids=["worktree", "index"])
def test_a_registered_file_edited_since_its_commit_exits_1(checkout, capsys, staged):
    rel = E + "xref.json"
    (checkout / rel).write_text('{"fingerprint": "edited"}\n', encoding="utf-8")
    if staged:
        git(checkout, "add", "--", rel)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[rel] == "MODIFIED"
    assert result.rows[cwr.MERGED] == "OK" and result.rows[REPORT] == "OK"


def test_an_empty_registered_file_exits_1(checkout, capsys):
    rel = E + "xref_allow.yaml"
    write(checkout, rel, "")
    commit(checkout, rel)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[rel] == "EMPTY"


def test_the_merged_allowlist_missing_exits_1(checkout, capsys):
    (checkout / cwr.MERGED).unlink()

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.MERGED] == "MISSING"


def test_the_merged_allowlist_edited_after_registration_exits_1(checkout, capsys):
    merged = checkout / cwr.MERGED
    registered = hashlib.sha256(merged.read_bytes()).hexdigest()
    merged.write_text(merged.read_text(encoding="utf-8").replace("delta: -22", "delta: -23"), encoding="utf-8")

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.MERGED] == "MISMATCH"
    assert registered in result.out and hashlib.sha256(merged.read_bytes()).hexdigest() in result.out


def test_a_merge_of_older_fragments_exits_1(checkout, capsys):
    """Fragment regenerated and committed after the merge: merged file and sha256 agree, but are stale."""
    write_fragment(checkout, "relations_allow.yaml", delta=-598)
    commit(checkout, E + "relations_allow.yaml")

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.MERGED] == "MISMATCH"
    assert "not the --merge-out of the registered fragments" in result.out
    assert result.rows[E + "relations_allow.yaml"] == "OK"


def test_a_remerge_whose_sha256_is_not_committed_exits_1(checkout, capsys):
    write_fragment(checkout, "relations_allow.yaml", delta=-598)
    commit(checkout, E + "relations_allow.yaml")
    merge(checkout)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.MERGED_SHA] == "MODIFIED"
    assert result.rows[cwr.MERGED] == "OK"


@pytest.mark.parametrize("text", [
    "0123  config/kg_diff_allow_batch1w1.yaml\n",
    "{sha}  config/kg_diff_allow_batch1w1.yaml\n{sha}  config/kg_diff_allow_batch1w1.yaml\n",
    "{sha}  config/kg_diff_allow_batch1w0.yaml\n",
    "{sha} config/kg_diff_allow_batch1w1.yaml\n",
], ids=["short", "two-lines", "other-file", "one-space"])
def test_a_malformed_registered_sha256_exits_1(checkout, capsys, text):
    sha = hashlib.sha256((checkout / cwr.MERGED).read_bytes()).hexdigest()
    write(checkout, cwr.MERGED_SHA, text.format(sha=sha))
    commit(checkout, cwr.MERGED_SHA)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.MERGED] == "INVALID"
    assert result.rows[cwr.MERGED_SHA] == "OK"


def test_a_6_05_output_that_is_not_the_registered_one_exits_1(checkout, capsys):
    registered = json.loads((checkout / cwr.RELATIONS_EXPECTED).read_text(encoding="utf-8"))
    now = write_605(checkout, ROWS[1:])

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[REPORT] == "MISMATCH"
    for field in cwr.SHA_FIELDS:
        assert registered[field] != now[field]
        assert f"{field} {now[field]}, registered {registered[field]}" in result.out


def test_a_6_05_output_rewritten_after_its_report_exits_1(checkout, capsys):
    clean = checkout / "output" / "relations_clean.jsonl"
    clean.write_bytes(pp.serialize(ROWS[1:]))

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[REPORT] == "INVALID"
    assert "does not hash to the report's output.sha256" in result.out


def test_no_6_05_report_exits_1(checkout, capsys):
    (checkout / REPORT).unlink()

    assert run(checkout, capsys).rows[REPORT] == "MISSING"


def test_report_flag_points_at_another_report(checkout, capsys, tmp_path):
    moved = tmp_path / "elsewhere.report.json"
    (checkout / REPORT).rename(moved)

    result = run(checkout, capsys, "--report", str(moved))

    assert result.code == 0 and result.rows[str(moved)] == "OK"


@pytest.mark.parametrize("doc", [{"report_sha256": "0" * 64, "output_sha256": "0" * 64}, ["not", "a", "dict"]])
def test_relations_expected_without_its_shas_exits_1(checkout, capsys, doc):
    write(checkout, cwr.RELATIONS_EXPECTED, json.dumps(doc) + "\n")
    commit(checkout, cwr.RELATIONS_EXPECTED)

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[REPORT] == "INVALID"
    assert result.rows[cwr.RELATIONS_EXPECTED] == "OK"


def test_a_directory_without_git_or_commits_exits_2(tmp_path, capsys):
    assert cwr.main(["--root", str(tmp_path)]) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out
    git(tmp_path, "init", "-q")
    assert cwr.main(["--root", str(tmp_path)]) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out

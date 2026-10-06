"""W1 pre-registration pre-flight (scripts/tools/check_w1_registration.py).

The W1 chain runs it after check_merged_inputs and 6.05, before Step 3. Step 5
empties the staging graph, and residuals_expect can only read it while it is
still the batch-0 build, so the chain must stop unless every expected file and
fragment, and the merged allowlist's sha256 file, is committed, the three
expected files hold what their tools write (residuals_expected.json passes
residuals_expect's own loader, the one --check runs at R2), the merged
allowlist is the registered one, and the fresh 6.05 output is the one
relations_expected.json registered. It also refuses to let 8a/8b --recreate the
batch-0 control: HEAD's scripts/tools/staging.env and the shell's
QDRANT_ENTITY_COLLECTION must both be bible_entities_v3 (decision O7, confirmed
2026-10-06). And Step 3 and Step 5 must not start without R0 item 9's batch-0
staging backups (decision Q7: a rejection at W1 step 4 restores them): both
dumps under --backup-dir exist, are not empty, and hash to the one line
SHA256SUMS lists for each. Each test builds a throwaway git checkout:
the fragments merged by the real diff_kg --merge-out --sha-out, the 6.05 output
and report written with relation_postprocess's own serialize and
expected_after_10_2 (test_check_edge_set.write_reference), and
residuals_expected.json written by residuals_expect.build itself.
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
from scripts.tools import residuals_expect as rx
from test_check_edge_set import ROWS, write_reference

ROOT = Path(__file__).resolve().parents[2]
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
STAGING_ENV = "scripts/tools/staging.env"
COLLECTION = "QDRANT_ENTITY_COLLECTION"   # the row's name
W1_COLLECTION = "bible_entities_v3"
RESIDUALS = E + "residuals_expected.json"
XREF = E + "xref.json"
SIDES = {"a": ("prod", "bolt://localhost:7687"), "b": ("staging", "bolt://localhost:7688")}
BACKUP = "bak/x"   # bak/$D of the W1 R0 date
DUMPS = ("neo4j_staging/neo4j.dump", "postgres/bible_rag_staging.dump")
BACKUP_ROWS = tuple(f"{BACKUP}/{rel}" for rel in DUMPS)
# xref_probe expect's document (W1's counts); fingerprint --expect reads version, fingerprint, xref_provenance
XREF_DOC = {"version": 1, "inputs": {"relationships_sha256": "1" * 64, "embedding_queue_sha256": "2" * 64,
                                     "tsk_sha256": "3" * 64},
            "counts": {"curated_rows": 932, "attached": 924, "curated_without_tsk": 8, "pure_tsk": 249_434,
                       "total": 250_366, "votes_edges": 250_358},
            "xref_provenance": {"source=markdown curated=True tsk=False": 8,
                                "source=markdown curated=True tsk=True": 766,
                                "source=supplementary curated=True tsk=True": 158,
                                "source=tsk curated=False tsk=True": 249_434},
            "xrefs_by_source": {"markdown": 774, "supplementary": 158, "tsk": 249_434},
            "fingerprint": hashlib.sha256(b"W1 xref").hexdigest()}


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


def residuals_doc() -> dict:
    """residuals_expected.json exactly as residuals_expect.build writes it, from a tiny batch-0 pair."""
    def side(mention_count: int, props: dict) -> dict:
        entity = {"entity_id": "event:shanshangbaoxun", "description": "登山寶訓", "aliases": [],
                  "mention_count": mention_count}
        return {"entities": {entity["entity_id"]: entity}, "sourced": 0, "nodes": 13_589, "relationships": 319_988,
                "mentions": {("Pericope", "mat_005_001", "event:shanshangbaoxun"): props}}
    targets = {key: SimpleNamespace(name=name, neo4j_uri=uri) for key, (name, uri) in SIDES.items()}
    sides = {"a": side(23, {"start_pos": 0}), "b": side(1, {"start_pos": 0, "source_granularity": "pericope"})}
    r1 = {key: (n, {"origin": f"live:{SIDES[key][0]} ({SIDES[key][1]})", "sha256": "0" * 64})
          for key, n in (("a", 1938), ("b", 2124))}
    return rx.build(targets, sides, r1, "2026-10-06T01:20:10+08:00")[0]


def write_staging_env(root: Path, collection: str) -> None:
    """The real staging.env, its entity collection set to `collection`."""
    text = (ROOT / STAGING_ENV).read_text(encoding="utf-8")
    line = re.compile(rf"^export {COLLECTION}=.*$", re.M)
    assert len(line.findall(text)) == 1, text
    write(root, STAGING_ENV, line.sub(f"export {COLLECTION}={collection}", text))


def write_backup(root: Path, contents=(b"NEO4J DUMP", b"PG DUMP")) -> Path:
    """R0 item 9's two dumps and SHA256SUMS as its block leaves them: `sha256sum ./… >> SHA256SUMS` run in
    bak/$D, after a line R0 wrote earlier for the prod dump (another path ending in neo4j.dump)."""
    backup = root / BACKUP
    lines = [f"{hashlib.sha256(b'prod').hexdigest()}  ./neo4j/neo4j.dump\n"]
    for rel, data in zip(DUMPS, contents):
        write(backup, rel, "").write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  ./{rel}\n")
    write(backup, cwr.BACKUP_SUMS, "".join(lines))
    return backup


def write_json(root: Path, rel: str, doc) -> None:
    write(root, rel, json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


@pytest.fixture
def checkout(tmp_path, monkeypatch, capsys):
    """A checkout after W1 pre-registration: the six files and the merged sha256 committed, the merged
    allowlist written but not committed (that waits for R4), and a fresh 6.05 output in output/; staging.env
    bumped to v3 and committed (R0 item 8), the staging shell holding v3, and R0 item 9's backups in bak/x."""
    def no_target(*_, **__):
        raise AssertionError("the registration check must not resolve a database target")
    monkeypatch.setattr(dk, "resolve_target", no_target)
    monkeypatch.setattr(ces, "resolve_target", no_target)
    monkeypatch.setattr(rx, "resolve_target", no_target)
    monkeypatch.setattr(rx, "git_head", lambda: "0123456789abcdef0123456789abcdef01234567")
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    monkeypatch.chdir(root)   # diff_kg --merge-out runs from the project root, as the runbook says
    for name in FRAGMENT_ENTRIES:
        write_fragment(root, name)
    write_json(root, XREF, XREF_DOC)
    write_json(root, RESIDUALS, residuals_doc())
    write(root, cwr.RELATIONS_EXPECTED, expected(write_605(root)))
    merge(root)
    write_staging_env(root, W1_COLLECTION)
    commit(root, *cwr.REGISTERED, STAGING_ENV)
    monkeypatch.setenv(COLLECTION, W1_COLLECTION)
    write_backup(root)   # untracked, as bak/ is
    capsys.readouterr()
    return root


def run(root: Path, capsys, *extra: str, backup: bool = True) -> SimpleNamespace:
    code = cwr.main(["--root", str(root), *(["--backup-dir", str(root / BACKUP)] if backup else []), *extra])
    out = capsys.readouterr().out
    found = list(re.finditer(r"^  ([A-Z]+) +(\S+)  (.*)$", out, re.M))
    return SimpleNamespace(code=code, out=out, rows={m[2]: m[1] for m in found}, texts={m[2]: m[3] for m in found})


def test_registered_checkout_exits_0(checkout, capsys):
    result = run(checkout, capsys)

    assert result.code == 0, result.out
    assert result.rows == {**{rel: "OK" for rel in cwr.REGISTERED}, cwr.MERGED: "OK", REPORT: "OK", COLLECTION: "OK",
                           **{name: "OK" for name in BACKUP_ROWS}}
    assert W1_COLLECTION in result.texts[COLLECTION] and "bible_entities_v2" in result.texts[COLLECTION]
    assert "continue with Step 3" in result.out
    digests = residuals_doc()["mentions_props"]["sha256"]
    for needle in ("mentions_props", digests["a"][:12], digests["b"][:12], "R1.b 2,124"):
        assert needle in result.texts[RESIDUALS], needle
    assert XREF_DOC["fingerprint"][:12] in result.texts[XREF]
    assert "version 1" in result.texts[cwr.RELATIONS_EXPECTED]
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
    assert (cwr.STAGING_ENV, cwr.W1_COLLECTION, cwr.BATCH0_COLLECTION) == (
        STAGING_ENV, W1_COLLECTION, "bible_entities_v2")
    assert (cwr.BATCH0_BACKUPS, cwr.BACKUP_SUMS) == (DUMPS, "SHA256SUMS")   # what R0 item 9 writes


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
    assert result.rows[cwr.RELATIONS_EXPECTED] == "INVALID"   # committed, but not what relations_expect writes


# --- the expected files' content: committed and unmodified is not enough -------------

def _commit_broken(root: Path, rel: str, doc) -> None:
    write(root, rel, doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False) + "\n")
    commit(root, rel)


def _only_invalid(result, rel: str) -> None:
    assert result.code == 1 and result.rows[rel] == "INVALID", result.out
    assert {name for name, status in result.rows.items() if status != "OK"} == {rel}, result.out
    for needle in ("STOP: not as registered", "Do not run Step 3", "Step 5", "residuals_expect"):
        assert needle in result.out, needle


BROKEN_RESIDUALS = {
    "no-mentions-props": lambda doc: doc.pop("mentions_props"),     # the pre-bd8d71c format, still in scratch
    "no-digests": lambda doc: doc["mentions_props"].pop("sha256"),
    "b-sourced": lambda doc: doc["basis"]["b"].update(sourced_semantic_edges=5616),   # read off a W1 build
    "r1-not-integer": lambda doc: doc["validate_kg"]["R1"].update(b="2124"),
    "no-basis-target": lambda doc: doc["basis"]["a"].pop("target"),
}


@pytest.mark.parametrize("broken", [*BROKEN_RESIDUALS, "not-json"])
def test_a_residuals_expected_json_its_tool_would_refuse_exits_1(checkout, capsys, broken):
    """Committed and unmodified, the pre-mentions_props file passed; Step 5 then wiped the batch-0
    staging and R2's residuals_expect --check exited 2 with nothing left to regenerate it from."""
    doc = residuals_doc()
    if broken == "not-json":
        doc = "{\n"
    else:
        BROKEN_RESIDUALS[broken](doc)
    _commit_broken(checkout, RESIDUALS, doc)

    result = run(checkout, capsys)

    _only_invalid(result, RESIDUALS)
    assert "not a residuals_expected.json" in result.texts[RESIDUALS]


@pytest.mark.parametrize("change", [
    lambda doc: doc.pop("version"),
    lambda doc: doc.update(fingerprint="e522411e"),                          # not 64 hex
    lambda doc: doc.pop("xref_provenance"),
    lambda doc: doc["xref_provenance"].update({"source=tsk curated=False tsk=True": "249434"}),
], ids=["no-version", "short-fingerprint", "no-provenance", "provenance-not-a-count"])
def test_an_xref_json_without_what_fingerprint_expect_reads_exits_1(checkout, capsys, change):
    doc = json.loads(json.dumps(XREF_DOC))
    change(doc)
    _commit_broken(checkout, XREF, doc)

    _only_invalid(run(checkout, capsys), XREF)


def test_a_relations_expected_json_of_another_version_exits_1(checkout, capsys):
    doc = json.loads((checkout / cwr.RELATIONS_EXPECTED).read_text(encoding="utf-8"))
    _commit_broken(checkout, cwr.RELATIONS_EXPECTED, {**doc, "version": 2})

    result = run(checkout, capsys)

    assert result.code == 1 and result.rows[cwr.RELATIONS_EXPECTED] == "INVALID"
    assert "version" in result.texts[cwr.RELATIONS_EXPECTED]


def test_a_directory_without_git_or_commits_exits_2(tmp_path, capsys):
    assert cwr.main(["--root", str(tmp_path)]) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out
    git(tmp_path, "init", "-q")
    assert cwr.main(["--root", str(tmp_path)]) == 2
    assert "CANNOT CHECK" in capsys.readouterr().out


# --- the staging entity collection: 8a/8b --recreate must never reach the batch-0 control --

@pytest.mark.parametrize("head, shell, named", [
    ("bible_entities_v2", W1_COLLECTION, [f"{STAGING_ENV} at HEAD has 'bible_entities_v2' (the batch-0 control)"]),
    (W1_COLLECTION, "bible_entities_v2", ["this shell has 'bible_entities_v2' (the batch-0 control)"]),
    (W1_COLLECTION, None, ["this shell has it unset"]),
    ("bible_entities_v4", "bible_entities_v4", ["at HEAD has 'bible_entities_v4'", "this shell has 'bible_entities_v4'"]),
], ids=["not-bumped", "shell-not-resourced", "shell-not-sourced", "w2-collection"])
def test_a_staging_collection_other_than_v3_exits_1(checkout, capsys, monkeypatch, head, shell, named):
    if head != W1_COLLECTION:   # the fixture committed v3
        write_staging_env(checkout, head)
        commit(checkout, STAGING_ENV)
    if shell is None:
        monkeypatch.delenv(COLLECTION)
    else:
        monkeypatch.setenv(COLLECTION, shell)

    result = run(checkout, capsys)

    _only_invalid(result, COLLECTION)
    for needle in (*named, f"W1 writes {W1_COLLECTION}", "--recreate"):
        assert needle in result.texts[COLLECTION], needle
    for needle in ("R0 item 8", "bible_entities_v2 is the batch-0 staging collection"):
        assert needle in result.out, needle


def test_a_bump_on_disk_but_not_committed_exits_1(checkout, capsys):
    """The shell sourced the bumped file, but HEAD (what the W1 record and the :w1 image pin) still says v2."""
    write_staging_env(checkout, "bible_entities_v2")
    commit(checkout, STAGING_ENV)
    write_staging_env(checkout, W1_COLLECTION)

    result = run(checkout, capsys)

    _only_invalid(result, COLLECTION)
    assert "at HEAD has 'bible_entities_v2'" in result.texts[COLLECTION]


def test_a_staging_env_missing_at_head_exits_1(checkout, capsys):
    git(checkout, "rm", "-q", "--", STAGING_ENV)
    git(checkout, "commit", "-q", "-m", "drop")

    result = run(checkout, capsys)

    _only_invalid(result, COLLECTION)
    assert f"{STAGING_ENV} is not committed at HEAD" in result.texts[COLLECTION]


@pytest.mark.parametrize("text, value", [
    ("export QDRANT_ENTITY_COLLECTION=bible_entities_v3\n", W1_COLLECTION),
    ("QDRANT_ENTITY_COLLECTION=bible_entities_v3\n", W1_COLLECTION),
    ("export QDRANT_ENTITY_COLLECTION=bible_entities_v3   # W1\n", W1_COLLECTION),
    ("export QDRANT_ENTITY_COLLECTION='bible_entities_v3'\n", W1_COLLECTION),
    ("export QDRANT_ENTITY_COLLECTION=bible_entities_v3\nexport QDRANT_ENTITY_COLLECTION=bible_entities_v2\n",
     "bible_entities_v2"),   # bash keeps the last assignment
    ("# export QDRANT_ENTITY_COLLECTION=bible_entities_v3\n", None),
    ("export QDRANT_ENTITY_COLLECTION=${QDRANT_ENTITY_COLLECTION:-bible_entities_v3}\n",
     "${QDRANT_ENTITY_COLLECTION:-bible_entities_v3}"),   # not a literal: never equals v3, so INVALID
])
def test_the_collection_is_read_as_bash_assigns_it(text, value):
    assert cwr.assigned_collection(text) == value


def test_the_real_staging_env_names_one_versioned_collection():
    # v2 until R0 item 8 commits the bump, v3 after: either way the parser reads the real file's format
    assert re.fullmatch(r"bible_entities_v\d+", cwr.committed_collection(ROOT) or ""), cwr.committed_collection(ROOT)


# --- R0 item 9's batch-0 staging backups: Step 3 and Step 5 never start without them --------

def _only(result, name: str, status: str) -> None:
    assert result.code == 1 and result.rows[name] == status, result.out
    assert {n for n, s in result.rows.items() if s != "OK"} == {name}, result.out
    for needle in ("STOP: not as registered", "Do not run Step 3", "R0 item 9", "batch-0 staging backup"):
        assert needle in result.out, needle


def test_the_backup_rows_name_both_dumps_and_their_sha256(checkout, capsys):
    result = run(checkout, capsys)

    for name, data in zip(BACKUP_ROWS, (b"NEO4J DUMP", b"PG DUMP")):
        assert result.rows[name] == "OK" and hashlib.sha256(data).hexdigest()[:12] in result.texts[name]
        assert cwr.BACKUP_SUMS in result.texts[name]


def test_without_a_backup_dir_both_rows_are_invalid(checkout, capsys):
    result = run(checkout, capsys, backup=False)

    assert result.code == 1
    names = {f"bak/$D/{rel}" for rel in DUMPS}
    assert {n for n, s in result.rows.items() if s != "OK"} == names, result.out
    assert all(result.rows[n] == "INVALID" and "--backup-dir" in result.texts[n] for n in names), result.out


def _sums(root: Path) -> Path:
    return root / BACKUP / cwr.BACKUP_SUMS


@pytest.mark.parametrize("dump", [0, 1], ids=DUMPS)
def test_a_missing_backup_exits_1(checkout, capsys, dump):
    (checkout / BACKUP_ROWS[dump]).unlink()

    _only(run(checkout, capsys), BACKUP_ROWS[dump], "MISSING")


def test_an_empty_backup_exits_1_even_when_listed(checkout, capsys):
    write_backup(checkout, contents=(b"NEO4J DUMP", b""))   # a 0-byte file and its (valid) sha256 line

    _only(run(checkout, capsys), BACKUP_ROWS[1], "EMPTY")


@pytest.mark.parametrize("dump", [0, 1], ids=DUMPS)
def test_a_backup_sha256sums_does_not_list_exits_1(checkout, capsys, dump):
    lines = _sums(checkout).read_text(encoding="utf-8").splitlines(keepends=True)
    _sums(checkout).write_text("".join(line for line in lines if not line.endswith(f"./{DUMPS[dump]}\n")),
                               encoding="utf-8")

    result = run(checkout, capsys)

    _only(result, BACKUP_ROWS[dump], "INVALID")
    assert f"lists no sha256 for ./{DUMPS[dump]}" in result.texts[BACKUP_ROWS[dump]]


def test_no_sha256sums_at_all_exits_1(checkout, capsys):
    _sums(checkout).unlink()

    result = run(checkout, capsys)

    assert result.code == 1 and all(result.rows[name] == "INVALID" for name in BACKUP_ROWS), result.out


def test_a_backup_changed_after_its_sha256_line_exits_1(checkout, capsys):
    listed = hashlib.sha256(b"NEO4J DUMP").hexdigest()
    (checkout / BACKUP_ROWS[0]).write_bytes(b"another dump")

    result = run(checkout, capsys)

    _only(result, BACKUP_ROWS[0], "MISMATCH")
    assert listed in result.texts[BACKUP_ROWS[0]]


def test_two_different_sha256_lines_for_one_backup_exit_1(checkout, capsys):
    with _sums(checkout).open("a", encoding="utf-8") as sums:
        sums.write(f"{hashlib.sha256(b'other').hexdigest()}  ./{DUMPS[1]}\n")

    result = run(checkout, capsys)

    _only(result, BACKUP_ROWS[1], "INVALID")
    assert "2 different sha256" in result.texts[BACKUP_ROWS[1]]

#!/usr/bin/env python3
"""W1 pre-registration pre-flight, fail-closed: run in the W1 rebuild chain
after check_merged_inputs and 6.05, before Step 3.

The W1 expected files and allowlist fragments are registered (committed)
before the staging rebuild, and the rebuild only compares against them
(docs/records/2026-10-04_kg_batch1_plan.md §3; docs/staging_promotion.md R2).
One of them cannot be made later: residuals_expect reads the staging graph
while it is still the batch-0 build, and refuses a b side that holds semantic
edges with a source (exit 2). Step 5 empties that graph and 6.1 writes such
edges, so a residuals_expected.json missing at Step 5, or one --check at R2
refuses (exit 2, e.g. one written before mentions_props existed), is lost for
good. Before this check the chain only compared xref.json. This one reads no
database:

  registered  each file the runbook registers under config/kg_expect/batch1_w1/
              (relations_expected.json, relations_allow.yaml,
              residuals_expected.json, residuals_allow.yaml, xref.json,
              xref_allow.yaml, kg_diff_allow_batch1w1.sha256) exists, is not
              empty and equals its blob at HEAD: committed, and no edit since,
              staged or not. The three expected files must also hold what their
              tool writes and the later gates read (INVALID otherwise):
              residuals_expected.json passes residuals_expect.load_registered,
              the loader of --check (version, mentions_props with both per-side
              digests, basis targets read with no sourced semantic edge, R1
              integers); relations_expected.json is version 1 with the three
              sha256 the 6.05 row compares, and check_edge_set --expect loads
              it; xref.json is version 1 with the fingerprint and the
              xref_provenance counts xref_probe fingerprint --expect compares.
  merged      config/kg_diff_allow_batch1w1.yaml hashes to the sha256 that
              kg_diff_allow_batch1w1.sha256 registers (the sha256sum line
              diff_kg --merge-out --sha-out writes), and is byte for byte the
              --merge-out of the three registered fragments in the runbook's
              order (relations, residuals, xref). The merged file itself is
              committed only after R4, with the ratchet (plan §3), so what is
              registered before the rebuild is its sha256.
  6.05        the fresh 6.05 report (--report) hashes to relations_expected.json's
              report_sha256; the relations_clean.jsonl it names, checked as
              check_edge_set checks a report (a relative output.path resolves
              against this tool's checkout, as 6.1 reads it), hashes to
              output_sha256; and its edge set after 10.2 is edge_set_sha256.
  collection  QDRANT_ENTITY_COLLECTION is bible_entities_v3 both in
              scripts/tools/staging.env at HEAD (the R0 item 8 bump, committed)
              and in this shell's environment (what 8a/8b --recreate drop and
              rebuild). bible_entities_v2 is the batch-0 staging build, kept as
              W2's control (decision O7, confirmed by Kay 2026-10-06); a v2, any
              other value, an unset variable or a staging.env missing at HEAD is
              INVALID, so the chain stops before Step 3 and never reaches 8a.

Every check runs and prints one row: OK, MISSING, EMPTY, UNREADABLE,
UNCOMMITTED (not in HEAD: untracked, or added but not committed), MODIFIED
(differs from HEAD), MISMATCH or INVALID. W1 only.

Exit codes: 0 everything is registered, the 6.05 output is the registered one and
the staging entity collection is bible_entities_v3; 1 any row is not OK (STOP; do not
run Step 3); 2 cannot check (git does not run, or --root is not a git checkout with a
commit).

Usage (from the project root, in the W1 chain right after 6.05, in the shell
that sourced scripts/tools/staging.env):
    scripts/.venv/bin/python scripts/tools/check_w1_registration.py
    scripts/.venv/bin/python scripts/tools/check_w1_registration.py --root . \\
        --report output/relations_clean.report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from scripts.tools import diff_kg, residuals_expect  # noqa: E402
from scripts.tools.check_edge_set import CannotCheck as BadReport, load_expect, load_reference  # noqa: E402

EXPECT_DIR = "config/kg_expect/batch1_w1/"
# the merge order of docs/staging_promotion.md R2 item 2: 1A relations, 1A residuals, 1B xref
FRAGMENTS = tuple(EXPECT_DIR + name for name in ("relations_allow.yaml", "residuals_allow.yaml", "xref_allow.yaml"))
RELATIONS_EXPECTED = EXPECT_DIR + "relations_expected.json"
RESIDUALS_EXPECTED = EXPECT_DIR + "residuals_expected.json"
XREF_EXPECTED = EXPECT_DIR + "xref.json"
MERGED = "config/kg_diff_allow_batch1w1.yaml"
MERGED_SHA = EXPECT_DIR + "kg_diff_allow_batch1w1.sha256"
REGISTERED = (RELATIONS_EXPECTED, FRAGMENTS[0], RESIDUALS_EXPECTED, FRAGMENTS[1],
              XREF_EXPECTED, FRAGMENTS[2], MERGED_SHA)
DEFAULT_REPORT = Path("output") / "relations_clean.report.json"
SHA_FIELDS = ("report_sha256", "output_sha256", "edge_set_sha256")
GIT_TIMEOUT_S = 30
STAGING_ENV = "scripts/tools/staging.env"
COLLECTION_VAR = "QDRANT_ENTITY_COLLECTION"
W1_COLLECTION = "bible_entities_v3"
BATCH0_COLLECTION = "bible_entities_v2"   # the batch-0 staging build, W2's control (plan §9.1 O7)
# a line that assigns the variable, as bash reads it: optional export, the value up to the first blank
_ASSIGNMENT = re.compile(rf"^[ \t]*(?:export[ \t]+)?{COLLECTION_VAR}=(\S*)", re.M)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA_LINE = re.compile(r"([0-9a-f]{64})  (.+)")

HAZARD = (
    "Do not run Step 3. Step 5 empties the staging graph (7688), which must still be the batch-0 build "
    "when residuals_expect reads it: once the rebuild has written semantic edges with a source there, "
    "residuals_expect refuses it (exit 2) and residuals_expected.json can never be produced. Register what "
    "is missing as docs/staging_promotion.md R2 says (W1 的交叉引用檢查 item 1; item 2's --merge-out "
    "--sha-out; W1 的關係層檢查 items 1-2), commit everything under config/kg_expect/batch1_w1/ and rerun "
    "this check. An INVALID expected file was written by an older tool or edited: regenerate it with the "
    "tool at HEAD (residuals_expect only while 7688 still holds the batch-0 build), commit it and rerun. "
    "A 6.05 output that is not the registered one: find out why first (an input or PP_FILES "
    "changed); never regenerate an expected file to fit it, and never edit one after seeing a staging "
    "diff (plan §3). A QDRANT_ENTITY_COLLECTION row that is not OK: bump scripts/tools/staging.env to "
    f"{W1_COLLECTION} and commit it (docs/staging_promotion.md R0 item 8), source it again in this shell and "
    f"rerun; {BATCH0_COLLECTION} is the batch-0 staging collection, kept as W2's control, and 8a/8b --recreate "
    "would rebuild whatever collection this shell names.")


class CannotCheck(Exception):
    """git cannot read the checkout (exit 2)."""


class Failed(Exception):
    """One check's row is not OK: .status and the message."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=GIT_TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CannotCheck(f"git {' '.join(args)} in {root}: {e}") from e


def require_checkout(root: Path) -> None:
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").returncode != 0:
        raise CannotCheck(f"{root} is not a git checkout with a commit")


def _read(path: Path) -> bytes:
    """The file's bytes; Failed when it is missing, unreadable or empty."""
    if not path.is_file():
        raise Failed("MISSING", "no such file")
    try:
        data = path.read_bytes()
    except OSError as e:
        raise Failed("UNREADABLE", str(e)) from e
    if not data:
        raise Failed("EMPTY", "0 bytes")
    return data


# --- the checks: each returns the OK row's text or raises Failed ------------------------

def check_committed(root: Path, rel: str) -> str:
    """rel is a non-empty file equal to its blob at HEAD."""
    data = _read(root / rel)
    head = _git(root, "cat-file", "blob", f"HEAD:./{rel}")
    if head.returncode != 0:
        raise Failed("UNCOMMITTED", "not committed at HEAD (untracked, or added but not committed)")
    if head.stdout != data:
        raise Failed("MODIFIED", f"edited since HEAD: sha256 {_sha(data)}, at HEAD {_sha(head.stdout)}")
    return f"committed at HEAD, sha256 {_sha(data)}"


def registered_merged_sha(root: Path) -> str:
    """The sha256 that kg_diff_allow_batch1w1.sha256 registers for the merged allowlist."""
    try:
        lines = _read(root / MERGED_SHA).decode("utf-8", "replace").splitlines()
    except Failed as e:
        raise Failed("INVALID", f"no registered sha256: {MERGED_SHA}: {e}") from e
    match = _SHA_LINE.fullmatch(lines[0]) if len(lines) == 1 else None
    if not match or (root / match.group(2)).resolve() != (root / MERGED).resolve():
        raise Failed("INVALID", f"{MERGED_SHA} is not one sha256sum line for {MERGED} "
                                "(diff_kg --merge-out --sha-out writes it)")
    return match.group(1)


def check_merged(root: Path) -> str:
    """The merged allowlist is the registered one and the merge of the registered fragments."""
    want = registered_merged_sha(root)
    data = _read(root / MERGED)
    if _sha(data) != want:
        raise Failed("MISMATCH", f"sha256 {_sha(data)}, registered {want} in {MERGED_SHA}")
    try:
        text, counts = diff_kg.merge_allowlists([root / rel for rel in FRAGMENTS])
    except (OSError, ValueError) as e:
        raise Failed("INVALID", f"the registered fragments do not merge: {e}") from e
    if text.encode("utf-8") != data:
        raise Failed("MISMATCH", "not the --merge-out of the registered fragments "
                                 f"{', '.join(Path(rel).name for rel in FRAGMENTS)} in this order")
    return f"sha256 {want} as registered, the --merge-out of the registered fragments " \
           f"({' + '.join(map(str, counts))} entries)"


def _version_1(path: Path, rel: str) -> dict:
    """A version 1 JSON document; Failed INVALID otherwise (or MISSING, EMPTY, UNREADABLE)."""
    data = _read(path)
    try:
        doc = json.loads(data)
    except ValueError as e:
        raise Failed("INVALID", f"{rel} is not JSON: {e}") from e
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise Failed("INVALID", f"{rel} is not a version 1 document: version "
                                f"{doc.get('version') if isinstance(doc, dict) else None!r}")
    return doc


def registered_605(root: Path) -> dict[str, str]:
    """relations_expected.json's report, output and edge-set sha256."""
    try:
        doc = _version_1(root / RELATIONS_EXPECTED, RELATIONS_EXPECTED)
    except Failed as e:
        why = str(e) if e.status == "INVALID" else f"nothing registered: {RELATIONS_EXPECTED}: {e}"
        raise Failed("INVALID", why) from e
    shas = {field: doc.get(field) for field in SHA_FIELDS}
    missing = [field for field, sha in shas.items() if not (isinstance(sha, str) and _SHA256.fullmatch(sha))]
    if missing:
        raise Failed("INVALID", f"{RELATIONS_EXPECTED} has no {', '.join(missing)} (64 hex)")
    return shas


def check_605(root: Path, report: Path) -> str:
    """The fresh 6.05 report, its output and its edge set after 10.2 are the registered ones."""
    want = registered_605(root)
    data = _read(report)
    try:
        ref, clean = load_reference(report)
    except BadReport as e:
        raise Failed("INVALID", str(e)) from e
    got = {"report_sha256": _sha(data), "output_sha256": _sha(clean.read_bytes()), "edge_set_sha256": ref.sha256}
    differ = [f"{field} {got[field]}, registered {want[field]}" for field in SHA_FIELDS if got[field] != want[field]]
    if differ:
        raise Failed("MISMATCH", f"not the 6.05 output {RELATIONS_EXPECTED} registered: {'; '.join(differ)}")
    return (f"report {got['report_sha256'][:12]}…, output {got['output_sha256'][:12]}…, edge set "
            f"{ref.sha256[:12]}… ({ref.edges:,} edges after 10.2) as {RELATIONS_EXPECTED} registered")


# --- the expected files' content: what each tool writes and the later gates read ---------

def relations_content(root: Path) -> str:
    """version 1, the three sha256 of the 6.05 row, and check_edge_set --expect's own loader."""
    shas = registered_605(root)
    try:
        load_expect(root / RELATIONS_EXPECTED)
    except BadReport as e:
        raise Failed("INVALID", str(e)) from e
    return f"version 1, edge set {shas['edge_set_sha256'][:12]}…"


def residuals_content(root: Path) -> str:
    """residuals_expect's own loader, the one --check runs at R2 when nothing can regenerate the file."""
    try:
        doc = residuals_expect.load_registered(root / RESIDUALS_EXPECTED)
    except residuals_expect.CannotGenerate as e:
        raise Failed("INVALID", str(e)) from e
    props, r1 = doc["mentions_props"], doc["validate_kg"]["R1"]
    return (f"mentions_props of {props['edges']['a']:,} and {props['edges']['b']:,} edges, sha256 a "
            f"{props['sha256']['a'][:12]}…, b {props['sha256']['b'][:12]}…, R1.b {r1['b']:,}")


def xref_content(root: Path) -> str:
    """version 1, the fingerprint and the xref_provenance counts xref_probe fingerprint --expect compares."""
    doc = _version_1(root / XREF_EXPECTED, XREF_EXPECTED)
    fingerprint, provenance = doc.get("fingerprint"), doc.get("xref_provenance")
    if not (isinstance(fingerprint, str) and _SHA256.fullmatch(fingerprint)):
        raise Failed("INVALID", f"{XREF_EXPECTED} has no fingerprint (64 hex): {fingerprint!r}")
    if not (isinstance(provenance, dict) and provenance and all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in provenance.values())):
        raise Failed("INVALID", f"{XREF_EXPECTED} has no xref_provenance of edge counts: {str(provenance)[:200]}")
    return f"version 1, fingerprint {fingerprint[:12]}…, {len(provenance)} xref_provenance keys"


CONTENT = {RELATIONS_EXPECTED: relations_content, RESIDUALS_EXPECTED: residuals_content,
           XREF_EXPECTED: xref_content}


def check_registered(root: Path, rel: str) -> str:
    """rel is committed and unmodified; an expected file also holds what its tool writes."""
    text = check_committed(root, rel)
    return f"{text}; {CONTENT[rel](root)}" if rel in CONTENT else text


# --- the staging entity collection: 8a/8b --recreate must not reach the batch-0 control ---

def assigned_collection(text: str) -> str | None:
    """The value the last QDRANT_ENTITY_COLLECTION= line of an env file gives, quotes stripped; None if none."""
    values = _ASSIGNMENT.findall(text)
    return values[-1].strip("'\"") if values else None


def committed_collection(root: Path) -> str | None:
    """QDRANT_ENTITY_COLLECTION as scripts/tools/staging.env at HEAD sets it; Failed INVALID if not at HEAD."""
    head = _git(root, "cat-file", "blob", f"HEAD:./{STAGING_ENV}")
    if head.returncode != 0:
        raise Failed("INVALID", f"{STAGING_ENV} is not committed at HEAD")
    return assigned_collection(head.stdout.decode("utf-8", "replace"))


def _named(value: str | None) -> str:
    if value is None:
        return "it unset"
    return repr(value) + (" (the batch-0 control)" if value == BATCH0_COLLECTION else "")


def check_collection(root: Path, env: Mapping[str, str]) -> str:
    """HEAD's staging.env and this shell both name the W1 collection, never the batch-0 control."""
    found = {f"{STAGING_ENV} at HEAD": committed_collection(root), "this shell": env.get(COLLECTION_VAR)}
    wrong = [f"{where} has {_named(value)}" for where, value in found.items() if value != W1_COLLECTION]
    if wrong:
        raise Failed("INVALID", f"{'; '.join(wrong)}; W1 writes {W1_COLLECTION}, and 8a/8b --recreate drop and "
                                f"rebuild the collection this shell names")
    return (f"{W1_COLLECTION} at HEAD and in this shell; 8a/8b --recreate leave {BATCH0_COLLECTION}, "
            "the batch-0 control")


# --- run -----------------------------------------------------------------------------

def _shown(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def run_checks(root: Path, report: Path, env: Mapping[str, str] | None = None) -> list[tuple[str, str, str]]:
    """(status, name, text) per check, in order; CannotCheck when git cannot read the checkout.
    `env` is the shell's environment (default os.environ), read for QDRANT_ENTITY_COLLECTION."""
    require_checkout(root)
    env = os.environ if env is None else env
    checks = [(rel, lambda rel=rel: check_registered(root, rel)) for rel in REGISTERED]
    checks += [(MERGED, lambda: check_merged(root)), (_shown(report, root), lambda: check_605(root, report)),
               (COLLECTION_VAR, lambda: check_collection(root, env))]
    rows = []
    for name, check in checks:
        try:
            rows.append(("OK", name, check()))
        except Failed as e:
            rows.append((e.status, name, str(e)))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=_PROJECT_ROOT,
                        help=f"the git checkout whose registration is checked (default: {_PROJECT_ROOT})")
    parser.add_argument("--report", type=Path, default=None,
                        help=f"the fresh 6.05 report (default: <root>/{DEFAULT_REPORT.as_posix()})")
    args = parser.parse_args(argv)
    report = args.report or args.root / DEFAULT_REPORT
    try:
        rows = run_checks(args.root, report)
    except CannotCheck as e:
        print(f"CANNOT CHECK: {e}")
        return 2
    for status, name, text in rows:
        print(f"  {status:<12}{name}  {text}")
    failed = [name for status, name, _ in rows if status != "OK"]
    if failed:
        print(f"STOP: not as registered: {', '.join(failed)}.\n{HAZARD}")
        return 1
    print("OK: the W1 expected files (holding what their tools write), fragments and merged allowlist sha256 "
          "are committed, the merged allowlist and the 6.05 output are the registered ones, and the staging "
          f"entity collection is {W1_COLLECTION}; continue with Step 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())

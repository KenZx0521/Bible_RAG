"""Freeze records of the GEN confirmation set: the F1 manifest (prereg §3.8 F1, §2.3; store f1_manifest.json,
written once), the K0 harness record (§4.5, §8.1-1; store harness_record.json) and the 執行紀錄 anchors.

"files" maps a path to its sha256: repo-relative (this checkout) for repository files, store-relative for store
files, as g_common.backend_pins() keys its items. It holds
  the F1a group   gencard/*.py, gen_names.json, mech_g.py, mech_qg.py: these must equal store f1a_pins.json's "files"
                  (exactly the same paths and sha256 values), else the manifest is refused; ``card_paths`` is its
                  card part (gencard/*.py and gen_names.json, what F2 checks again);
  F1's own files  prompts_g.py and the writer and audit prompt files it renders (gen_g.md, audit_g.md), the
                  banned-term module banned_g.py, the constants module g_common.py (§3.9: its final sha256 goes into
                  the F1 manifest), the CLI pin json (store cli_pin.json);
  prod            ``prod_pins()``: every g_common.backend_pins() item (prompt parity and the dynasty-trigger deletion
                  rule) and every g_common.trigger_pins() item (the other files the trigger loads, §4.3); the items
                  whose sha256 g_common keeps (``kept_pins``: the r4 layer, R4_LAYER_SHA256, and the trigger's files,
                  TRIGGER_PINS_SHA256) must be at those values, else the manifest is refused (F2 step 3,
                  freeze_g.prod_trigger, needs the manifest and the files both at them: a manifest of another value
                  could never pass it).
No timestamp is inside "files": order_g derives the writing-order seed from its canonical JSON, so rewriting the
manifest with the same files gives the same order. Outside "files" the manifest records when, the git HEAD, and
the sha256 of f1a_pins.json and of the canonical "files" JSON (order_g.files_digest).
f1a_pins.json's contract (no qset builder defines it yet; minimal): {"files": {path: sha256}} over exactly the
F1a group's paths, keyed as here. The manifest is written once (an existing one refuses), and only while every
repository file it names is committed and unchanged. ``manifest_problems`` compares it later with the files now
(run_g's gate: nothing it names may change after F1, §3.8, §5.5).
The log helpers shared by run_g and f2_g: prereg.md's 「## 執行紀錄」 text and lines, and the anchor rule. An
anchor (harness-change, run --infra-fix, smoke --redo, a void record) is one whole line of the log without its leading
markdown marks (#, -, *, >), at least ANCHOR_MIN characters, on no other line of the log, not used by an earlier
record and not among the lines (sha256) that were in the log before the step it records; a substring, a short
string or an old line never passes.
The harness (every .py here and in gencard/, every tests/test_gen_confirm_*.py, prereg.md above its log) is
recorded at the K0 commit (``record_k0``, once) and at each later change (``record_change``, run_g's
harness-change), each only while git_problems() is empty and the test_gen_confirm_* suite passes in a fresh
interpreter (``suite_problems``); every entry keeps the log's line sha256 (the next anchor must be newer).
``harness_problems``: the current harness is the record's, every change's anchor still a line of the log.
Nothing here calls an LLM; only counts and sha are printed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

import g_common as GC

SCHEMA = "gen_confirm.f1_manifest.v1"
CLI_PIN = GC.CLI_PIN
F1_OWN = ("prompts_g.py", "gen_g.md", "audit_g.md", "banned_g.py", "g_common.py")
PREREG = GC.PREREG
LOG_HEADING = "\n## 執行紀錄"
HARNESS_RECORD = GC.HARNESS_RECORD
TESTS_DIR, TESTS_GLOB = GC.TESTS_DIR, "test_gen_confirm_*.py"
ANCHOR_MIN = 12                                      # characters of an anchor line
MARKS = "#-*> \t"


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


# ---------------------------------------------------------------- the log and its anchors
def log_text(prereg: Path = PREREG) -> str:
    text = Path(prereg).read_text(encoding="utf-8")
    return text.split(LOG_HEADING, 1)[1] if LOG_HEADING in text else ""


def log_lines(prereg: Path = PREREG) -> list[str]:
    """The log's non-empty lines without their leading markdown marks."""
    return [s for s in (ln.strip().lstrip(MARKS).strip() for ln in log_text(prereg).splitlines()) if s]


def lines_sha256(lines: Iterable[str]) -> list[str]:
    return sorted({GC.sha256_text(s) for s in lines})


def anchor_problems(anchor: str | None, prereg: Path = PREREG, *, used: Iterable[str] = (),
                    seen: Iterable[str] = ()) -> list[str]:
    """Why ``anchor`` cannot stand for the step it records (empty = it can); ``seen`` holds line sha256."""
    a, lines = (anchor or "").strip(), log_lines(prereg)
    out = [] if len(a) >= ANCHOR_MIN else [f"the anchor is shorter than {ANCHOR_MIN} characters"]
    n = lines.count(a)
    out += [] if n == 1 else ["the anchor is not a whole line of prereg.md's 執行紀錄" if n == 0
                              else "the anchor is on more than one line of the log"]
    out += ["the anchor was used by an earlier record"] if a in set(used) else []
    return out + (["the anchor line was in the log before this step"] if GC.sha256_text(a) in set(seen) else [])


# ---------------------------------------------------------------- the K0 harness record (§4.5, §8.1-1)
def harness_files_sha256(here: Path = GC.HERE, tests_dir: Path = TESTS_DIR) -> dict:
    """Every .py here and in gencard/, prereg.md above its log, and every test_gen_confirm_*.py (as tests/<name>)."""
    out = {p.name: GC.sha256_file(p) for p in sorted(Path(here).glob("*.py"))}
    out |= {f"gencard/{p.name}": GC.sha256_file(p) for p in sorted((Path(here) / "gencard").glob("*.py"))}
    pre = Path(here) / "prereg.md"
    if pre.is_file():
        out["prereg.md"] = GC.sha256_text(pre.read_text(encoding="utf-8").split(LOG_HEADING, 1)[0])
    return out | {f"tests/{p.name}": GC.sha256_file(p) for p in sorted(Path(tests_dir).glob(TESTS_GLOB))}


def harness_pins(here: Path = GC.HERE, tests_dir: Path = TESTS_DIR) -> dict:
    files = harness_files_sha256(here, tests_dir)
    return {"files_sha256": files, "sha256": GC.sha256_text(json.dumps(files, sort_keys=True))}


def harness_change(old: dict, new: dict, note: str) -> dict:
    a, b = old["files_sha256"], new["files_sha256"]
    return {"t": now(), "from": old["sha256"], "to": new["sha256"], "files": sorted(n for n in a.keys() | b.keys()
                                                                                   if a.get(n) != b.get(n)),
            "note": note, "git_head": _git(GC.REPO, "rev-parse", "HEAD").stdout.strip() or None}


def git_problems(prereg: Path = PREREG, harness_dir: Path = GC.HERE, tests_dir: Path = TESTS_DIR) -> list[str]:
    """prereg.md committed and unchanged; no edited or untracked file in the harness directory (gencard/ included)
    or among this experiment's test files."""
    out = []
    if _git(prereg.parent, "ls-files", "--error-unmatch", prereg.name).returncode != 0:
        out.append("prereg.md not committed")
    elif _git(prereg.parent, "diff", "--quiet", "HEAD", "--", prereg.name).returncode != 0:
        out.append("prereg.md changed since the last commit")
    st = _git(harness_dir, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if st.returncode != 0 or st.stdout.strip():
        out.append("harness files changed or untracked since the last commit")
    ts = _git(tests_dir, "status", "--porcelain", "--untracked-files=all", "--", TESTS_GLOB)
    if ts.returncode != 0 or ts.stdout.strip():
        out.append("test files changed or untracked since the last commit")
    return out


def suite_problems() -> list[str]:
    """The test_gen_confirm_* suite in a fresh interpreter (K0-合成, §8.1-1): [] when it passes."""
    files = sorted(str(p) for p in Path(TESTS_DIR).glob(TESTS_GLOB))
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=GC.REPO,
                       capture_output=True, text=True, timeout=3600)
    last = (r.stdout.strip().splitlines() or ["no output"])[-1]
    return [] if r.returncode == 0 else [f"the test_gen_confirm_* suite fails ({last})"]


def _record_args(record, prereg, git, pins, tests) -> tuple:
    return (Path(record or HARNESS_RECORD), Path(prereg or PREREG), git or git_problems, pins or harness_pins,
            tests or suite_problems)


def record_k0(*, record: Path | None = None, prereg: Path | None = None, git=None, pins=None, tests=None) -> dict:
    """The harness record at the K0 commit (once), with the log's line sha256 at that time."""
    record, prereg, git, pins, tests = _record_args(record, prereg, git, pins, tests)
    bad = [f"{record.name} exists: the K0 harness record is made once"] if record.exists() else git()
    bad = bad or tests()
    if bad:
        raise SystemExit(f"K0 harness record refused: {bad}")
    p, head = pins(), _git(GC.REPO, "rev-parse", "HEAD").stdout.strip() or None
    k0 = {**p, "t": now(), "git_head": head, "log_lines_sha256": lines_sha256(log_lines(prereg))}
    doc = {"schema": "gen_confirm.harness_record.v1", "k0": k0, "changes": [], "current": p}
    GC.write_json(record, doc)
    return doc


def record_change(anchor: str, *, record: Path | None = None, prereg: Path | None = None, git=None, pins=None,
                  tests=None) -> dict:
    """A harness change after K0: committed, its anchor a new log line since the record's last entry, the suite green."""
    record, prereg, git, pins, tests = _record_args(record, prereg, git, pins, tests)
    if not record.is_file():
        raise SystemExit(f"{record} missing: harness-k0 first")
    doc, p = GC.read_json(record), pins()
    last = doc["changes"][-1] if doc["changes"] else doc["k0"]
    bad = git() + anchor_problems(anchor, prereg, used=[c["note"] for c in doc["changes"]],
                                  seen=last["log_lines_sha256"])
    bad += ["the harness is the recorded one: nothing to record"] if p["sha256"] == doc["current"]["sha256"] else []
    bad = bad or tests()
    if bad:
        raise SystemExit(f"harness change refused: {bad}")
    change = {**harness_change(doc["current"], p, anchor.strip()), "log_lines_sha256": lines_sha256(log_lines(prereg))}
    doc = {**doc, "changes": doc["changes"] + [change], "current": p}
    GC.write_json(record, doc)
    return doc


def harness_problems(*, record: Path | None = None, prereg: Path | None = None, pins=None) -> list[str]:
    record, prereg, pins = Path(record or HARNESS_RECORD), Path(prereg or PREREG), pins or harness_pins
    if not record.is_file():
        return [f"{record.name} missing: no K0 harness record"]
    doc, lines = GC.read_json(record), set(log_lines(prereg))
    out = [f"harness change {c['to'][:12]}: its anchor is not a line of the log" for c in doc["changes"]
           if c["note"] not in lines]
    if doc["current"]["sha256"] != pins()["sha256"]:
        out.append("the harness differs from its record (K0 or the last logged change)")
    return out


# ---------------------------------------------------------------- the frozen files


def rel(p: Path, root: Path) -> str:
    return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()


def card_paths(here: Path = GC.HERE, repo: Path = GC.REPO, store: Path = GC.STORE,
               gen_names: Path = GC.GEN_NAMES) -> dict[str, Path]:
    """{key: file} of the card's files: gencard/*.py and gen_names.json (the F1a group without the mech checks)."""
    out = {rel(p, repo): p for p in sorted((Path(here) / "gencard").glob("*.py"))}
    return {**out, rel(gen_names, store): Path(gen_names)}


def f1a_paths(here: Path = GC.HERE, repo: Path = GC.REPO, store: Path = GC.STORE,
              gen_names: Path = GC.GEN_NAMES) -> dict[str, Path]:
    """{key: file} of the F1a group: gencard/*.py, gen_names.json, mech_g.py and the P2 validity check mech_qg.py."""
    mech = {rel(Path(here) / n, repo): Path(here) / n for n in ("mech_g.py", "mech_qg.py")}
    return {**card_paths(here, repo, store, gen_names), **mech}


def own_paths(here: Path = GC.HERE, repo: Path = GC.REPO, store: Path = GC.STORE, cli_pin: Path = CLI_PIN) -> dict[str, Path]:
    """{key: file} of F1's own files: the prompt module and files, the banned-term module, the CLI pin."""
    own = {rel(Path(here) / n, repo): Path(here) / n for n in F1_OWN}
    return {**own, rel(cli_pin, store): Path(cli_pin)}


def frozen_paths() -> dict[str, Path]:
    """{key: file} of every non-backend file of the F1 manifest (the F1a group and F1's own files)."""
    return {**f1a_paths(), **own_paths()}


def prod_pins() -> dict[str, str]:
    """The F1 manifest's prod items now: g_common.backend_pins() and g_common.trigger_pins() (§4.3, §4.5)."""
    return {**GC.backend_pins(), **GC.trigger_pins()}


def kept_pins() -> dict[str, str]:
    """The prod items whose sha256 g_common keeps: the r4 layer (R4_LAYER_SHA256) and the trigger's files
    (TRIGGER_PINS_SHA256), the values freeze_g.prod_trigger requires of the manifest and of the files."""
    return {str(GC.R4_LAYER.relative_to(GC.STORE)): GC.R4_LAYER_SHA256, **GC.TRIGGER_PINS_SHA256}


def sha_map(paths: dict[str, Path]) -> dict[str, str | None]:
    return {k: (GC.sha256_file(p) if Path(p).is_file() else None) for k, p in paths.items()}


def manifest_problems(files: dict[str, str], current: dict[str, str | None]) -> list[str]:
    """The manifest's "files" against the frozen files now (sha256 or None; keys only in the messages)."""
    out = [f"{k} is not the F1 manifest's" for k in sorted(current) if current[k] is None or files.get(k) != current[k]]
    return out + [f"{k} is in the F1 manifest, not among the frozen files now" for k in sorted(set(files) - set(current))]


def f1a_problems(group: dict[str, str | None], f1a_doc: dict | None) -> list[str]:
    """The F1a group now against f1a_pins.json's "files" (paths only in the messages)."""
    if not isinstance(f1a_doc, dict) or not isinstance(f1a_doc.get("files"), dict):
        return ["f1a_pins.json has no files map"]
    pins = f1a_doc["files"]
    out = [f"{k}: missing" for k, v in group.items() if v is None]
    out += [f"{k}: not in f1a_pins.json" for k in sorted(set(group) - set(pins))]
    out += [f"{k}: in f1a_pins.json, not in the F1a group now" for k in sorted(set(pins) - set(group))]
    return out + [f"{k}: sha256 differs from f1a_pins.json" for k in sorted(set(group) & set(pins)) if group[k] != pins[k]]


def uncommitted(paths: list[Path], repo: Path = GC.REPO) -> list[str]:
    """Repository files that are untracked or differ from HEAD."""
    out = []
    for p in paths:
        r = rel(p, repo)
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", r], capture_output=True).returncode == 0
        same = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", r], capture_output=True).returncode == 0
        if not (tracked and same):
            out.append(r)
    return out


def build_manifest(group: dict[str, Path], own: dict[str, Path], backend: dict[str, str], f1a: Path,
                   repo: Path = GC.REPO, git: Callable[[list[Path]], list[str]] | None = None) -> dict:
    """The manifest document, or SystemExit with every reason it is refused (``backend``: the prod items, prod_pins(),
    holding every kept_pins() item at its value)."""
    g_sha, o_sha, kept = sha_map(group), sha_map(own), kept_pins()
    bad = [f"missing: {k}" for k, v in o_sha.items() if v is None]
    bad += [f"prod pin {k} is not the sha256 g_common keeps" for k in sorted(kept) if backend.get(k) != kept[k]]
    bad += f1a_problems(g_sha, GC.read_json(f1a) if Path(f1a).is_file() else None)
    clash = sorted((set(g_sha) | set(o_sha)) & set(backend) | set(g_sha) & set(o_sha))
    bad += [f"keys clash: {clash}"] if clash else []
    root = Path(repo).resolve()
    repo_files = [p for p in {**group, **own}.values() if root in Path(p).resolve().parents]
    bad += [f"not committed or changed since HEAD: {r}" for r in (git or (lambda ps: uncommitted(ps, repo)))(repo_files)]
    if bad:
        raise SystemExit(f"F1 manifest refused: {bad}")
    files = {**g_sha, **o_sha, **backend}
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return {"schema": SCHEMA, "files": files, "f1a_group": sorted(g_sha),
            "files_digest": GC.sha256_text(json.dumps(files, sort_keys=True, ensure_ascii=False)),
            "f1a_pins_sha256": GC.sha256_file(f1a), "t": now(), "git_head": head or None}


def write_manifest(out: Path = GC.F1_MANIFEST, f1a: Path = GC.F1A_LOG, group: dict[str, Path] | None = None,
                   own: dict[str, Path] | None = None, backend: dict[str, str] | None = None, repo: Path = GC.REPO,
                   git: Callable[[list[Path]], list[str]] | None = None) -> dict:
    """Write the F1 manifest once; refused when it exists or build_manifest refuses."""
    if Path(out).exists():
        raise SystemExit(f"{out} exists: the F1 manifest is written once (prereg §3.8)")
    doc = build_manifest(f1a_paths() if group is None else group, own_paths() if own is None else own,
                         prod_pins() if backend is None else backend, f1a, repo, git)
    GC.write_json(out, doc)
    return doc


def main() -> int:
    doc = write_manifest()
    print({"files": len(doc["files"]), "files_digest": doc["files_digest"],
           "f1_manifest_sha256": GC.sha256_file(GC.F1_MANIFEST)})
    return 0


if __name__ == "__main__":
    sys.exit(main())

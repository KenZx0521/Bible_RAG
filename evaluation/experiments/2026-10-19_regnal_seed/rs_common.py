"""Paths, pins and imports of the rule-seed regression (prereg.md). Host python, stdlib + this checkout.

The backend's regnal modules (backend/utils/regnal) and ragcommon are imported from this checkout and
checked to resolve here (``backend()``); experiment A's cards_common, confirm/score_c, keys_a, score_a
and analyze_c are imported unchanged. Store writes go to reports/regnal_seed_20261019/ only
(``writable``); experiment A's, A4's, the layers', contracts' and releases' directories are read only.
Nothing is ever written inside the repository (it is public), and the command line writes only under
reports/regnal_seed_20261019/ (``cli_out``). Nothing here calls Ollama, the backend or any LLM.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BACKEND, PACKAGES = REPO / "backend", REPO / "packages"
KG = REPO / "evaluation/experiments/2026-10-18_kg_cards"
A_DIR, CONFIRM_DIR = KG / "A", KG / "A/confirm"
for _p in (PACKAGES, BACKEND, A_DIR, CONFIRM_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import c_common  # noqa: E402  (inserts A_DIR's parent for cards_common)
from c_common import ac, cc  # noqa: E402,F401

STORE = cc.STORE
OUT_ROOT = STORE / "reports/regnal_seed_20261019"
READ_ONLY = (STORE / "reports/kg_cards_20261018", STORE / "reports/regnal_card_20261019",
             STORE / "layers", STORE / "contracts", STORE / "releases")
A_CONFIRM, A_DEV = c_common.OUT, ac.OUT
REGNAL_CARD = STORE / "reports/regnal_card_20261019"
# recorded gemma seeds (prereg §2): label -> file
SEED_SOURCES = {"a": A_CONFIRM / "gen_seed.jsonl",                       # G-auto's seed call, raw output
                "b": REGNAL_CARD / "a4/responses.jsonl",                 # staging A4, aux_card.seeds
                "c": REGNAL_CARD / "a4_r3b/responses.jsonl",             # staging A4 on r3b, aux_card.seeds
                "dev": A_DEV / "gen_seed.jsonl"}                         # stage-0 seed call, raw output
CONFIRM_LABELS, DEV_LABELS = ("a", "b", "c"), ("dev",)

MODEL = cc.MODEL                                   # gemma4:e4b-it-q8_0
OPTIONS = dict(c_common.OPTIONS)                   # temperature 0.1, num_predict 10000, num_ctx 131072
# A_confirm/night_run.log, /api/ps before and after the confirmation run
EXPECTED_DIGEST = "9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923"
REPS = 3
THRESHOLD, EPS = -0.05, 1e-9                       # R1, R2: Δ̄ ≥ −0.05 (the boundary passes)
ARMS = ("rule", "gemma")

PREREG = HERE / "prereg.md"
DRAFT_MARK = "草稿，待主 session 審；正式版 commit 前不准叫 Ollama"
LAYER_SHA_PLACEHOLDER = "<r4 層 sha，待主 session 填>"
LAYER_LINE = "| 王朝層（`--layer`） |"          # prereg §1: the row that must name the layer's sha256
LEXICON_LINE = "| routing lexicon（`--lexicon`） |"   # prereg §1: the row that must name the lexicon's sha256
# prereg §1's backend table: one row 「| file | sha256 |」 per BACKEND_FILES entry
HARNESS_GLOBS = ("*.py", "prereg.md")          # the harness files pinned in run_meta and verdict

BACKEND_FILES = ("backend/utils/regnal/card.py", "backend/utils/regnal/engine.py", "backend/utils/regnal/layer.py",
                 "backend/utils/regnal/seeds.py", "backend/utils/regnal/trigger.py",
                 "packages/ragcommon/regnal.py", "packages/ragcommon/routing.py")
EXPERIMENT_FILES = ("cards_common.py", "A/a_common.py", "A/keys_a.py", "A/score_a.py", "A/regnal.py",
                    "A/confirm/c_common.py", "A/confirm/score_c.py", "A/confirm/arms_c.py", "A/confirm/analyze_c.py")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path | str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p: Path | str):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path | str, obj) -> None:
    p = writable(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def jsonl(p: Path | str) -> list[dict]:
    p = Path(p)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _under(p: Path, root: Path) -> bool:
    return p == root.resolve() or root.resolve() in p.parents


@functools.lru_cache(maxsize=1)
def repo_roots() -> tuple[Path, ...]:
    """This checkout and, for a git worktree, the main checkout that holds it."""
    roots = {REPO.resolve()}
    common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True)
    if common.returncode == 0 and common.stdout.strip():
        roots.add(Path(common.stdout.strip()).resolve().parent)
    return tuple(sorted(roots))


def writable(path: Path | str) -> Path:
    """The resolved path, when writing there is allowed: never inside the repository (public: no
    question, card or answer text), in the store only under reports/regnal_seed_20261019/, and
    anywhere else (tests, scratch)."""
    p = Path(path).resolve()
    if any(_under(p, r) for r in repo_roots()):
        raise SystemExit(f"{p}: nothing is written inside the repository")
    if any(_under(p, d) for d in READ_ONLY) or (_under(p, STORE) and not _under(p, OUT_ROOT)):
        raise SystemExit(f"{p}: the store is written only under {OUT_ROOT}")
    return p


def cli_out(path: Path | str, allow_root: bool = False) -> Path:
    """A command-line output path: strictly under OUT_ROOT (OUT_ROOT itself only with allow_root)."""
    p, root = writable(path), Path(OUT_ROOT).resolve()
    if not (root in p.parents or (allow_root and p == root)):
        raise SystemExit(f"{p}: the command line writes only under {root}")
    return p


@functools.lru_cache(maxsize=1)
def backend() -> SimpleNamespace:
    """The backend's regnal modules and ragcommon's regnal and routing, from this checkout (sha recorded)."""
    mods = {n: importlib.import_module(f"utils.regnal.{n}") for n in ("card", "engine", "layer", "seeds", "trigger")}
    mods.update({n: importlib.import_module(f"ragcommon.{n}") for n in ("regnal", "routing")})
    for n, m in mods.items():
        root = PACKAGES if n in ("regnal", "routing") else BACKEND
        if not _under(Path(m.__file__).resolve(), root):
            raise SystemExit(f"{n} resolved to {m.__file__}, not this checkout's {root.name}/")
    files = {f: sha256_file(REPO / f) for f in BACKEND_FILES}
    return SimpleNamespace(**mods, files_sha256=files, sha256=sha256_text(json.dumps(files, sort_keys=True)))


def experiment_files_sha256() -> dict:
    return {f: sha256_file(KG / f) for f in EXPERIMENT_FILES}


def load_layer(layer_path: Path | str, lexicon_path: Path | str):
    """(the layer with the routing lexicon attached, as the backend serves it; its pins)."""
    B = backend()
    layer = B.layer.with_lexicon(B.layer.parse_layer(Path(layer_path).read_bytes()),
                                 B.routing.load_lexicon(lexicon_path))
    info = {"layer_path": str(Path(layer_path).resolve()), "layer_sha256": layer.sha256,
            "lexicon_path": str(Path(lexicon_path).resolve()), "lexicon_sha256": sha256_file(lexicon_path),
            "blockers": len(layer.blockers)}
    return layer, info


@functools.lru_cache(maxsize=1)
def ref_view():
    """Experiment A's reference layer (the scorers' names and traps), unchanged."""
    from regnal import load_ref
    return load_ref(c_common.LAYER_REF)


def frozen_problems() -> list[str]:
    """Experiment A's frozen files and prompts that differ from confirm_A.md §0 (empty = all match)."""
    return c_common.frozen_mismatches()


def prereg_problems(text: str, layer_sha: str, *, lexicon_sha: str, backend_files: dict[str, str]) -> list[str]:
    """Why prereg.md is not yet the formal version for this run: the draft mark, the placeholder, §1's
    layer row (LAYER_LINE) or lexicon row (LEXICON_LINE) not naming the run's sha256, or a row of §1's
    backend table (「| file | sha256 |」) not naming the sha256 of that file of this checkout."""
    out = []
    lines = text.splitlines()
    if DRAFT_MARK in text:
        out.append("draft")
    if LAYER_SHA_PLACEHOLDER in text:
        out.append("placeholder")
    if not any(line.startswith(LAYER_LINE) and layer_sha in line for line in lines):
        out.append("layer sha")
    if not any(line.startswith(LEXICON_LINE) and lexicon_sha in line for line in lines):
        out.append("lexicon sha")
    for f, sha in backend_files.items():
        if not any(line.startswith(f"| {f} |") and sha in line for line in lines):
            out.append(f"backend sha {f}")
    return out


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def prereg_git_problems(path: Path | None = None, harness_dir: Path | None = None) -> list[str]:
    """prereg.md must be committed and unchanged since, and so must every file of the harness directory
    (no edit, no untracked file): no Ollama call before the formal version, and the code that runs is
    the committed code."""
    path = Path(path or PREREG).resolve()
    harness_dir = Path(harness_dir or HERE).resolve()
    out = []
    if _git(path.parent, "ls-files", "--error-unmatch", path.name).returncode != 0:
        out.append("prereg.md not committed")
    elif _git(path.parent, "diff", "--quiet", "HEAD", "--", path.name).returncode != 0:
        out.append("prereg.md changed since the last commit")
    status = _git(harness_dir, "status", "--porcelain", "--untracked-files=all", "--", ".")
    if status.returncode != 0 or status.stdout.strip():
        out.append("harness files changed or untracked since the last commit")
    return out


def harness_files_sha256(harness_dir: Path | None = None) -> dict[str, str]:
    d = Path(harness_dir or HERE)
    return {p.name: sha256_file(p) for g in HARNESS_GLOBS for p in sorted(d.glob(g)) if p.is_file()}


def harness_pins(harness_dir: Path | None = None) -> dict:
    """The harness's own version: git HEAD, whether its directory differs from HEAD, its files' sha256."""
    d = Path(harness_dir or HERE)
    head = _git(d, "rev-parse", "HEAD")
    status = _git(d, "status", "--porcelain", "--untracked-files=all", "--", ".")
    files = harness_files_sha256(d)
    return {"git_head": head.stdout.strip() if head.returncode == 0 else None,
            "dirty": status.returncode != 0 or bool(status.stdout.strip()), "files_sha256": files,
            "sha256": sha256_text(json.dumps(files, sort_keys=True))}

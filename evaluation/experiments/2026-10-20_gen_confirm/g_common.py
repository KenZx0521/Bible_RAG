"""Paths, pins and the store-write guard of the GEN confirmation set (prereg.md). Host python, stdlib only.

This module never imports experiment A's ``c_common`` or stage-0's ``x_common``; modules that need
stage-0's frozen code import it read-only through ``stage0()``. Store writes go to
reports/gen_confirm_20261020/ only (``writable``); nothing is ever written inside the repository (it is
public: no question, card, answer or scripture text), and the frozen stores of experiment A and stage-0
are refused by name. Nothing here calls Ollama or any LLM.
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
STAGE0_DIR = REPO / "evaluation/experiments/2026-10-20_arith_stage0"
STORE = Path("/mnt/ollama-data/bible_rag_store")
OUT_ROOT = STORE / "reports/gen_confirm_20261020"
STAGE0_OUT = STORE / "reports/arith_stage0_20261020"
READ_ONLY = (STORE / "reports/kg_cards_20261018", STAGE0_OUT, STORE / "reports/regnal_fix_20261019",
             STORE / "reports/regnal_qset_20261019", STORE / "reports/kg_niche_20261018",
             STORE / "layers", STORE / "contracts", STORE / "releases")

# prereg §2: stage-0's frozen Genesis layer and the text layer it was read from
GEN_LAYER = STAGE0_OUT / "gen_layer.json"
GEN_LAYER_SHA256_PREFIX = "46d87abb2900"
POOL = OUT_ROOT / "pool.json"
GEN_NAMES = OUT_ROOT / "gen_names.json"
F1A_LOG = OUT_ROOT / "f1a_pins.json"
F1_MANIFEST = OUT_ROOT / "f1_manifest.json"
ORDER = OUT_ROOT / "order.json"
QUESTIONS_FROZEN = OUT_ROOT / "questions_frozen.json"
POOL_SHA256 = "3426c5929d827b9e0cdeef8973263f1fffe838841afc2d631097d8b1aaa06604"
HO_ROOT = OUT_ROOT / "ho"                            # blind writing (prereg §3)
QSET_ROOT = OUT_ROOT / "qset"                        # P1/P2 (prereg §5.4)

# prereg §4.3, §4.5: prod files whose content defines prompt parity and the dynasty-trigger deletion rule
BACKEND_PIN_FILES = ("backend/utils/generator.py", "backend/utils/regnal/trigger.py",
                     "backend/utils/regnal/layer.py", "backend/utils/regnal/card.py", "packages/ragcommon/regnal.py")
R4_LAYER = STORE / "contracts/b20261019_a86f2b06/regnal_layer.json"
R4_LAYER_SHA256 = "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"

# prereg §1, §7
MODEL = "gemma4:e4b-it-q8_0"
EXPECTED_DIGEST = "9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923"
OLLAMA_VERSION = "0.32.5"
METRIC_VERSION = "4d0826bb8d14"
TEST_SEED = 20261018                                 # ab_stats.sign_flip_p / bootstrap_ci, as A
POWER_SEED = 20261018
P2_SEED = 20261022                                   # P2 positives: sample of 50 pool slots, no replacement
KAY_SAMPLE_SEED = 20261021                           # Kay's page: 10 passed questions

# prereg §3, §5.4, §8: money and attempts
USD_CAP = 50.0
START_MARGIN_USD = 1.0                               # a job starts only if spent + its cap <= USD_CAP - margin
JOB_CAP_USD = {"draft": 2.0, "fix": 1.5, "audit": 1.0}
PROBE_CAP_USD = 1.0                                  # CLI probe
PROBE_MAX_RUNS = 2
QSET_CAP_USD = 3.0                                   # P1 + P2
QSET_JOB_CAP_USD = {"gen": 0.2, "label": 0.2}        # per qset job, as the regnal qset
KP_BUDGET_USD = 47.0                                 # K-P: longest order prefix projected at or under this
MAX_ATTEMPTS = 3                                     # per slot, never switching type
FIX_SOURCES = ("mech", "audit", "kay")               # one fix round per source per attempt, as A
MAX_FIX_ROUNDS = 1                                   # per source
KAY_QUESTIONS = 10                                   # Kay's page sample; K-Kay stops at >= 3 drops
MAX_INFRA_RETRIES = 2                                # per job; not counted as attempts
PARALLEL = 4
PILOT = 12


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path | str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p: Path | str):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def backend_pins() -> dict:
    """sha256 of the prod files and the r4 layer that §4.3's parity test and deletion rule depend on."""
    out = {f: sha256_file(REPO / f) for f in BACKEND_PIN_FILES}
    out[str(R4_LAYER.relative_to(STORE))] = sha256_file(R4_LAYER)
    return out


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
    """The resolved path, when writing there is allowed: never inside the repository, never in a frozen
    store folder, in the store only under reports/gen_confirm_20261020/, and anywhere else (tests, scratch)."""
    p = Path(path).resolve()
    if any(_under(p, r) for r in repo_roots()):
        raise SystemExit(f"{p}: nothing is written inside the repository")
    if any(_under(p, d) for d in READ_ONLY) or (_under(p, STORE) and not _under(p, OUT_ROOT)):
        raise SystemExit(f"{p}: the store is written only under {OUT_ROOT}")
    return p


def write_json(p: Path | str, obj) -> Path:
    p = writable(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


@functools.lru_cache(maxsize=1)
def stage0() -> SimpleNamespace:
    """Stage-0's frozen Genesis modules, imported read-only from their own folder (never copied or edited)."""
    if str(STAGE0_DIR) not in sys.path:
        sys.path.insert(0, str(STAGE0_DIR))
    mods = {m: importlib.import_module(m) for m in ("x_common", "gen_layer", "items_x", "engine_x", "keys_x")}
    for name, m in mods.items():
        if Path(m.__file__).resolve().parent != STAGE0_DIR.resolve():
            raise SystemExit(f"{name} resolved to {m.__file__}, not stage-0's folder")
    return SimpleNamespace(**mods)

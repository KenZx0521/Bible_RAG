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


# ================================================================ batch 3: appended after F0 (integration)
# prereg §3.9: every amount, attempt / rerun count, stop threshold, path and store root, sub-root or file name of
# the GEN modules is defined here once; a module reads GC.<name> (a module-level alias is the same object). The F0
# names above and their values never change; this block only adds names.

# repository files and folders
PREREG = HERE / "prereg.md"
TESTS_DIR = REPO / "evaluation/tests"
EVAL_DIR = REPO / "evaluation"
GENCARD_DIR = HERE / "gencard"
GEN_PROMPT = HERE / "gen_g.md"                       # the writer and fixer prompts (prompts_g)
AUDIT_PROMPT = HERE / "audit_g.md"                   # the value-blind auditor prompts (prompts_g)
QSET_PROMPT = HERE / "prompts_qg.md"                 # the P1/P2 writer prompts (prompt_qg)
GT_FILES = (REPO / "ground_truth.json", REPO / "ground_truth.v2.json")      # §5.6's GT nail
HO_TOOLS_DIR = REPO / "evaluation/experiments/2026-10-14_graph_gd/ho_tools"
BT_GUARD = HO_TOOLS_DIR / "bt_guard.py"              # HO's original hook, run or loaded by path (sha pinned)
HO_BANNED = HO_TOOLS_DIR / "banned.py"               # HO's word lists, loaded by path (sha pinned)
A_BANNED = REPO / "evaluation/experiments/2026-10-18_kg_cards/A/confirm/ho_a/banned_a.py"   # read as literals

# outside the repository and the out root
AGENT_CWD = Path("/srv")                             # every agent's cwd: empty, outside and not above the repo
CLI_VERSIONS_DIR = Path.home() / ".local/share/claude/versions"           # the CLI's own install (probe copies it)
TEXT_LAYER = STORE / "layers/text/text@247eafe44b02"  # bt_g keeps its own copy: it imports nothing of this folder
ROUTING_LEXICON = R4_LAYER.with_name("routing_lexicon.json")              # the r4 contract's lexicon
STAGE0_RUN_META = STAGE0_OUT / "formal/run_meta.json"  # stage-0's formal run (its harness, §4.5)

# §4.3, §4.5: prod's dynasty trigger (F2 step 3) loads these besides backend_pins()'s trigger.py, layer.py and
# ragcommon/regnal.py; trigger_pins() keys them as backend_pins() does, TRIGGER_PINS_SHA256 keeps their sha256
PROD_TRIGGER_FILES = ("backend/utils/regnal/trigger.py", "backend/utils/regnal/layer.py",
                      "packages/ragcommon/regnal.py")
TRIGGER_PIN_FILES = ("packages/ragcommon/__init__.py", "packages/ragcommon/routing.py", "packages/ragcommon/books.py",
                     "packages/ragcommon/ids.py", "packages/ragcommon/data/books.json")
TRIGGER_PINS_SHA256 = {
    "packages/ragcommon/__init__.py": "6282eea8e619210ce1792b5b23156f7300e20d671e2d517ca3dfe8c964d1e973",
    "packages/ragcommon/routing.py": "dfffe5f424c8643aa7bd7f7851534bf25e3d91b9c52e5eaa5cc331b2a4d95490",
    "packages/ragcommon/books.py": "e153e8098007897f8efafdf1b0a7e0daf3a6d0c6678bbe37d24654cb8b85b7c2",
    "packages/ragcommon/ids.py": "64d90cd5a7cc05c0b4ab377d84bd5c98da95624ab71e77ffc8b1af9915e38dd7",
    "packages/ragcommon/data/books.json": "e553f0880622e83d81ff5d97656e9393670fd23975c0e6d1d47adf00c333a3bc",
    str(ROUTING_LEXICON.relative_to(STORE)): "2a172575e3d474ee22c099fcc99fda9f11eeaeba14aa69cde8bf53d9e65b991e"}
OLLAMA_OPTIONS = {"temperature": 0.1, "num_predict": 10000, "num_ctx": 131072}    # §4.3 (stage-0's OPTIONS)

# the store under OUT_ROOT
PROBE_ROOT = OUT_ROOT / "probe"                      # one sub-root <n>/ per CLI probe invocation
CLI_DIR = OUT_ROOT / "cli"                           # the pinned CLI copies (§3.1: versions/ gets cleaned)
CLI_PIN = OUT_ROOT / "cli_pin.json"                  # the one pin file of HO and qset
HARNESS_RECORD = OUT_ROOT / "harness_record.json"    # K0's harness record and its logged changes (§4.5)
K0_FILE = OUT_ROOT / "k0.json"                       # the K0 result (§3.9, §8.1-1)
K0_ATTEMPTS = OUT_ROOT / "k0_attempts"              # the failed K0 attempts, one file each (k0_g)
F2_FILE = OUT_ROOT / "f2.json"                       # F2 steps 5–7
VOID_FILE = OUT_ROOT / "void.json"                   # the one void record (prompt parity, a truncated smoke)
RUN_ROOT = OUT_ROOT / "run"                          # the Ollama runs (run_g)
LEDGER_LOCK, LEDGER_SNAPSHOT = "ledger.lock", "ledger.json"                    # in OUT_ROOT (ledger_g)
HO_SUB_ROOTS = ("pilot", "main", "kay")              # run sub-roots of HO_ROOT
HO_STATE, HO_LOCK, KP_FILE, KAY_FILE, REPINS_FILE = "state.json", "state.lock", "kp.json", "kay.json", "repins.json"
FREEZE_FILE, K_GOLD_FILE = "freeze.json", "k_gold.json"                       # in HO_ROOT
KAY_PAGE, KAY_SAMPLE = "kay_page.html", "kay_sample.json"                     # in HO_ROOT/kay
QSET_SETS = ("p1", "p2")                             # set roots of QSET_ROOT
QSET_SPEC, QSET_DRAFTS, QSET_LOCK, QSET_ITEMS = "spec.json", "drafts", "run.lock", "items.json"   # in a set root
QSET_GEN_DONE, QSET_REFILL_DONE, QSET_SCORE_DONE = "gen_done.json", "refill_done.json", "score.json"  # P2's records
P1_SCORES, P1_ROWS = "scores.jsonl", "score_rows.json"                         # in QSET_ROOT/p1
G1_FILE, P2_NEAR_FILE = "g1.json", "p2_near_miss.json"                        # P2's results, in QSET_ROOT
G1_RESULT, P2_NEAR_MISS = QSET_ROOT / G1_FILE, QSET_ROOT / P2_NEAR_FILE
RUN_KINDS = ("dry_run", "smoke", "formal")           # run directories of RUN_ROOT
RUN_ITEMS, RUN_CARDS, RUN_JOBS, RUN_ARMS_META = "items.json", "cards.json", "jobs.json", "arms_meta.json"
RUN_DATA_FILES = (RUN_ITEMS, RUN_CARDS, RUN_JOBS, RUN_ARMS_META)              # the F3 build, in RUN_ROOT
RUN_F3, RUN_META, RUN_GEN, RUN_TORN, RUN_LOCK = "f3.json", "run_meta.json", "gen_arms.jsonl", "gen_arms.torn.jsonl", \
    "run.lock"
RUN_SMOKE, RUN_CANARY, SMOKE_HISTORY, SMOKE_SET_ASIDE = "smoke.json", "canary.json", "smoke_history.json", \
    "smoke_set_aside"
RUN_SCORES, RUN_REPORT, RUN_REPORT_MD, DRY_RUN_REPORT = "scores.json", "report.json", "report.md", "dry_run_report.json"

# amounts, counts and stop thresholds
SPEND_LIMIT_USD = USD_CAP - START_MARGIN_USD         # 49: spent + a job's cap must fit (§3.9)
KIND_JOB_CAP_USD = {"probe": PROBE_CAP_USD, "qset": max(QSET_JOB_CAP_USD.values()), "ho": max(JOB_CAP_USD.values())}
PROBE_REPS_BT = 3                                    # mode-bt runs of one probe invocation
PROBE_RUN_CAP_USD = {"bt": 0.12, "none_opus": 0.06, "none_sonnet": 0.04}    # per probe run (probe_g's docstring)
PROBE_INVOCATION_CAP_USD = round(PROBE_REPS_BT * PROBE_RUN_CAP_USD["bt"] + PROBE_RUN_CAP_USD["none_opus"]
                                 + PROBE_RUN_CAP_USD["none_sonnet"], 6)     # 0.46: two fit in PROBE_CAP_USD
P2_RESERVE_USD = 1.5                                 # of QSET_CAP_USD, kept free for P2 while P1 runs
P1_LIMIT_USD = QSET_CAP_USD - P2_RESERVE_USD
CLI_VERSION_TRIES = 2                                # `claude --version` tries before CliUnavailable
UNAVAILABLE_WAVES = 3                                # HO waves in a row in which every job met CliUnavailable: stop
K_KAY_STOP = 3                                       # §3.7: K-Kay stops at ≥ 3 drops among KAY_QUESTIONS
N_POS, N_NEAR, N_DEV, QSET_JOB_SIZE = 50, 20, 14, 3  # §5.4: positives and near misses per set, dev slots, job size
G1_N = 53                                            # §5.6: G1's n = power_g.N_PLAN (58 slots × A's 32/35)
SMOKE_PER_ARM, CANARY_CALLS = 2, 30                  # §4.4: smoke prompts per arm; the canary's first calls
TRUNC_ARM_MAX, TRUNC_GAP_MAX = 2, 2                  # §4.5 void: an arm truncated ≥ 2 times; G and T-rows ≥ 2 apart


def trigger_pins() -> dict:
    """sha256 now of the files prod's dynasty trigger loads besides backend_pins(): ragcommon's __init__, routing,
    books, ids and data/books.json, and the r4 contract's routing lexicon (keyed as backend_pins() keys its items)."""
    out = {f: sha256_file(REPO / f) for f in TRIGGER_PIN_FILES}
    out[str(ROUTING_LEXICON.relative_to(STORE))] = sha256_file(ROUTING_LEXICON)
    return out

"""Paths, pins and imports of the ordered-chain arithmetic stage-0 (prereg.md). Host python, stdlib + this checkout.

Experiment A's cards_common, a_common, keys_a, score_a, tcanon, confirm/c_common and confirm/arms_c are
imported unchanged (their sha256 values are confirm_A.md §0's pins, checked by ``frozen_problems``). The
dynasty rows come from the r4 layer read the prod way (``ragcommon.regnal.load``, the backend engine's
``row_text``); the dynasty gold from the hand reference layer v2. Store writes go to
reports/arith_stage0_20261020/ only (``writable``); nothing is ever written inside the repository (it is
public: no question, card, answer or scripture text), and the command line writes only under that
directory (``cli_out``). Nothing here calls Ollama or any LLM.
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

import c_common  # noqa: E402  (puts A's parent on sys.path for cards_common)
from c_common import ac, cc  # noqa: E402,F401

STORE = cc.STORE
OUT_ROOT = STORE / "reports/arith_stage0_20261020"
READ_ONLY = (STORE / "reports/kg_cards_20261018", STORE / "reports/regnal_fix_20261019",
             STORE / "reports/kg_niche_20261018", STORE / "layers", STORE / "contracts", STORE / "releases")

# prereg §2: the dynasty gold (hand reference v2) and rows (r4, as prod reads it); the text layer
REF_V2 = STORE / "reports/regnal_fix_20261019/ref_layer_v2.json"
REF_V2_SHA256 = "e39e04f227f1b558300dd85662d7dbdaf76e73252ddf732ef1f6aab96cec576a"
R4_LAYER = STORE / "contracts/b20261019_a86f2b06/regnal_layer.json"
R4_LAYER_SHA256 = "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"
TEXT = STORE / "layers/text/text@247eafe44b02"
TEXT_DIGEST = "247eafe44b02ed27f49d244ba525d02b87bd7c8402ca03ce38cb97972a12e75a"
GEN_LAYER = OUT_ROOT / "gen_layer.json"
ITEMS = OUT_ROOT / "items.json"
# prereg §7-5: the power simulation, copied into power_x.py (this is the source it was copied from)
POWER_SRC = STORE / "reports/kg_niche_20261018/kgniche/synth/powerA_strong.py"
POWER_SRC_SHA256 = "78d67cb84da4be052329113f97ca91c1d97af4521d88afaac9496ebe1b03d500"

# prereg §1
MODEL = cc.MODEL                                    # gemma4:e4b-it-q8_0
OPTIONS = dict(c_common.OPTIONS)                    # temperature 0.1, num_predict 10000, num_ctx 131072
EXPECTED_DIGEST = "9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923"
SEED = 20261020
REPS = 3
CAP_CHARS = 900

# prereg §3: families, question types and arms (§4)
JUDGED = ("DYN", "GEN")                             # families with a K-S0 verdict
DESCRIBED = ("S6", "SYNC")                          # described only
QTYPES = {"DYN": ("S5",), "S6": ("S6",), "SYNC": ("SYNC2", "SYNC3"), "GEN": ("F1", "F3", "F5")}
ARMS = {"DYN": ("G", "T-rows", "T-canon", "B0"), "S6": ("G", "T-rows", "T-canon", "B0"),
        "SYNC": ("G", "T-rows", "T-canon", "B0"), "GEN": ("G", "T-rows", "B0")}
B0_BARE = "B0p"                                     # prereg §4 B0′: no block, no passages (GEN, 1 rep)
REPS_BY_ARM = {"G": REPS, "T-rows": REPS, "T-canon": REPS, "B0": REPS, B0_BARE: 1}

PREREG = HERE / "prereg.md"
DRAFT_MARK = "草稿，待主 session 審"
LOG_HEADING = "\n## 執行紀錄"                       # prereg.md's append-only log: not pinned (harness_files_sha256)
HARNESS_GLOBS = ("*.py", "prereg.md", "appendix.md")
TESTS_DIR, TESTS_GLOB = REPO / "evaluation/tests", "test_arith_stage0_*.py"   # pinned as tests/<name>

BACKEND_FILES = ("backend/utils/regnal/engine.py", "packages/ragcommon/regnal.py")
EXPERIMENT_FILES = ("cards_common.py", "A/a_common.py", "A/keys_a.py", "A/score_a.py", "A/tcanon.py",
                    "A/regnal.py", "A/confirm/c_common.py", "A/confirm/arms_c.py")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path | str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p: Path | str):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path | str, obj) -> Path:
    p = writable(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


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
    """The resolved path, when writing there is allowed: never inside the repository, in the store only
    under reports/arith_stage0_20261020/, and anywhere else (tests, scratch)."""
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
    """ragcommon.regnal (the prod reader) and the backend engine (its ``row_text``), from this checkout."""
    reg = importlib.import_module("ragcommon.regnal")
    eng = importlib.import_module("utils.regnal.engine")
    for m, root in ((reg, PACKAGES), (eng, BACKEND)):
        if not _under(Path(m.__file__).resolve(), root):
            raise SystemExit(f"{m.__name__} resolved to {m.__file__}, not this checkout's {root.name}/")
    files = {f: sha256_file(REPO / f) for f in BACKEND_FILES}
    return SimpleNamespace(regnal=reg, engine=eng, files_sha256=files,
                           sha256=sha256_text(json.dumps(files, sort_keys=True)))


def check_pins() -> list[str]:
    """Input files whose sha256 is not prereg §2's (empty = all match)."""
    out = []
    for path, want in ((REF_V2, REF_V2_SHA256), (R4_LAYER, R4_LAYER_SHA256), (POWER_SRC, POWER_SRC_SHA256)):
        if not path.is_file():
            out.append(f"missing {path}")
        elif sha256_file(path) != want:
            out.append(f"{path.name}: sha256 {sha256_file(path)[:12]} is not {want[:12]}")
    manifest = TEXT / "layer_manifest.json"
    if not manifest.is_file() or read_json(manifest).get("digest") != TEXT_DIGEST:
        out.append(f"text layer digest is not {TEXT_DIGEST[:12]}")
    return out


@functools.lru_cache(maxsize=1)
def r4_view():
    """The r4 layer as prod reads it (ragcommon.regnal.load)."""
    return backend().regnal.load(read_json(R4_LAYER))


@functools.lru_cache(maxsize=1)
def ref_v2_view():
    """The hand reference layer v2 through experiment A's reader (the dynasty gold, keys and traps)."""
    from regnal import load_ref
    return load_ref(REF_V2)


def frozen_problems() -> list[str]:
    """Experiment A's frozen files and prompts that differ from confirm_A.md §0 (empty = all match)."""
    return c_common.frozen_mismatches()


def experiment_files_sha256() -> dict:
    return {f: sha256_file(KG / f) for f in EXPERIMENT_FILES}


def prereg_pinned_text(text: str) -> str:
    """prereg.md above its 「## 執行紀錄」 heading (the log below it is append-only and never pinned)."""
    return text.split(LOG_HEADING, 1)[0]


def prereg_log_text(text: str) -> str:
    """prereg.md's 「## 執行紀錄」 section (empty when there is none)."""
    return text.split(LOG_HEADING, 1)[1] if LOG_HEADING in text else ""


def harness_files_sha256(here: Path = HERE, tests_dir: Path = TESTS_DIR) -> dict:
    """sha256 of every harness file (prereg.md: its text above the log only) and, as tests/<name>, of
    every test file of this experiment."""
    def sha(p: Path) -> str:
        return sha256_text(prereg_pinned_text(p.read_text(encoding="utf-8"))) if p.name == PREREG.name else sha256_file(p)
    out = {p.name: sha(p) for g in HARNESS_GLOBS for p in sorted(Path(here).glob(g)) if p.is_file()}
    out.update({f"tests/{p.name}": sha256_file(p) for p in sorted(Path(tests_dir).glob(TESTS_GLOB)) if p.is_file()})
    return out

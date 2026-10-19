"""Paths, constants and pins of the question set for the chronology card's trigger recall (qset.md).

The question set measures how often the card's trigger (``backend/utils/regnal/trigger.py``) takes
dynasty-chronology questions as real readers would phrase them. Writers only phrase: every gold is
computed here from the reference layer, so no writer looks scripture up and nobody audits answers.

* Store root ROOT = reports/regnal_qset_20261019/ is the only place these tools write (spec, writer and
  labeller transcripts, ledger, items, scores). Question text never goes into the repo.
* The reference layer is read from reports/regnal_fix_20261019/ref_layer_v2.json (written by the layer
  fix). Before that file exists it is derived in memory from experiment A's frozen ref_layer.json
  (79d57efe…, sha checked, never written): 所羅門 (J00) dropped, 羅波安 (J01) made the Judah founder;
  the derivation's bytes (json indent=1) must hash to REF_V2_DERIVED_SHA256.
* The backend's regnal modules are imported from this checkout (``regnal()``), never copied.

Nothing here launches an agent, calls Ollama or touches a container. Host python3 -B or the
evaluation venv; stdlib only.
"""
from __future__ import annotations

import functools
import hashlib
import importlib
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BACKEND, PACKAGES = REPO / "backend", REPO / "packages"

# ---------------------------------------------------------------- store paths
STORE = Path("/mnt/ollama-data/bible_rag_store")
ROOT = STORE / "reports" / "regnal_qset_20261019"
REF_V2 = STORE / "reports" / "regnal_fix_20261019" / "ref_layer_v2.json"
REF_A = STORE / "reports" / "kg_cards_20261018" / "A" / "ref_layer.json"
REF_A_SHA256 = "79d57efe451f675b6d2c1163d801b2a173a24a1a8b1ed0ba6a207f698ca16660"
REF_V2_DERIVED_SHA256 = "e39e04f227f1b558300dd85662d7dbdaf76e73252ddf732ef1f6aab96cec576a"
LAYER_PROD = STORE / "contracts" / "b20261019_18aa84ad" / "regnal_layer.json"   # 932d2242…, before the fix
LAYER_PRE_FIX_SHA256 = "932d2242dc3fdce8830112484c81bc0ea5364cc4caaf6978b12f8984790ee9ab"   # describe only
# the r4 layer every formal score uses (qset.md §5, §12-5), pinned with the formal prereg; while None
# P2 is not scored and P1 takes any layer but the pre-fix one (score_q.score_layer_check). Pinned
# 2026-10-19: relations@ee8e78c043d2, in release b20261019_a86f2b06 (contracts/…/regnal_layer.json)
SCORE_LAYER_SHA256: str | None = "252e09559cb0041155b3e64b895b8284ace59450eb3b9becf1b649aba395cd11"
LEXICON_FILE = "routing_lexicon.json"   # the build's routing lexicon, next to its regnal_layer.json
DEV_ITEMS = STORE / "reports" / "kg_cards_20261018" / "A" / "items.json"         # 30 dev questions (in-sample)
CONFIRM_FROZEN = STORE / "reports" / "kg_cards_20261018" / "A_confirm" / "questions_frozen.json"  # 32 (in-sample)
GT_FILES = (REPO / "ground_truth.json", REPO / "ground_truth.v2.json")
PROMPTS_MD = HERE / "prompts_q.md"

# ---------------------------------------------------------------- design (qset.md §1, §2)
SEED = 20261019
KINGDOMS = ("I", "J")
KNAME = {"I": "以色列", "J": "猶大"}
KD = {"以色列": "I", "猶大": "J"}
SETS = ("p1", "p2")
POS_TYPES = ("S1a", "S1b", "S1c", "S4")
NEAR_FAMILIES = ("N1", "N2", "N3", "N4", "N5")
FLAGS = ("f_start_unnamed", "f_between", "f_father_is_answer")   # mech_q: recorded, never dropped
INTENT = {"S1a": "offset", "S1b": "handovers", "S1c": "usurper_n", "S4": "on_throne_at_birth",
          "N1": "attribute", "N2": "event", "N3": "sync", "N4": "contemporary", "N5": "kin"}
POS_INTENTS = frozenset(INTENT[t] for t in POS_TYPES)
QUOTA = {"p1": {"S1a": 28, "S1b": 12, "S1c": 10, "S4": 10, "N1": 4, "N2": 4, "N3": 3, "N4": 2, "N5": 2},
         "p2": {"S1a": 24, "S1b": 10, "S1c": 8, "S4": 8, "N1": 3, "N2": 3, "N3": 3, "N4": 2, "N5": 2}}
PERSONAS = ("sunday_school", "casual", "seminary", "search_box", "reading")
WRITERS = ("opus", "sonnet")        # half the jobs each; the probe resolves and pins the model ids
LABELLER = "opus"
LABEL_BATCH = 10

# ---------------------------------------------------------------- budget (qset.md §9, ≤10 USD)
# probe 2026-10-19 (3-slot writer job, measured): opus 0.0251, sonnet 0.0146 USD; the gen cap is ~8x opus
USD_CAP = 10.0
JOB_CAP_USD = {"gen": 0.2, "label": 0.2, "probe": 0.3}
PROBE_MAX_RUNS, PROBE_TOTAL_USD = 2, 0.6
PARALLEL = 4
MAX_RETRIES = 2                     # infrastructure failures only (no result, timeout, model fallback)

# ---------------------------------------------------------------- CLI pin (qset.md §8)
CLAUDE_VERSION = "2.1.302"
CLI_VERSIONS_DIR = Path.home() / ".local" / "share" / "claude" / "versions"
CLI_SHA256 = {"2.1.302": "60d7eb7f12fbb28a52533fe8be5884097403562aa02dc73991a021c7067e29a5"}
MODEL_IDS = {"opus": "claude-opus-5-5"}   # the other writers' ids come from the probe (cli_pin.json)
EFFORT = {"gen": "xhigh", "label": "high", "probe": "xhigh"}
BT_GUARD_HO_SHA256 = "a81cba6e153bdb39b8c1a3f10cb1ccccf7ac66dd2b46db587b713a45fd1835ab"
PIN_FILE = "cli_pin.json"

WRITE_LOCK = threading.Lock()


class QError(Exception):
    """A question-set tool refused its input (bad spec, missing pin, banned word, write outside root, …)."""


class BudgetRefused(QError):
    """spent + this job's cap would exceed USD_CAP (or the probe allowance); nothing was started."""


@dataclass(frozen=True)
class Violation:
    """One failed rule; level 'error' voids the run or the item, 'warn' is only recorded."""
    rule: str
    detail: str
    level: str = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical(obj: Any) -> bytes:
    """The reference layer's serialisation (json indent=1, no trailing newline): its sha is the pin."""
    return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")


def under(path: Path | str, root: Path | str) -> bool:
    p, r = Path(path).resolve(), Path(root).resolve()
    return p == r or r in p.parents


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, obj: Any, root: Path | str) -> Path:
    """Atomic JSON write (temp file + rename), refused outside ``root``."""
    path = Path(path)
    if not under(path, root):
        raise QError(f"refusing to write {path} outside {root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def append_jsonl(path: Path | str, row: Any, root: Path | str) -> Path:
    path = Path(path)
    if not under(path, root):
        raise QError(f"refusing to write {path} outside {root}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with WRITE_LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_jsonl(path: Path | str) -> list[Any]:
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_evenly(total: int, parts: int) -> list[int]:
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


@functools.lru_cache(maxsize=1)
def regnal() -> SimpleNamespace:
    """The backend's trigger, layer, engine and seeds modules and ragcommon's regnal and routing from this
    checkout (sha recorded).

    ``seeds.rule_seeds`` and ``layer.with_lexicon`` are optional (the rule-seed change lands separately);
    callers treat their absence as n/a and as a layer without blockers."""
    for p in (str(PACKAGES), str(BACKEND)):
        if p not in sys.path:
            sys.path.insert(0, p)
    mods = {n: importlib.import_module(f"utils.regnal.{n}") for n in ("trigger", "layer", "engine", "seeds")}
    files = {}
    for n, m in mods.items():
        path = Path(m.__file__).resolve()
        if not under(path, BACKEND):
            raise QError(f"utils.regnal.{n} resolved to {path}, not this checkout's backend")
        files[f"{n}.py"] = sha256_file(path)
    common = {n: importlib.import_module(f"ragcommon.{n}") for n in ("regnal", "routing")}
    for n, m in common.items():
        if not under(m.__file__, PACKAGES):
            raise QError(f"ragcommon.{n} resolved to {m.__file__}, not this checkout's packages")
        files[f"ragcommon/{n}.py"] = sha256_file(m.__file__)
    return SimpleNamespace(**mods, ragcommon=common["regnal"], routing=common["routing"], files_sha256=files)


def counts(values: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items()))

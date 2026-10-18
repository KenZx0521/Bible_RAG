"""Shared paths, errors and file pins of the blind question-writing tools (confirm_A.md §2, §7, §8).

Importing this module puts ho_a/ and confirm/ on sys.path, so every ho_a script reaches c_common
(and through it the stage-0 A/ modules) from here. The run root is ROOT = store
reports/kg_cards_20261018/A_confirm/ho/; every tool also takes another root (tests use tmp dirs).
Outputs beside the root (questions_frozen.json, k1.json, k_u2.json) live in root.parent, which is
OUT for the store root. Host python3 -B, stdlib only. Nothing here launches an agent.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

HO_A = Path(__file__).resolve().parent
CONFIRM = HO_A.parent
for _p in (str(HO_A), str(CONFIRM)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import c_common as C  # noqa: E402

ROOT = C.HO
REPO_ROOT = CONFIRM.parents[4]                      # .../Bible_RAG
GEN_PROMPT = HO_A / "gen_a.md"
AUDIT_PROMPT = HO_A / "audit_a.md"
PIN_FILE = "cli_pin.json"                            # written by probe_cli.py pin (main program)
PASSED_FILE = "questions_passed.json"                # k1.py / support.py read it (c_common.QUESTIONS_PASSED)
TOOL_FILES = ("hoa_common.py", "bt_a.py", "bt_guard.py", "banned_a.py", "transcript_a.py", "claude_a.py",
              "prompts_a.py", "state_a.py", "mech_a.py", "runs_a.py", "run_ho_a.py", "kay_a.py", "freeze_a.py",
              "probe_cli.py", "gen_a.md", "audit_a.md")
BT_GUARD_HO_SHA256 = "a81cba6e153bdb39b8c1a3f10cb1ccccf7ac66dd2b46db587b713a45fd1835ab"  # HO ho_tools/bt_guard.py


class HoError(Exception):
    """A question-writing tool refused its input (bad state, missing pin, unfinished phase, ...)."""


class BudgetRefused(HoError):
    """§8.2: spent + this job's cap would exceed the hard cap; the job is not started."""


@dataclass(frozen=True)
class Violation:
    """One failed mechanical rule; level 'error' sends the draft back, 'warn' is only recorded."""
    rule: str
    detail: str
    level: str = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def under(path: Path | str, root: Path | str) -> bool:
    p, r = Path(path).resolve(), Path(root).resolve()
    return p == r or r in p.parents


def out_dir(root: Path) -> Path:
    """Where freeze / K1 / K-U2 files of a run root live (OUT for the store root)."""
    return Path(root).resolve().parent


def write_json(path: Path, obj: Any) -> Path:
    """Atomic JSON write (temp file + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tool_sha(names: Iterable[str] = TOOL_FILES) -> dict[str, str]:
    """sha256 of the ho_a files that exist (F1 records them)."""
    return {n: sha256_file(HO_A / n) for n in names if (HO_A / n).is_file()}


def meta(script: str, **extra: Any) -> dict[str, Any]:
    """Run meta of one tool call: script, time, python, tool and frozen-input sha256 values."""
    segs = C.SEGMENTS
    return {"script": script, "utc": now(), "python": sys.executable, "tools_sha256": tool_sha(),
            "segments_sha256": sha256_file(segs) if segs.is_file() else None, **extra}


def check_guard_copy() -> None:
    """bt_guard.py must stay a verbatim copy of the HO hook (confirm_A.md §9)."""
    got = sha256_file(HO_A / "bt_guard.py")
    if got != BT_GUARD_HO_SHA256:
        raise HoError(f"bt_guard.py sha256 {got[:12]} is not the HO copy {BT_GUARD_HO_SHA256[:12]}")


def as_mapping(obj: Any) -> Mapping[str, Any]:
    return obj if isinstance(obj, Mapping) else {}

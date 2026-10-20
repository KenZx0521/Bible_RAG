"""Errors, records and pins shared by this experiment's agent launches (prereg §3.1, §3.9, §8.2).

Both agent uses share them: the HO blind writing (writers, value-blind auditors, fixers and Kay's revisions under
HO_ROOT, prereg §3) and the qset P1/P2 writers (QSET_ROOT, §5.4). Copied in part from experiment A's
ho_a/hoa_common.py (the original untouched), without its sys.path lines and its ``import c_common``: that import
resolves to A's constants (USD_CAP 140, job caps 4/3/1.5, HO root A_confirm/ho) and, once ``GC.stage0()`` has run,
to A's modules (§3.9). Money, attempt and path constants all come from g_common (these aliases are its objects):

* PROBE_ROOT  store OUT_ROOT/probe/: one sub-root <n>/ per CLI probe invocation (ledger_g counts them)
* CLI_DIR     store OUT_ROOT/cli/: the pinned CLI executable copied there at probe time (§3.1: versions/ is cleaned)
* BT_GUARD    HO's original ho_tools/bt_guard.py, run by path (the hook) or loaded by path for its command rule
              (transcript_g), always after the sha256 check; no copy of it exists in this experiment
* TOOL_FILES  the agent-tool files whose sha256 ``meta`` / ``tool_sha`` log (the HO runner logs them with every
              command): the launch and check tools, the HO and qset runners' modules and the prompt files they render

Store writes go through g_common.write_json (g_common.writable: the store only under reports/gen_confirm_20261020/,
never the repo); ``writable`` is the same check raising HoError instead of SystemExit, so a launch refuses before
anything starts. Errors: HoError (a launch tool refused), BudgetRefused (§3.9), CliChanged (the pinned CLI copy or
its `--version` changed: §3.1 重做 probe) and CliUnavailable (`claude --version` gave no answer twice: a transient
infrastructure failure, not a change). Host python, stdlib only. Nothing here launches an agent.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

import g_common as GC

HERE = GC.HERE
PROBE_ROOT = GC.PROBE_ROOT
CLI_DIR = GC.CLI_DIR
BT_GUARD = GC.BT_GUARD
BT_GUARD_SHA256 = "a81cba6e153bdb39b8c1a3f10cb1ccccf7ac66dd2b46db587b713a45fd1835ab"
# this experiment's agent-tool files (meta / the runners record them): the launch and check tools, the HO runner
# (run_ho_g.HO_FILES is this tuple) and the qset runner with the prompt files they render
TOOL_FILES = ("hog_common.py", "claude_g.py", "bt_g.py", "ledger_g.py", "transcript_g.py", "probe_g.py",
              "banned_g.py", "prompts_g.py", "mech_g.py", "gen_g.md", "audit_g.md",
              "state_g.py", "runs_g.py", "run_ho_g.py", "kay_g.py", "freeze_g.py",
              "run_qg.py", "spec_qg.py", "prompt_qg.py", "prompts_qg.md", "mech_qg.py")
_GUARD_MODULE = "ho_bt_guard_for_g"


class HoError(Exception):
    """An agent-launch tool refused its input (bad state, missing or changed pin, unsafe cwd, ...)."""


class BudgetRefused(HoError):
    """prereg §3.9 / §8.2: spent + this job's cap would pass a cap; nothing was reserved or started."""


class CliChanged(HoError):
    """The pinned CLI copy is missing or hashes differently, or `claude --version` names another version (§3.1:
    an infrastructure stop; probe again)."""


class CliUnavailable(HoError):
    """`claude --version` gave no answer (timeout, start failure, non-zero exit) on every try: retry the job later;
    not a CLI change, no new probe."""


@dataclass(frozen=True)
class Violation:
    """One failed transcript or launch rule; level 'error' voids the run's output, 'warn' is only recorded."""
    rule: str
    detail: str
    level: str = "error"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path | str) -> str:
    return GC.sha256_file(path)


def sha256_text(text: str) -> str:
    return GC.sha256_text(text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path | str) -> Any:
    return GC.read_json(path)


def write_json(path: Path | str, obj: Any) -> Path:
    """Atomic JSON write behind g_common.writable (never the repo; the store only under OUT_ROOT)."""
    return GC.write_json(path, obj)


def writable(path: Path | str) -> Path:
    """g_common.writable as a HoError (the repo, frozen store folders and the store outside OUT_ROOT refused)."""
    try:
        return GC.writable(path)
    except SystemExit as err:
        raise HoError(str(err)) from None


def under(path: Path | str, root: Path | str) -> bool:
    p, r = Path(path).resolve(), Path(root).resolve()
    return p == r or r in p.parents


def as_mapping(obj: Any) -> Mapping[str, Any]:
    return obj if isinstance(obj, Mapping) else {}


def check_guard(path: Path | None = None) -> str:
    """HO's bt_guard.py (or `path`) must be the pinned original (prereg §3.1); returns its sha256."""
    path = BT_GUARD if path is None else Path(path)
    got = sha256_file(path) if path.is_file() else "missing"
    if got != BT_GUARD_SHA256:
        raise HoError(f"bt_guard.py sha256 {got[:12]} is not HO's original {BT_GUARD_SHA256[:12]}")
    return got


def bt_guard() -> ModuleType:
    """HO's bt_guard loaded by path after the sha256 check (its check_command is t_tool's rule); cached."""
    mod = sys.modules.get(_GUARD_MODULE)
    if mod is not None:
        return mod
    check_guard()
    spec = importlib.util.spec_from_file_location(_GUARD_MODULE, BT_GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[_GUARD_MODULE] = mod
    return mod


def tool_sha(names: Iterable[str] = TOOL_FILES) -> dict[str, str]:
    """sha256 of this experiment's agent-tool files that exist, plus HO's bt_guard by its repo path."""
    out = {n: sha256_file(HERE / n) for n in names if (HERE / n).is_file()}
    out[str(BT_GUARD.relative_to(GC.REPO))] = sha256_file(BT_GUARD)
    return out


def meta(script: str, names: Iterable[str] = TOOL_FILES, **extra: Any) -> dict[str, Any]:
    """Run meta of one tool call: script, time, interpreter, tool-file sha256 values."""
    return {"script": script, "utc": now(), "python": sys.executable, "tools_sha256": tool_sha(names), **extra}

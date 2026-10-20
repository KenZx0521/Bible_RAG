"""Blinding word lists of the GEN confirmation set's writers and auditors, and their scope rule (prereg §3.3).

Three lists, each with its own scope:

* MEMORY_MARKERS: a hit anywhere (prompt or transcript, agent output included) is a blinding error. HO's and
  experiment A's markers plus this experiment's file and directory names (G_MEMORY_MARKERS).
* PROMPT_TERMS: never in the fixed part of a prompt. HO's and A's prompt terms, 算術, 觸發, 規則種子, 年歲卡,
  推導卡, and the trigger's cue words themselves: ``gencard.CUE_LITERALS``, imported lazily on first use and never
  copied, so a writer is not primed with them. Tests inject a stand-in tuple (``override_cue_literals``).
* BANNED_TERMS: the transcript list (the writer's and auditor's output and tool calls). HO's banned terms, A's
  A_LEAK_TERMS, and words only this project uses: T-rows, G-ref, B0, rule seed, gencard. 算術 and 觸發 are
  ordinary Chinese and stay prompt-only.

Scope rule (the regnal qset's): templates, JSON schemas and tool-rendered values (slot id, English slot
definition, X / Y names, marker string, mech details, value hints) get the full prompt check, which is
PROMPT_TERMS + BANNED_TERMS + MEMORY_MARKERS (HO builds its PROMPT_TERMS the same way); agent-written fields
embedded in a prompt (question, steps, audit findings, fix requests, Kay's notes) get MEMORY_MARKERS only,
because a question the trigger can fire on holds age and event cue words by construction; a transcript gets
BANNED_TERMS + MEMORY_MARKERS.

Not banned: a bare GEN (HO's matching would hit every bt call and every verse key gen.N.M), F1 and F5 (no
longer in any schema: the neutral qtypes are age_at_birth / age_at_death), arith (ASCII terms match on word
boundaries, so arithmetic is safe; this experiment's file names are memory markers).

HO's banned.py is loaded by path (sha pinned) for its lists and its matching rule (ASCII case-insensitive on word
boundaries, CJK as substrings). A's banned_a.py lists are read as literals from its source (sha pinned, never
executed): no module under ho_a/ is loaded, as the prereg §3.9 sys.modules test needs. Their paths are
g_common's (HO_BANNED, A_BANNED, GENCARD_DIR).

The memory markers name every file of this experiment by stem. ASCII markers match on letter and digit boundaries
only (HO's rule: "_" is not a boundary), so a stem never hits a longer name that merely contains it: bt_g is not
found in bt_guard, mech_g not in mech_qg, run_g not in run_ho_g; each of those is a marker of its own.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import g_common as GC

HO_BANNED = GC.HO_BANNED
HO_BANNED_SHA256 = "d2226711f27934b4188f2c17c2151628771788736afe29035e10c276d1efc8ee"
A_BANNED = GC.A_BANNED
A_BANNED_SHA256 = "5466992819622ec276a78d3e83897a02e53857d7f81260d79d8d8f9ee1eebcfd"
GENCARD_DIR = GC.GENCARD_DIR
SCOPES = ("prompt", "agent", "transcript")


class BlindingError(ValueError):
    """A prompt part holds a word its scope forbids."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_ho():
    if _sha256(HO_BANNED) != HO_BANNED_SHA256:
        raise RuntimeError(f"{HO_BANNED.name} changed (sha256 pinned in banned_g.py)")
    name = "ho_banned_for_g"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HO_BANNED)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                       # dataclasses look the module up while it loads
    spec.loader.exec_module(mod)
    return mod


def literal_tuples(path: Path, sha256: str, names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """The tuple-of-strings literals `names` assigned at the top level of a pinned source file (never executed)."""
    if _sha256(path) != sha256:
        raise RuntimeError(f"{Path(path).name}: sha256 is not the pinned {sha256[:12]}")
    found: dict[str, tuple[str, ...]] = {}
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in names:
            value = ast.literal_eval(node.value)
            if not (isinstance(value, tuple) and all(isinstance(t, str) for t in value)):
                raise RuntimeError(f"{Path(path).name}: {node.targets[0].id} is not a tuple of strings")
            found[node.targets[0].id] = value
    missing = [n for n in names if n not in found]
    if missing:
        raise RuntimeError(f"{Path(path).name}: missing {missing}")
    return found


def _dedupe(*parts: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(t for p in parts for t in p))


HO = _load_ho()
Hit = HO.Hit
_A = literal_tuples(A_BANNED, A_BANNED_SHA256, ("A_PROMPT_TERMS", "A_LEAK_TERMS", "A_MEMORY_MARKERS"))
A_PROMPT_TERMS, A_LEAK_TERMS, A_MEMORY_MARKERS = _A["A_PROMPT_TERMS"], _A["A_LEAK_TERMS"], _A["A_MEMORY_MARKERS"]
# banned_a's own PROMPT_TERMS / BANNED_TERMS / MEMORY_MARKERS, rebuilt the way banned_a builds them
A_LEVEL_PROMPT_TERMS = _dedupe(HO.PROMPT_TERMS, A_PROMPT_TERMS)
A_LEVEL_BANNED_TERMS = _dedupe(HO.BANNED_TERMS, A_LEAK_TERMS)
A_LEVEL_MEMORY_MARKERS = _dedupe(HO.MEMORY_MARKERS, A_MEMORY_MARKERS)

G_PROMPT_TERMS = ("算術", "觸發", "規則種子", "年歲卡", "推導卡")
G_LEAK_TERMS = ("T-rows", "G-ref", "B0", "rule seed", "gencard")
# this experiment's file and directory names (prereg §3.3), the prompt files by stem; the prereg's list first, then
# every later file of this folder (banned_g, names_g, the agent tools, the HO and qset runners, K0, smoke, void)
G_MEMORY_MARKERS = ("gen_confirm", "gencard", "gen_layer", "gen_names", "g_common", "x_common", "arith_stage0",
                    "power_g", "pool_g", "order_g", "mech_g", "run_g", "analyze_g", "gen_g", "audit_g", "prompts_g",
                    "banned_g", "names_g", "regnal_qset",
                    "hog_common", "claude_g", "bt_g", "ledger_g", "transcript_g", "probe_g", "arms_g", "score_g",
                    "f1_g", "f2_g", "f1a_g", "freeze_g", "kay_g", "run_ho_g", "runs_g", "state_g", "spec_qg",
                    "prompt_qg", "prompts_qg", "mech_qg", "run_qg", "k0_g", "smoke_g", "void_g")

MEMORY_MARKERS = _dedupe(A_LEVEL_MEMORY_MARKERS, G_MEMORY_MARKERS)
BANNED_TERMS = _dedupe(A_LEVEL_BANNED_TERMS, G_LEAK_TERMS)
BASE_PROMPT_TERMS = _dedupe(A_LEVEL_PROMPT_TERMS, G_PROMPT_TERMS)   # PROMPT_TERMS without the cue words

_CUES: tuple[str, ...] | None = None


def _gencard_cues() -> tuple[str, ...]:
    mod = importlib.import_module("gencard")
    if Path(mod.__file__).resolve().parent != GENCARD_DIR.resolve():
        raise RuntimeError(f"gencard resolved to {mod.__file__}, not {GENCARD_DIR}")
    cues = getattr(mod, "CUE_LITERALS", None)
    if cues is None:
        cues = getattr(importlib.import_module("gencard.trigger"), "CUE_LITERALS", None)
    if not (isinstance(cues, tuple) and cues and all(isinstance(c, str) and c for c in cues)):
        raise RuntimeError("gencard.CUE_LITERALS must be a non-empty tuple of non-empty strings")
    return cues


def cue_literals() -> tuple[str, ...]:
    """gencard.CUE_LITERALS (prereg §5.2 rules 7 and 10), imported on first use; or the injected stand-in."""
    global _CUES
    if _CUES is None:
        _CUES = _gencard_cues()
    return _CUES


@contextlib.contextmanager
def override_cue_literals(cues: Sequence[str] | None) -> Iterator[None]:
    """Use `cues` as the cue words inside the block (None: gencard's, imported afresh); restores afterwards."""
    global _CUES
    saved = _CUES
    _CUES = tuple(cues) if cues is not None else None
    try:
        yield
    finally:
        _CUES = saved


def prompt_terms() -> tuple[str, ...]:
    return _dedupe(BASE_PROMPT_TERMS, cue_literals())


def __getattr__(name: str):
    if name == "PROMPT_TERMS":                    # lazy: needs gencard (or an injected stand-in)
        return prompt_terms()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def find_terms(text: str, terms: Iterable[str], where: str = "") -> list:
    """Every occurrence of every term (HO matching rule)."""
    return HO.find_terms(text, tuple(dict.fromkeys(terms)), where)


def prompt_hits(text: str, where: str = "prompt") -> list:
    """Full check: templates, schemas and tool-rendered values."""
    return find_terms(text, prompt_terms() + BANNED_TERMS + MEMORY_MARKERS, where)


def agent_hits(text: str, where: str = "agent") -> list:
    """Agent-written text embedded in a prompt: memory markers only."""
    return find_terms(text, MEMORY_MARKERS, where)


def transcript_hits(text: str, where: str = "transcript") -> list:
    """What a writer or auditor read or wrote: banned terms and memory markers."""
    return find_terms(text, BANNED_TERMS + MEMORY_MARKERS, where)


_CHECK = {"prompt": prompt_hits, "agent": agent_hits, "transcript": transcript_hits}


def require(text: str, where: str, scope: str = "prompt") -> str:
    """`text` unchanged when its scope's check finds nothing; BlindingError naming the terms otherwise."""
    if scope not in _CHECK:
        raise ValueError(f"unknown scope {scope!r} (one of {SCOPES})")
    hits = _CHECK[scope](text, where)
    if hits:
        raise BlindingError(f"{where}: {scope} check found {sorted({h.term for h in hits})}")
    return text


def check_prompt_file(path: Path | str) -> list:
    return prompt_hits(Path(path).read_text(encoding="utf-8"), str(path))

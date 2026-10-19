"""Blinding checks of the writers' and labeller's input (qset.md §3): what they read must not name a cue.

The banned list is for the writer's *input* only. A writer's output may use any word: the cue words
(之後, 第二位, 篡, 出生時 …) are ordinary Chinese, and banning them would measure adversarial
phrasings instead of real ones. Every rendered prompt (system, user, schema) must pass:

* the trigger's own regexes: ``backend/utils/regnal/trigger.py`` CUES, searched on the NFKC text,
  0 matches (imported from this checkout, never copied);
* CUE_LITERALS: the literal fragments of every CUES branch (a test checks each branch's canonical
  example holds one, so a new branch without a literal here fails the tests);
* HO's and experiment A's prompt terms (ho_tools/banned.py and ho_a/banned_a.py, loaded by path with
  their sha pinned, never changed) plus Q_PROMPT_TERMS (this tool's purpose words);
* MEMORY_MARKERS: HO + A + Q_MEMORY_MARKERS (names only this project's code and memory use). In a
  transcript a marker anywhere is a blinding error (t_memory), output included, so Q's markers are
  code forms only (trigger.py, utils.regnal, regnal_layer …): words a writer may well think in plain
  English ("regnal year", "cues") are prompt-only terms (Q_PROMPT_TERMS), banned from every prompt
  but never voiding a job (review 2026-10-19).

ASCII terms match case-insensitively on word boundaries, CJK terms as substrings (HO rule).
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

from q_common import HERE, regnal

HO_BANNED = HERE.parent / "2026-10-14_graph_gd" / "ho_tools" / "banned.py"
HO_BANNED_SHA256 = "d2226711f27934b4188f2c17c2151628771788736afe29035e10c276d1efc8ee"
A_BANNED = HERE.parent / "2026-10-18_kg_cards" / "A" / "confirm" / "ho_a" / "banned_a.py"
A_BANNED_SHA256 = "5466992819622ec276a78d3e83897a02e53857d7f81260d79d8d8f9ee1eebcfd"


def _load(path: Path, sha: str, name: str):
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise RuntimeError(f"{path.name} changed (sha256 pinned in banned_q.py)")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                       # dataclasses look the module up while it loads
    spec.loader.exec_module(mod)
    return mod


HO = _load(HO_BANNED, HO_BANNED_SHA256, "ho_banned_for_q")
A = _load(A_BANNED, A_BANNED_SHA256, "banned_a_for_q")
Hit = HO.Hit

# the literal fragments of trigger.CUES (S1a: 之後/之前/以後/以前, 往前數/往後數, 接續…作王, 繼位;
# S1b: 交接, 相隔; S1c: 篡; S4: 出生時/出生的時/出生那年 … 在位/作…王)
CUE_LITERALS = ("之後", "之前", "以後", "以前", "往前數", "往後數", "接續", "作王", "繼位", "交接", "相隔", "篡",
                "出生時", "出生的時", "出生那年", "在位",
                # the 2026-10-19 relaxation (trigger.py group ``new``), after P1 and P2 were written
                "往前", "往後", "往下", "隔", "下一任", "上一任", "上上任", "下下任", "繼任", "接任", "接著", "更迭",
                "更替", "換手", "換王", "幾次", "謀反", "弒", "殺王", "政變", "奪位", "出生", "誕生", "做王", "當王", "執政",
                "統治", "掌權")
Q_PROMPT_TERMS = ("觸發", "召回", "年表", "線索", "誤觸", "近似", "問法集", "分母", "規則種子", "標註器", "鎖住",
                  "trigger", "recall", "regex", "cue", "cues", "regnal", "P1", "P2", "near miss", "near-miss")
Q_MEMORY_MARKERS = ("trigger.py", "trigger.CUES", "_KTH", "utils.regnal", "regnal_layer", "aux_card",
                    "use_regnal_card", "年表卡", "ref_layer", "layer_auto", "regnal_qset", "qset", "rule_seeds",
                    "chronology_card")
PROMPT_TERMS = tuple(dict.fromkeys(A.PROMPT_TERMS + Q_PROMPT_TERMS + CUE_LITERALS))
MEMORY_MARKERS = tuple(dict.fromkeys(A.MEMORY_MARKERS + Q_MEMORY_MARKERS))


def find_terms(text: str, terms: Iterable[str], where: str = "") -> list:
    """Every occurrence of every term (HO matching rule)."""
    return HO.find_terms(text, terms, where)


def cue_hits(text: str, where: str = "") -> list:
    """Matches of the trigger's CUES regexes on the NFKC text, as Hit(term='CUES:<type>')."""
    q = unicodedata.normalize("NFKC", text)
    out = []
    for qtype, pat in regnal().trigger.CUES.items():
        for m in pat.finditer(q):
            lo, hi = max(m.start() - 20, 0), min(m.end() + 20, len(q))
            out.append(Hit(f"CUES:{qtype}", where, q[lo:hi].replace("\n", " ")))
    return out


def check_prompt_text(text: str, where: str = "prompt") -> list:
    """Everything a writer or labeller reads: CUES, cue literals, HO / A / Q prompt terms, memory markers."""
    return cue_hits(text, where) + find_terms(text, PROMPT_TERMS + MEMORY_MARKERS, where)


def memory_hits(text: str, where: str = "") -> list:
    return find_terms(text, MEMORY_MARKERS, where)

"""Blinding word checks of the question-writing tools (confirm_A.md §2.5, §2.6-12): HO banned.py plus A's words.

The HO lists are loaded from 2026-10-14_graph_gd/ho_tools/banned.py (read only, sha recorded) and
extended:

* PROMPT_TERMS = HO PROMPT_TERMS + A_PROMPT_TERMS (§2.6-12: 引擎、推導、卡片、模板、種子、pilot, ...).
  A prompt file (and the output schema) must contain none of them. 「推算」 is a normal question word
  and is not banned.
* BANNED_TERMS (transcripts: t_banned in the system prompt, t_banned_agent warnings elsewhere) =
  HO BANNED_TERMS + A_LEAK_TERMS: A words an agent would only write after seeing this project.
  種子、模板、推導、卡片 occur in Bible text or plain Chinese, so they stay prompt-only.
* MEMORY_MARKERS (t_memory errors anywhere) = HO MEMORY_MARKERS + A_MEMORY_MARKERS (file and directory
  names of this experiment).

ASCII terms match case-insensitively on word boundaries, CJK terms as substrings (HO rule).
CLI: `banned_a.py FILE ...` checks prompt files; exit 1 on a hit, 2 on error.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Iterable, Sequence

HO_BANNED = Path(__file__).resolve().parents[4] / "2026-10-14_graph_gd" / "ho_tools" / "banned.py"
HO_BANNED_SHA256 = "d2226711f27934b4188f2c17c2151628771788736afe29035e10c276d1efc8ee"


def _load_ho():
    if hashlib.sha256(HO_BANNED.read_bytes()).hexdigest() != HO_BANNED_SHA256:
        raise RuntimeError(f"{HO_BANNED.name} changed (sha256 pinned in banned_a.py)")
    name = "ho_banned_for_a"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HO_BANNED)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                       # dataclasses look the module up while it loads
    spec.loader.exec_module(mod)
    return mod


HO = _load_ho()
Hit = HO.Hit
A_PROMPT_TERMS = ("引擎", "推導", "推導行", "卡片", "年表層", "王朝層", "層列", "模板", "種子", "gemma", "Ollama",
                  "開發集", "確認集", "pilot", "盲集", "參照層", "stage", "kg_cards", "kgniche", "T-canon", "T-rows",
                  "G-auto", "G-ref")
A_LEAK_TERMS = ("推導行", "年表層", "王朝層", "層列", "gemma", "Ollama", "開發集", "確認集", "盲集", "參照層",
                "T-canon", "T-rows", "G-auto", "G-ref")
A_MEMORY_MARKERS = ("kg_cards", "kgniche", "A_confirm", "confirm_A", "cards_common", "kg_niche", "graph_qd",
                    "stage-0", "c_common", "ho_a")
PROMPT_TERMS = tuple(dict.fromkeys(HO.PROMPT_TERMS + A_PROMPT_TERMS))
BANNED_TERMS = tuple(dict.fromkeys(HO.BANNED_TERMS + A_LEAK_TERMS))
MEMORY_MARKERS = tuple(dict.fromkeys(HO.MEMORY_MARKERS + A_MEMORY_MARKERS))


def find_terms(text: str, terms: Iterable[str], where: str = "") -> list:
    """Every occurrence of every term (HO matching rule)."""
    return HO.find_terms(text, terms, where)


def check_prompt_text(text: str, where: str = "prompt") -> list:
    """Prompt check: HO banned, purpose and memory words plus A's words."""
    return find_terms(text, PROMPT_TERMS + MEMORY_MARKERS, where)


def check_prompt_file(path: Path | str) -> list:
    return check_prompt_text(Path(path).read_text(encoding="utf-8"), str(path))


def main(argv: Sequence[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print("banned_a.py: usage: banned_a.py FILE ...", file=sys.stderr)
        return 2
    try:
        hits = [h for p in paths for h in check_prompt_file(p)]
    except OSError as err:
        print(f"banned_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    for h in hits:
        print(f"{h.where}: {h.term!r} in …{h.excerpt}…")
    print(f"banned_a.py: {len(hits)} hit(s) in {len(paths)} file(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())

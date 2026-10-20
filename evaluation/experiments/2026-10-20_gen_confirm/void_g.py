"""The one void record of the GEN confirmation set (prereg §4.4, §4.5, §8.1-10.7, §9): store void.json, written once.

Two steps can void the line before any formal answer exists, each under a new anchor line of prereg.md's
「執行紀錄」 (f1_g.anchor_problems, with the lines the caller says were in the log before its step and the anchors
earlier records used):
  parity      f2_g --void-anchor A: prompt parity failed and only cards_common or prod could fix it (§8.1-10.7);
  truncation  run_g smoke --void-truncated A: the smoke truncated and no infrastructure cause was found (§4.4).
The record {"schema", "why", "label", "anchor", "sentence", "t", "detail"} carries §9's sentence, analyze_g's void
template with its label (analyze_g.VOID_WHY), e.g. 「作廢（截斷），不構成任何方向的證據」. Once it exists ``problems`` is
never empty: run_g's smoke, run, score and dry run refuse, and analyze writes a report with that sentence only. A
record that cannot be read, or lacks its why, label or sentence, still voids (fail closed, of unknown cause).
``detail`` holds sha256 values and counts only. Every call names the record's path: f2_g puts it beside its f2.json
and run_g beside its run root (both OUT_ROOT/void.json, VOID_FILE; a test's tmp f2.json or run root keeps its own
record). Nothing here calls Ollama or any LLM.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable, Mapping

import analyze_g as AG
import f1_g as F1
import g_common as GC

SCHEMA = "gen_confirm.void.v1"
VOID_FILE = GC.VOID_FILE
WHYS = ("parity", "truncation")


def sentence(why: str) -> str:
    return AG.SENTENCE["void"].format(why=AG.VOID_WHY[why])


def read(path: Path) -> dict[str, Any] | None:
    """The void record, None when the line is not void; an unreadable record reads as a void of unknown cause."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        doc = GC.read_json(p)
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or doc.get("why") not in WHYS or \
            not all(isinstance(doc.get(k), str) and doc[k] for k in ("label", "sentence")):
        return {"schema": SCHEMA, "why": None, "label": "?", "anchor": None, "sentence": None, "unreadable": True}
    return doc


def problems(path: Path) -> list[str]:
    """[] unless the line is void (then every Ollama step and score refuses)."""
    doc = read(path)
    if doc is None:
        return []
    if doc.get("unreadable"):
        return [f"{Path(path).name} exists but cannot be read: the line is treated as void"]
    return [f"the line is void ({doc['label']}; {Path(path).name}): {doc['sentence']}"]


def write(why: str, anchor: str, *, path: Path, prereg: Path | None = None, seen: Iterable[str] = (),
          used: Iterable[str] = (), detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Write the void record once; refused when one exists or the anchor fails f1_g's rule."""
    if why not in WHYS:
        raise ValueError(f"{why!r} is not one of {WHYS}")
    p = Path(path)
    if p.exists():
        raise SystemExit(f"{p.name} exists: a void is recorded once")
    bad = F1.anchor_problems(anchor, Path(prereg or F1.PREREG), used=used, seen=seen)
    if bad:
        raise SystemExit(f"void refused: {bad}")
    doc = {"schema": SCHEMA, "why": why, "label": AG.VOID_WHY[why], "anchor": anchor.strip(), "sentence": sentence(why),
           "t": time.strftime("%Y-%m-%dT%H:%M:%S"), "detail": dict(detail or {})}
    GC.write_json(p, doc)
    return doc

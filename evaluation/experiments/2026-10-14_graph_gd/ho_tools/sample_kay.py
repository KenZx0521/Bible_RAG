"""§7 Kay 抽查: draw 15 of the HO candidates and build the review page (a file, not published).

The draw is `random.Random(20261014).sample(sorted(ids), 15)` over the current selection
(每類前 30 個通過稽核的題); on the formal root it needs a complete selection and happens
once. Kay's decisions are then applied: accept (nothing changes), revise (needs_fix with
Kay's note; run_gen.py fix and a re-audit follow), drop (dropped; later drafts refill).
freeze.py requires the sample drawn and every sampled question decided and settled.

    sample_kay.py draw  --root R          # <root>/kay/kay_sample.json, kay_sample.html
    sample_kay.py apply --root R --decisions D.json   # {"ID": {"decision": "...", "note": "..."}}

On a pilot root the draw takes min(15, n) of whatever passed, and nothing is binding.
Exit 0 ok, 2 error (one line).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import HO_DIR, SEED, HoToolError, gd, ho_meta  # first: sets sys.path

import _ho_state as S  # noqa: E402
import build_page  # noqa: E402

__all__ = ["SAMPLE_SIZE", "DECISIONS", "sample_ids", "page_questions", "draw", "apply", "main",
           "SCRIPT_FILES"]

SAMPLE_SIZE = 15
DECISIONS = ("accept", "revise", "drop")
SCRIPT_FILES = tuple(HO_DIR / n for n in ("sample_kay.py", "_ho_common.py", "_ho_state.py",
                                         "build_page.py", "annotate.py", "_ho_text.py",
                                         "page_template.html"))


def sample_ids(ids: Sequence[str], k: int = SAMPLE_SIZE, seed: int = SEED) -> list[str]:
    """§7: random.Random(20261014).sample(sorted(ids), 15)."""
    return random.Random(seed).sample(sorted(ids), k)


def page_questions(state: Mapping[str, Any], ids: Sequence[str]) -> list[dict[str, Any]]:
    """Annotated items of `ids` with their status and last audit, for the review page."""
    out = []
    for qid in ids:
        r = S.record(state, qid)
        last = (r.get("audits") or [{}])[-1]
        fixed = bool(r.get("fixes"))
        audit = {"severity": last.get("severity", "not_audited"), "issues": last.get("issues", []),
                 "outcome": "major／critical 已修正並複驗通過" if fixed else ""}
        out.append({**r["item"], "status": "fixed" if fixed else "accept", "audit": audit})
    return out


def draw(root: Path) -> dict[str, Any]:
    state = S.load_state(root)
    pilot = state["pilot"]
    cand = S.selected_ids(state)
    if not pilot and not S.is_complete(state):
        raise HoToolError(f"selection not complete: {S.summary(state)['selected']}")
    if not pilot and state.get("kay"):
        raise HoToolError("the Kay sample was already drawn (§7 draws once)")
    k = min(SAMPLE_SIZE, len(cand)) if pilot else SAMPLE_SIZE
    if k == 0 or len(cand) < k:
        raise HoToolError(f"{len(cand)} candidates, cannot draw {SAMPLE_SIZE}")
    ids = sample_ids(cand, k)
    kdir = Path(root) / "kay"
    kdir.mkdir(parents=True, exist_ok=True)
    note = f"從 {len(cand)} 題候選以 random.Random({SEED}).sample(sorted(ids), {k}) 抽出。"
    if pilot:
        note = "（試跑頁，題目一律丟棄）" + note
    build_page.write_page(page_questions(state, ids), kdir / "kay_sample.html", note)
    doc = {"meta": ho_meta("sample_kay.py draw", SCRIPT_FILES, root=str(root)), "pilot": pilot,
           "seed": SEED, "k": k, "candidates": sorted(cand), "candidates_ids_sha256": gd.ids_sha256(cand),
           "sample_ids": ids}
    (kdir / "kay_sample.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")
    kay = {"sample_ids": ids, "candidates_ids_sha256": doc["candidates_ids_sha256"],
           "drawn_utc": S.now(), "decisions": {}, "resolved": False}
    S.save_state(root, {**state, "kay": kay})
    return doc


def apply(root: Path, decisions: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """New saved state with Kay's decisions applied to sampled questions."""
    state = S.load_state(root)
    kay = state.get("kay")
    if not kay:
        raise HoToolError("no Kay sample drawn yet")
    for qid, d in decisions.items():
        if qid not in kay["sample_ids"]:
            raise HoToolError(f"{qid} is not in the Kay sample")
        if d.get("decision") not in DECISIONS:
            raise HoToolError(f"{qid}: decision must be one of {DECISIONS}")
        if qid in kay["decisions"]:
            raise HoToolError(f"{qid}: already decided ({kay['decisions'][qid]['decision']})")
    for qid, d in decisions.items():
        note = str(d.get("note") or "")
        if d["decision"] == "revise":
            req = {"source": "kay", "issues": [note or "（Kay 要求修改）"], "suggested_fix": ""}
            state = S.update_record(state, qid, S.NEEDS_FIX, f"Kay 要求修改：{note}", fix_request=req)
        elif d["decision"] == "drop":
            state = S.update_record(state, qid, S.DROPPED, f"Kay 刪除：{note}")
    decided = {**kay["decisions"], **{q: {"decision": d["decision"], "note": d.get("note", ""),
                                          "at": S.now()} for q, d in decisions.items()}}
    kay = {**kay, "decisions": decided, "resolved": set(decided) == set(kay["sample_ids"])}
    state = {**state, "kay": kay}
    S.save_state(root, state)
    return state


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draw")
    p.add_argument("--root", type=Path, required=True)
    p = sub.add_parser("apply")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--decisions", type=Path, required=True)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    if a.cmd == "draw":
        doc = draw(a.root)
        print(f"sample_kay.py draw: {doc['k']} of {len(doc['candidates'])} -> {a.root / 'kay'}")
    else:
        state = apply(a.root, json.loads(a.decisions.read_text(encoding="utf-8")))
        print(f"sample_kay.py apply: resolved={state['kay']['resolved']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"sample_kay.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)

"""F2 freeze of the confirmation questions (confirm_A.md §0 F2, §1.5 K-U2, §7).

Refuses unless: the pilot is done and k1.json (k1.py, main program) says stop false; the §8.2
re-estimate was applied; every slot is done and no draft waits (or drafting was stopped by the
re-estimate); the Kay page was drawn and applied, K0-1b did not stop and no Kay-sampled question
is still open; every passed question passes the mechanical check again and every run of it passes
the transcript rules (t_result only where the run was retried); no output exists yet.

Then K-U2 (§1.5): fewer than KU_MIN (12) segments with at least one passed question stops A —
k_u2.json records the frozen wording and questions_frozen.json is NOT written. Otherwise writes, in
the root's parent (OUT for the store root):
* questions_frozen.json   {"questions": [§2.8 item + pilot + slot]} — the input of items_c.py
* questions_frozen_manifest.json  sha256, 附錄 C rows (id, segment, qtype, key type), per-segment and
  per-type counts, slot outcomes, transcript breaches, ledger, Kay record (no question text)
* k_u2.json               the K-U2 verdict
* inputs_manifest.json    {"frozen": {"questions_frozen.json": sha256}} merged in (the F2 record that
                          collect_ctx and run_c prepare check); refused when it already names that file
The hidden flags (ref_disagree, gen_passage) go to <root>/hidden_flags.json for the post-run
description only.

    freeze_a.py [--root R]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from hoa_common import ROOT, C, HoError, meta, out_dir, read_json, sha256_file, write_json  # first: sys.path

import mech_a as M  # noqa: E402
import state_a as S  # noqa: E402
import transcript_a as TR  # noqa: E402

FROZEN, MANIFEST, KU2 = C.QUESTIONS_FROZEN.name, C.QUESTIONS_FROZEN_MANIFEST.name, C.K_U2.name
INPUTS = C.MANIFEST.name                    # inputs_manifest.json, shared with run_c (F3)


def _inputs_doc(dest: Path) -> dict[str, Any]:
    """inputs_manifest.json as it stands; refuses when it already records a questions_frozen.json sha."""
    path = dest / INPUTS
    doc = read_json(path) if path.is_file() else {}
    if FROZEN in (doc.get("frozen") or {}):
        raise HoError(f"{INPUTS} already records a {FROZEN} sha: a frozen file is never rewritten")
    return doc


def record_f2(dest: Path, sha: str, stamp: Mapping[str, Any]) -> Path:
    """Merge the F2 sha into inputs_manifest.json (other keys and frozen entries kept)."""
    doc = _inputs_doc(dest)
    return write_json(dest / INPUTS, {**doc, "frozen": {**(doc.get("frozen") or {}), FROZEN: sha},
                                      "f2": {"utc": stamp["utc"], "script": stamp["script"]}})


def _transcript_errors(root: Path, state: Mapping[str, Any], recs: Sequence[Mapping[str, Any]]) -> list[str]:
    out = []
    for r in recs:
        for run in r["runs"]:
            retried = (state["runs"].get(run) or {}).get("error") is not None
            out += [f"{run}: {v.rule}" for v in TR.check_run(root, run)
                    if v.level == "error" and not (retried and v.rule == "t_result")]
    return out


def check_ready(root: Path, state: Mapping[str, Any], seg_doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The passed records, after every pre-freeze condition holds."""
    slots = S.slot_plan(seg_doc)
    if not S.pilot_finished(state, slots):
        raise HoError("the pilot is not complete")
    k1 = out_dir(root) / C.K1_JSON.name
    if not k1.is_file() or read_json(k1).get("stop") is not False:
        raise HoError("K1 missing or stopped: A does not freeze (§3)")
    if not state.get("reestimate"):
        raise HoError("the §8.2 re-estimate was not applied")
    if not S.is_complete(state, slots, "main"):
        raise HoError(f"questions not finished: {S.summary(state, slots)}")
    kay = state.get("kay") or {}
    if not kay.get("resolved"):
        raise HoError("the Kay page is not drawn or not applied (§7)")
    if (kay.get("layer") or {}).get("stop"):
        raise HoError(f"K0-1b stopped: {kay['layer']['wording']}")
    open_ = [q for q in kay["question_ids"] if S.record(state, q)["status"] in S.UNRESOLVED]
    if open_:
        raise HoError(f"Kay-sampled questions still open: {open_}")
    found = M.recheck(state, seg_doc, slots)
    bad = sorted(q for q, vs in found.items() if any(v["level"] == "error" for v in vs))
    if bad:
        raise HoError(f"mechanical check fails for {bad}")
    recs = S.records(state, (S.PASSED,))
    errors = _transcript_errors(root, state, recs)
    if errors:
        raise HoError(f"transcript check fails: {errors[:5]}{' …' if len(errors) > 5 else ''}")
    return recs


def ku2(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    segs = sorted({r["segment"] for r in recs})
    stop = len(segs) < C.KU_MIN
    return {"rule": "K-U2", "n_units": len(segs), "min": C.KU_MIN, "units": segs, "stop": stop,
            "wording": C.WORDING["stop"].format(rule="K-U2", value=f"凍結單位 n＝{len(segs)}<{C.KU_MIN}", state="未跑")
            if stop else f"K-U2：凍結單位 n＝{len(segs)} ≥ {C.KU_MIN}，通過"}


def key_type(item: Mapping[str, Any]) -> str:
    return "number" if (item.get("answer") or {}).get("kind") == "count" else "name"


def manifest(state: Mapping[str, Any], recs: Sequence[Mapping[str, Any]], seg_doc: Mapping[str, Any],
             sha: str, root: Path) -> dict[str, Any]:
    slots = S.slot_plan(seg_doc)
    rows = [{"id": r["id"], "segment": r["segment"], "qtype": r["qtype"], "key_type": key_type(r["item"]),
             "pilot": r["pilot"], "slot": r["slot"]} for r in recs]
    outcome = {s.key: ("passed" if S.passed_record(state, s.key) else
                       "cancelled" if s.key in state["cancelled"] else "empty") for s in slots}
    return {"file": FROZEN, "sha256": sha, "n": len(recs), "appendix_c": rows,
            "by_segment": {sid: sum(r["segment"] == sid for r in recs) for sid in S.segment_rows(seg_doc)},
            "by_qtype": {t: sum(r["qtype"] == t for r in recs) for t in ("S1a", "S1b", "S1c", "S4")},
            "slots": outcome, "attempts": {s.key: S.attempts_used(state, s.key) for s in slots},
            "summary": S.summary(state, slots), "ledger_total_usd": S.ledger(root)["total_usd"],
            "reestimate": state.get("reestimate"), "cap_stop": state.get("cap_stop"),
            "kay": {k: v for k, v in (state.get("kay") or {}).items() if k != "decisions"} |
                   {"decisions": {q: d["decision"] for q, d in ((state.get("kay") or {}).get("decisions") or {}).items()}},
            "segments_sha256": sha256_file(C.SEGMENTS) if C.SEGMENTS.is_file() else None}


def freeze(root: Path, segments_path: Path = C.SEGMENTS) -> dict[str, Any]:
    root, dest = Path(root), out_dir(root)
    for name in (FROZEN, MANIFEST, KU2):
        if (dest / name).exists():
            raise HoError(f"{name} exists: a frozen file is never rewritten")
    _inputs_doc(dest)
    state, seg_doc = S.load_state(root), S.load_segments(segments_path)
    recs = check_ready(root, state, seg_doc)
    verdict = {"meta": meta("freeze_a.py"), **ku2(recs)}
    if verdict["stop"]:
        write_json(dest / KU2, verdict)
        return verdict
    rows = S.passed_items(state)
    write_json(dest / FROZEN, {"n": len(rows), "questions": rows})
    sha = sha256_file(dest / FROZEN)
    write_json(dest / MANIFEST, {"meta": verdict["meta"], **manifest(state, recs, seg_doc, sha, root)})
    record_f2(dest, sha, verdict["meta"])
    write_json(dest / KU2, {**verdict, "questions_frozen_sha256": sha})
    write_json(root / "hidden_flags.json", {r["id"]: r.get("hidden") for r in recs})
    return {**verdict, "questions_frozen_sha256": sha, "n": len(rows)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="F2 凍結：questions_frozen.json、清單與 K-U2")
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    doc = freeze(a.root)
    print(f"freeze_a.py: {doc['wording']}" + (f"; sha256 {doc['questions_frozen_sha256']}" if not doc["stop"] else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HoError, OSError, ValueError) as err:
        print(f"freeze_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)

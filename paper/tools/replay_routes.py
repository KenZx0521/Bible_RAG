#!/usr/bin/env python3
"""Reproduce the paper's intent-classifier evidence (Sections V-C, XI-A).

1. Replays the backend signal detector with an EMPTY classifier output
   (intent = verse_lookup if a verse reference parses, else topic; no
   entities, no keywords) and compares the replayed route with the logged
   route of every archived graph-mode run. A full match means the run was
   routed by the regex and dictionary signals alone, i.e. the classifier
   had silently fallen back.
2. Compares the July 15, 2026 graph run (pre-repair) with the Round 3
   graph run: route changes, classifier-fed strategy invocations, and
   graph-configuration retrieval.

Archived runs are read from git history; Round 3 from the working tree.
The event keyword added in the fusion round (commit 046040a) is removed
when replaying Rounds 0-1.

Usage:  python3 paper/tools/replay_routes.py
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
logging.disable(logging.CRITICAL)

import utils.entity_dicts as entity_dicts  # noqa: E402
from utils.signal_detector import detect_signals  # noqa: E402
from utils.verse_parser import parse_verse_references  # noqa: E402

FUSION_ROUND_KEYWORD = "客西馬尼禱告"
HEAD = "b2c27d9"  # last commit that still tracks the Round 0-1 archives
RUNS = (
    # label, git revision, path, keyword set predates the fusion round
    ("Round 0, Gemma", HEAD, "evaluation/results_graph_gemma_answer", True),
    ("Round 0, Claude", HEAD, "evaluation/results_graph_claude_answer", True),
    ("Round 1 (P0)", HEAD, "evaluation/results_graph_p0_after", True),
    ("Round 2 (fusion)", "d85c7eb", "evaluation/results_graph", False),
    ("July 15, 500 q.", "5a45393", "evaluation/results_graph", False),
    ("Round 3, graph", None, "evaluation/results_graph", False),
)
JULY15 = ("5a45393", "evaluation/results_graph")
ROUND3 = (None, "evaluation/results_graph")


def read_json(rev: str | None, path: str):
    if rev is None:
        return json.loads((REPO / path).read_text())
    blob = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"],
                          check=True, capture_output=True).stdout
    return json.loads(blob)


@contextmanager
def keyword_set_before_fusion_round(active: bool):
    """Temporarily drop the event keyword that the fusion round added."""
    removed = active and FUSION_ROUND_KEYWORD in entity_dicts.EVENT_KEYWORDS
    if removed:
        entity_dicts.EVENT_KEYWORDS.discard(FUSION_ROUND_KEYWORD)
    try:
        yield
    finally:
        if removed:
            entity_dicts.EVENT_KEYWORDS.add(FUSION_ROUND_KEYWORD)


def replay_route(question: str) -> str:
    refs = parse_verse_references(question)
    intent = "verse_lookup" if refs else "topic"
    return detect_signals(question, refs, intent, [], []).route


def main() -> None:
    gt = {x["question_id"]: x["question"] for x in
          json.loads((REPO / "ground_truth.json").read_text())["questions"]}

    print("== 1. empty-classifier replay vs logged routes")
    for label, rev, path, pre_fusion in RUNS:
        raw = read_json(rev, f"{path}/raw_responses.json")
        logged = {x["question_id"]: x["route_used"] for x in raw}
        with keyword_set_before_fusion_round(pre_fusion):
            mismatch = [q for q in logged if replay_route(gt[q]) != logged[q]]
        legacy = Counter(r for q, r in logged.items() if int(q.rsplit("_", 1)[1]) <= 20)
        print(f"   {label:17s} match {len(logged) - len(mismatch)}/{len(logged)}; "
              f"original-100 routes {dict(sorted(legacy.items()))}")

    print("\n== 2. July 15 (pre-repair) vs Round 3 graph run")
    old = {x["question_id"]: x for x in read_json(JULY15[0], f"{JULY15[1]}/raw_responses.json")}
    new = {x["question_id"]: x for x in read_json(ROUND3[0], f"{ROUND3[1]}/raw_responses.json")}
    changed = [q for q in new if old[q]["route_used"] != new[q]["route_used"]]
    legacy_changed = [q for q in changed if int(q.rsplit("_", 1)[1]) <= 20]
    print(f"   route changes: {len(changed)}/500 ({len(legacy_changed)} among the original 100)")
    for (a, b), n in Counter((old[q]["route_used"], new[q]["route_used"])
                             for q in changed).most_common():
        print(f"      {a} -> {b}: {n}")
    for strategy in ("graph", "graph_event"):
        n_old = sum(strategy in x["strategies_used"] for x in old.values())
        n_new = sum(strategy in x["strategies_used"] for x in new.values())
        print(f"   '{strategy}' invoked: {n_old} -> {n_new}")
    m_old = read_json(JULY15[0], f"{JULY15[1]}/evaluation_results.json")["overall"]
    m_new = read_json(ROUND3[0], f"{ROUND3[1]}/evaluation_results.json")["overall"]
    for k in ("verse_recall_at_k", "anchor_coverage_at_k", "hit_rate"):
        print(f"   {k}: {m_old[k]:.4f} -> {m_new[k]:.4f}")


if __name__ == "__main__":
    main()

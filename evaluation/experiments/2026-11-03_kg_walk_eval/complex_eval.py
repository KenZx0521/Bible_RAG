#!/usr/bin/env python3
"""The walk and the kinship card on the complex-relation questions (NEW82, OLD31), at the answer.

Arms, all on the same backend, image and build:
  G   no override: event_registry, graph_walk, kin_card (the main architecture)
  N   graph_strategies=[event_registry]: the same flow without the walk and the card
  N2  N again: what two runs of the same arm differ by
  S   semantic_only

Both sets were already seen when the graph was designed, so this is a development number.

From evaluation/, with BACKEND_URL set to the backend under test:
  .venv/bin/python experiments/2026-11-03_kg_walk_eval/complex_eval.py collect --out DIR
  .venv/bin/python experiments/2026-11-03_kg_walk_eval/complex_eval.py judge --out DIR
  .venv/bin/python experiments/2026-11-03_kg_walk_eval/complex_eval.py report --out DIR
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import httpx
import numpy as np
from scipy import stats

EVAL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EVAL_ROOT))

from src.config import settings  # noqa: E402
from src.metrics.coverage_eval import compute_coverage  # noqa: E402
from src.models import EvalSample, GroundTruthItem  # noqa: E402
from src.rag_client import NO_KEEPALIVE, parse_sources, query_rag  # noqa: E402
from src.slot_coverage import keyed_slots, load_verse_index  # noqa: E402

MULTIHOP = Path("/mnt/ollama-data/bible_rag_store/reports/multihop_kg_20261012/session_e73fd5d9")
NEW82_FILE = MULTIHOP / "newq/questions_v5.json"
OLD31_FILE = MULTIHOP / "multihop/synth/usable.json"
OLD31_API = MULTIHOP / "reenable/api_arms.json"
CONTRACTS = settings.rag_store / "contracts"

ARMS: dict[str, dict[str, Any]] = {
    "G": {"use_graph": True},
    "G2": {"use_graph": True},
    "N": {"use_graph": True, "graph_strategies": ["event_registry"]},
    "N2": {"use_graph": True, "graph_strategies": ["event_registry"]},
    "S": {"semantic_only": True},
}
# The answers of one context differ run to run: the average of two runs of an arm halves that noise's variance.
AVERAGES = {"Gbar": ("G", "G2"), "Nbar": ("N", "N2")}
PAIRS = (("Gbar", "Nbar"), ("Gbar", "S"), ("G", "N"), ("G", "S"), ("N", "S"), ("N", "N2"), ("G", "G2"))
CATEGORY = {"KIN": "親屬", "DIS": "消歧", "DISAMBIG_MH": "消歧", "TO": "時序", "MH_TO": "時序"}
BOOTSTRAPS = 10_000
SEED = 20261103
REQUEST_TIMEOUT_S = 300.0
CONCURRENCY = 3


def load_questions() -> list[dict[str, Any]]:
    """NEW82 (questions_v5 without the rejected and deduplicated) then OLD31 (usable with m > 0)."""
    rows = []
    for q in json.loads(NEW82_FILE.read_text())["questions"]:
        if q["status"] == "reject" or q["reject_reason"] or q["dedup_drop"]:
            continue
        rows.append({"qid": q["id"], "set": "new82", "question": q["question"], "points": q["key_points"],
                     "hops": q["hop_slots"], "category": CATEGORY.get(q["category"], "多跳")})
    api = {r["id"]: r for r in json.loads(OLD31_API.read_text())}
    for q in json.loads(OLD31_FILE.read_text()):
        if int(api[q["id"]]["m"]) <= 0:
            continue
        points = [s.strip() for s in re.split(r"[。；]", q["answer"]) if s.strip()]
        rows.append({"qid": q["id"], "set": "old31", "question": q["question"], "points": points,
                     "hops": q["hop_slots"], "category": CATEGORY.get(q["id"].rsplit("_", 1)[0], "多跳")})
    assert len(rows) == 113, len(rows)
    return rows


def _done(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return {r["qid"]: r for r in rows}


async def _ask(q: dict[str, Any], arm: str, client: httpx.AsyncClient) -> dict[str, Any]:
    resp = await query_rag(q["question"], client=client, **ARMS[arm])
    stats_ = resp.get("retrieval_stats") or {}
    return {"qid": q["qid"], "arm": arm, "answer": resp.get("answer", ""), "sources": resp.get("sources", []),
            "graph_trace": resp.get("graph_trace"), "aux_card": resp.get("aux_card"),
            "route": stats_.get("route_used"), "strategies": stats_.get("strategies_used"),
            "errors": stats_.get("strategy_errors"), "walk": stats_.get("graph_walk"),
            "kin": stats_.get("kin_card"), "intent": resp.get("intent")}


async def collect(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    questions = load_questions()
    health = httpx.get(f"{settings.backend_url}/api/v1/health", timeout=30).json()
    (out / "health.json").write_text(json.dumps(health, ensure_ascii=False, indent=1))
    gate = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, limits=NO_KEEPALIVE) as client:
        async def one(q: dict[str, Any], arm: str, path: Path) -> None:
            async with gate:
                row = await _ask(q, arm, client)
            async with lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

        for arm in ARMS:
            path = out / f"{arm}.jsonl"
            have = _done(path)
            todo = [q for q in questions if q["qid"] not in have]
            print(f"{arm}: {len(todo)} to ask, {len(have)} kept", flush=True)
            results = await asyncio.gather(*(one(q, arm, path) for q in todo), return_exceptions=True)
            failed = [(q["qid"], repr(r)) for q, r in zip(todo, results) if isinstance(r, Exception)]
            if failed:
                print(f"{arm}: {len(failed)} failed, run again to finish: {failed[:3]}", flush=True)


def _sample(q: dict[str, Any], row: dict[str, Any]) -> EvalSample:
    item = GroundTruthItem(question_id=q["qid"], question=q["question"], question_type=q["category"],
                           book_name="", expected_answer_points=q["points"])
    return EvalSample(question_id=q["qid"], question=q["question"], question_type=q["category"],
                      rag_answer=row["answer"], ground_truth=item)


def judge(out: Path) -> None:
    questions = load_questions()
    for arm in ARMS:
        target = out / f"{arm}.scores.json"
        if target.exists():
            print(f"{arm}: scores kept", flush=True)
            continue
        rows = _done(out / f"{arm}.jsonl")
        missing = [q["qid"] for q in questions if q["qid"] not in rows]
        if missing:
            raise SystemExit(f"{arm}: {len(missing)} questions not collected, first {missing[:3]}")
        results, outcomes = compute_coverage([_sample(q, rows[q["qid"]]) for q in questions])
        invalid = [qid for qid, r in results.items() if not r[0].valid]
        if invalid:
            raise SystemExit(f"{arm}: judge left {len(invalid)} invalid, first {invalid[:3]}; nothing saved")
        target.write_text(json.dumps(
            {qid: {"coverage": r[0].value, "points": outcomes[qid].points} for qid, r in results.items()},
            ensure_ascii=False, indent=1, default=str))


def _hops_hit(q: dict[str, Any], row: dict[str, Any], grid: Any) -> list[bool]:
    held: set[str] = set()
    for source in parse_sources(row["sources"]):
        held |= keyed_slots(grid, source)
    return [bool(held.intersection(hop)) for hop in q["hops"]]


def _paired(a: Iterable[float], b: Iterable[float]) -> dict[str, Any]:
    diff = np.asarray(list(a), float) - np.asarray(list(b), float)
    n = len(diff)
    if n == 0:
        return {"n": 0}
    rng = np.random.default_rng(SEED)
    means = diff[rng.integers(0, n, (BOOTSTRAPS, n))].mean(axis=1)
    wins, losses = int((diff > 0).sum()), int((diff < 0).sum())
    sign_p = float(stats.binomtest(wins, wins + losses, 0.5).pvalue) if wins + losses else 1.0
    wilcoxon_p = float(stats.wilcoxon(diff[diff != 0]).pvalue) if wins + losses else 1.0
    return {"n": n, "mean_diff": round(float(diff.mean()), 4),
            "ci95": [round(float(np.quantile(means, q)), 4) for q in (0.025, 0.975)],
            "win": wins, "loss": losses, "tie": n - wins - losses,
            "sign_p": round(sign_p, 4), "wilcoxon_p": round(wilcoxon_p, 4)}


def _source_ids(row: dict[str, Any]) -> list[str]:
    return [s["id"] for s in row["sources"]]


def report(out: Path) -> None:
    questions = load_questions()
    build = json.loads((out / "health.json").read_text())["build_id"]
    grid = load_verse_index(CONTRACTS / build, build)
    rows = {arm: _done(out / f"{arm}.jsonl") for arm in ARMS}
    scores = {arm: json.loads((out / f"{arm}.scores.json").read_text()) for arm in ARMS}
    cov = {arm: {qid: s["coverage"] for qid, s in scores[arm].items()} for arm in ARMS}
    hit = {arm: {q["qid"]: _hops_hit(q, rows[arm][q["qid"]], grid) for q in questions} for arm in ARMS}
    hop_recall = {arm: {qid: sum(h) / len(h) for qid, h in hit[arm].items()} for arm in ARMS}
    all_hops = {arm: {qid: float(all(h)) for qid, h in hit[arm].items()} for arm in ARMS}

    groups: dict[str, list[dict[str, Any]]] = {"all": questions}
    for field in ("set", "category"):
        for value in sorted({q[field] for q in questions}):
            groups[f"{field}={value}"] = [q for q in questions if q[field] == value]
    changed = [q for q in questions if _source_ids(rows["G"][q["qid"]]) != _source_ids(rows["N"][q["qid"]])]
    carded = [q for q in questions if (rows["G"][q["qid"]].get("aux_card") or {}).get("kind") == "kin"]
    groups["G_top_k_differs_from_N"] = changed
    groups["G_has_kin_card"] = carded
    groups["G_same_top_k_and_no_kin_card"] = [
        q for q in questions if q not in changed and q not in carded]
    groups["G_touched"] = [q for q in questions if q in changed or q in carded]

    def table(by_arm: dict[str, dict[str, float]]) -> dict[str, Any]:
        averaged = {name: {qid: (by_arm[a][qid] + by_arm[b][qid]) / 2 for qid in by_arm[a]}
                    for name, (a, b) in AVERAGES.items()}
        metric = {**by_arm, **averaged}
        result = {}
        for name, members in groups.items():
            means = {arm: round(float(np.mean([metric[arm][q["qid"]] for q in members])), 4) if members else None
                     for arm in metric}
            pairs = {f"{a}-{b}": _paired((metric[a][q["qid"]] for q in members),
                                         (metric[b][q["qid"]] for q in members)) for a, b in PAIRS}
            result[name] = {"n": len(members), "means": means, "pairs": pairs}
        return result

    usage = {
        "routes": _count(rows["G"][q["qid"]]["route"] for q in questions),
        "walk_ok": sum(_walk_ok(rows["G"][q["qid"]]) for q in questions),
        "walk_skips": _count((rows["G"][q["qid"]].get("walk") or {}).get("skip_reason") for q in questions),
        "kin_skips": _count((rows["G"][q["qid"]].get("kin") or {}).get("skip_reason") for q in questions),
        "kin_cards": len(carded),
        "top_k_differs_from_N": len(changed),
        "new_passages_in_top_k": sum(_walk_new(rows["G"][q["qid"]]) for q in questions),
    }
    doc = {"backend_build": build, "usage": usage, "answer_coverage": table(cov),
           "hop_recall": table(hop_recall), "all_hops_hit": table(all_hops)}
    (out / "report.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(json.dumps({"usage": usage, "answer_coverage": doc["answer_coverage"]}, ensure_ascii=False, indent=1))


def _count(values: Iterable[Any]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for value in values:
        tally[str(value)] = tally.get(str(value), 0) + 1
    return tally


def _walk_ok(row: dict[str, Any]) -> bool:
    """The walk reached Neo4j and came back. A walk record alone may only say why it was skipped."""
    walk = row.get("walk") or {}
    return bool(walk.get("n_cypher")) and not walk.get("skip_reason")


def _walk_new(row: dict[str, Any]) -> int:
    ops = row.get("graph_trace") or []
    return sum(len(op.get("passages") or []) for op in ops if op.get("op") == "graph_walk")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("collect", "judge", "report"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.step == "collect":
        asyncio.run(collect(args.out))
    elif args.step == "judge":
        judge(args.out)
    else:
        report(args.out)


if __name__ == "__main__":
    main()

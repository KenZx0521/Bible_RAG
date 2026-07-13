#!/usr/bin/env python3
"""Fast retrieval-only eval loop (no answer generation, no RAGAS).

Collects top-k sources for all ground-truth questions via the backend's
``retrieval_only`` mode and computes the same 7 retrieval metrics as the full
pipeline (src.metrics.retrieval — identical reference parsing and relevance
judging, so numbers are directly comparable with results_graph/ runs).

Also recomputes metrics from an existing raw_responses.json for baseline
comparison (--from-raw), so P0-era runs can be scored with byte-identical
metric code.

Usage (from evaluation/):
    uv run python quick_retrieval_eval.py --label fixes_a03            # live run
    uv run python quick_retrieval_eval.py --alpha 0.0 --label alpha0   # sweep point
    uv run python quick_retrieval_eval.py --from-raw results_graph/raw_responses.json --label p0_baseline
    uv run python quick_retrieval_eval.py --compare out_a.json out_b.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import settings  # noqa: E402
from src.data_loader import load_ground_truth  # noqa: E402
from src.models import EvalSample, SourceInfo  # noqa: E402
from src.metrics.retrieval import compute_retrieval_metrics  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parent / "results_quick"

# verse_recall / anchor_coverage first — the honest readouts. hit_rate and
# recall_at_k are unit-level (inflated for chapter ranges), kept for
# comparability with historical runs.
_METRIC_ORDER = [
    "verse_recall_at_k", "anchor_coverage_at_k",
    "hit_rate", "recall_at_k", "ndcg_at_k", "mrr", "precision_at_k",
]


async def _query_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    gt,
    use_graph: bool | None,
    alpha: float | None,
    top_k: int,
) -> EvalSample:
    payload: dict = {
        "question": gt.question,
        "top_k": top_k,
        "include_sources": True,
        "retrieval_only": True,
    }
    if use_graph is not None:
        payload["use_graph"] = use_graph
    if alpha is not None:
        payload["fusion_alpha"] = alpha

    async with sem:
        resp = await client.post(f"{settings.backend_url}/api/v1/query", json=payload)
        resp.raise_for_status()
        data = resp.json()

    sources = [
        SourceInfo(
            id=s.get("id", ""),
            book=s.get("book", ""),
            chapter=s.get("chapter"),
            title=s.get("title", ""),
            verse_range=s.get("verse_range", ""),
            score=s.get("score"),
        )
        for s in data.get("sources", [])
    ]
    stats = data.get("retrieval_stats", {})
    return EvalSample(
        question_id=gt.question_id,
        question=gt.question,
        question_type=gt.question_type,
        sources=sources,
        ground_truth=gt,
        route_used=stats.get("route_used", ""),
        strategies_used=stats.get("strategies_used", []),
        strategy_errors=stats.get("strategy_errors", {}),
    ), [
        {"id": s.get("id"), "strategy": s.get("strategy"), "score": s.get("score"),
         "rerank_score": s.get("rerank_score")}
        for s in data.get("sources", [])
    ]


async def collect(use_graph, alpha, top_k, concurrency, only_prefix) -> tuple[list[EvalSample], dict]:
    gts = load_ground_truth()
    if only_prefix:
        gts = [g for g in gts if g.question_id.startswith(tuple(only_prefix))]
    sem = asyncio.Semaphore(concurrency)
    raw_sources: dict[str, list] = {}
    async with httpx.AsyncClient(timeout=180.0) as client:
        tasks = [_query_one(client, sem, gt, use_graph, alpha, top_k) for gt in gts]
        out = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            sample, srcs = await coro
            out.append(sample)
            raw_sources[sample.question_id] = srcs
            done += 1
            if done % 20 == 0:
                print(f"  collected {done}/{len(gts)}")
    order = {g.question_id: i for i, g in enumerate(gts)}
    out.sort(key=lambda s: order[s.question_id])
    return out, raw_sources


def samples_from_raw(path: Path) -> list[EvalSample]:
    """Rebuild EvalSamples from a full-pipeline raw_responses.json."""
    gts = {g.question_id: g for g in load_ground_truth()}
    data = json.loads(path.read_text())
    samples: list[EvalSample] = []
    for item in data:
        gt = gts.get(item["question_id"])
        if gt is None:
            continue
        samples.append(EvalSample(
            question_id=item["question_id"],
            question=item["question"],
            question_type=gt.question_type,
            sources=[SourceInfo(**s) for s in item.get("sources", [])],
            ground_truth=gt,
            route_used=item.get("route_used", ""),
            strategies_used=item.get("strategies_used", []),
            strategy_errors=item.get("strategy_errors", {}),
        ))
    return samples


def aggregate(samples: list[EvalSample], k: int) -> dict:
    per_q = compute_retrieval_metrics(samples, k=k)
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall: dict[str, list[float]] = defaultdict(list)
    per_question: dict[str, dict[str, float]] = {}
    qtype: dict[str, str] = {}
    for s in samples:
        vals = {m.name: m.value for m in per_q[s.question_id]}
        per_question[s.question_id] = {
            **vals,
            "route": s.route_used,
            "strategies": s.strategies_used,
            "sources": [src.id for src in s.sources],
        }
        qtype[s.question_id] = s.question_type
        for name, v in vals.items():
            overall[name].append(v)
            by_type[s.question_type][name].append(v)
    return {
        "overall": {n: round(sum(v) / len(v), 4) for n, v in overall.items()},
        "by_type": {
            t: {n: round(sum(v) / len(v), 4) for n, v in ms.items()}
            for t, ms in sorted(by_type.items())
        },
        "n": len(samples),
        "per_question": per_question,
    }


def _fmt(ms: dict, m: str) -> str:
    v = ms.get(m)
    return f"{v:.3f}" if v is not None else "n/a"


def print_table(agg: dict, label: str) -> None:
    print(f"\n=== {label} (n={agg['n']}) ===")
    header = "type".ljust(16) + "".join(
        m.replace("_at_k", "@5").replace("verse_recall", "vrec").replace("anchor_coverage", "anch").ljust(11)
        for m in _METRIC_ORDER
    )
    print(header)
    for t, ms in agg["by_type"].items():
        print(t.ljust(16) + "".join(_fmt(ms, m).ljust(11) for m in _METRIC_ORDER))
    print("OVERALL".ljust(16) + "".join(_fmt(agg["overall"], m).ljust(11) for m in _METRIC_ORDER))


def compare(path_a: Path, path_b: Path) -> None:
    a = json.loads(path_a.read_text())
    b = json.loads(path_b.read_text())
    print(f"\n=== Δ ({path_b.name} − {path_a.name}) ===")
    for t in sorted(set(a["by_type"]) | set(b["by_type"])):
        cells = []
        for m in _METRIC_ORDER:
            va = a["by_type"].get(t, {}).get(m)
            vb = b["by_type"].get(t, {}).get(m)
            cells.append(f"{vb - va:+.3f}" if va is not None and vb is not None else "  n/a")
        print(t.ljust(16) + "".join(c.ljust(11) for c in cells))
    cells = []
    for m in _METRIC_ORDER:
        va, vb = a["overall"].get(m), b["overall"].get(m)
        cells.append(f"{vb - va:+.3f}" if va is not None and vb is not None else "  n/a")
    print("OVERALL".ljust(16) + "".join(c.ljust(11) for c in cells))

    pa, pb = a.get("per_question", {}), b.get("per_question", {})
    moved = []
    for qid in pa.keys() & pb.keys():
        d = pb[qid]["hit_rate"] - pa[qid]["hit_rate"]
        if abs(d) >= 0.5:
            moved.append((qid, d))
    if moved:
        print("\nhit_rate flips:")
        for qid, d in sorted(moved):
            print(f"  {'▲' if d > 0 else '▼'} {qid} ({d:+.0f})")

    vr_moved = []
    for qid in pa.keys() & pb.keys():
        va, vb = pa[qid].get("verse_recall_at_k"), pb[qid].get("verse_recall_at_k")
        if va is not None and vb is not None and abs(vb - va) >= 0.3:
            vr_moved.append((qid, vb - va))
    if vr_moved:
        print("\nverse_recall movers (|Δ|≥0.3):")
        for qid, d in sorted(vr_moved, key=lambda x: -abs(x[1])):
            print(f"  {'▲' if d > 0 else '▼'} {qid} ({d:+.3f})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="run")
    parser.add_argument("--alpha", type=float, default=None,
                        help="fusion_alpha override (omit = backend default)")
    parser.add_argument("--use-graph", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--only", nargs="*", default=None,
                        help="question_id prefixes to include (e.g. EVENT PERSON)")
    parser.add_argument("--from-raw", type=Path, default=None,
                        help="score an existing raw_responses.json instead of live collection")
    parser.add_argument("--compare", nargs=2, type=Path, default=None,
                        help="diff two saved result JSONs")
    args = parser.parse_args()

    if args.compare:
        compare(args.compare[0], args.compare[1])
        return 0

    if args.from_raw:
        samples = samples_from_raw(args.from_raw)
        raw_sources = None
    else:
        samples, raw_sources = asyncio.run(
            collect(args.use_graph, args.alpha, args.top_k, args.concurrency, args.only)
        )

    agg = aggregate(samples, k=args.top_k)
    if raw_sources:
        for qid, srcs in raw_sources.items():
            if qid in agg["per_question"]:
                agg["per_question"][qid]["source_detail"] = srcs
    print_table(agg, args.label)

    _OUT_DIR.mkdir(exist_ok=True)
    out = _OUT_DIR / f"{args.label}.json"
    out.write_text(json.dumps(agg, ensure_ascii=False, indent=2))
    print(f"\nsaved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Fast retrieval-only eval loop (no answer generation, no RAGAS).

Collects top-k sources for all ground-truth questions via the backend's
``retrieval_only`` mode and computes the same 7 retrieval metrics as the full
pipeline (src.metrics.retrieval — identical reference parsing and relevance
judging, so numbers are directly comparable with results_graph/ runs). Round 3's
results_graph/ ran every graph strategy; since 2026-10 the backend default is
graph_event only, so compare against it with --graph-strategies all. Each run
records the strategies the backend actually applied under "config".

Also recomputes metrics from an existing raw_responses.json for baseline
comparison (--from-raw), so P0-era runs can be scored with byte-identical
metric code.

Usage (from evaluation/):
    uv run python quick_retrieval_eval.py --label fixes_a03            # live run
    uv run python quick_retrieval_eval.py --alpha 0.0 --label alpha0   # sweep point
    uv run python quick_retrieval_eval.py --graph-strategies all --label all_graph  # strategy A/B
    uv run python quick_retrieval_eval.py --graph-strategies graph_event graph_person --label ev_person
    uv run python quick_retrieval_eval.py --graph-strategies --label none  # no graph strategy
    uv run python quick_retrieval_eval.py --from-raw results_graph/raw_responses.json --label p0_baseline
    uv run python quick_retrieval_eval.py --compare out_a.json out_b.json
    # auxiliary arm (event_registry appends after top-5) and its k-aligned controls
    uv run python quick_retrieval_eval.py --graph-strategies event_registry --metric-k 6 --label aux
    uv run python quick_retrieval_eval.py --no-use-graph --metric-k 6 --label dense5
    uv run python quick_retrieval_eval.py --no-use-graph --top-k 6 --metric-k 6 \
        --ids-file touched.txt --label dense6        # then: ab_compare.py

Each question's source_detail records every passage's provenance (strategy,
found_by) and whether it overlaps the gold reference, for ab_compare.py's
change ledger. Infrastructure failures (no sources + a strategy error) are
flagged invalid and left out of the averages.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import settings  # noqa: E402
from src.data_loader import load_ground_truth  # noqa: E402
from src.models import EvalSample, SourceInfo  # noqa: E402
from src.metrics.retrieval import compute_retrieval_metrics  # noqa: E402
from src.reference_parser import parse_reference  # noqa: E402
from src.relevance_judge import binary_relevance  # noqa: E402
from src.validity import is_infra_failure  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parent / "results_quick"

# Code that turns sources + reference into metric values; its hash is stored
# in every run so ab_compare refuses to pair runs scored differently (e.g.
# before/after the GENERAL_043 reference-parser fix).
_METRIC_CODE = [
    Path(__file__).resolve().parent / "src" / name
    for name in ("reference_parser.py", "verse_coverage.py", "relevance_judge.py",
                 "metrics/retrieval.py")
]


def metric_version() -> str:
    digest = hashlib.sha256()
    for path in _METRIC_CODE:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]

# verse_recall / anchor_coverage first — the honest readouts. hit_rate and
# recall_at_k are unit-level (inflated for chapter ranges), kept for
# comparability with historical runs.
_METRIC_ORDER = [
    "verse_recall_at_k", "anchor_coverage_at_k",
    "hit_rate", "recall_at_k", "ndcg_at_k", "mrr", "precision_at_k",
]


def applied_graph_strategies(requested: list[str] | None, stats: dict) -> list[str] | None:
    """Graph strategies the backend reports it applied, checked against the request.

    Raises when an explicit request was not honoured — a backend image built
    before `graph_strategies` existed drops the field silently, which would
    mislabel an A/B arm — or when the backend applied a different list.
    """
    applied = stats.get("graph_strategies")
    if requested is None:
        return applied
    if applied is None:
        raise RuntimeError(
            "backend did not report graph_strategies; rebuild it "
            "(docker compose up -d --build backend) before an A/B run"
        )
    wanted = sorted(set(requested))
    if stats.get("use_graph", True) and "all" not in requested and applied != wanted:
        raise RuntimeError(f"backend applied graph_strategies {applied}, requested {wanted}")
    return applied


async def _query_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    gt,
    use_graph: bool | None,
    alpha: float | None,
    top_k: int,
    graph_strategies: list[str] | None = None,
) -> tuple[EvalSample, list[dict], list[str] | None]:
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
    if graph_strategies is not None:
        payload["graph_strategies"] = graph_strategies

    async with sem:
        resp = await client.post(f"{settings.backend_url}/api/v1/query", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"{gt.question_id}: HTTP {resp.status_code} {resp.text[:300]}")
        data = resp.json()

    sources = [
        SourceInfo(
            id=s.get("id", ""),
            book=s.get("book", ""),
            chapter=s.get("chapter"),
            title=s.get("title", ""),
            verse_range=s.get("verse_range", ""),
            score=s.get("score"),
            strategy=s.get("strategy"),
        )
        for s in data.get("sources", [])
    ]
    stats = data.get("retrieval_stats", {})
    applied = applied_graph_strategies(graph_strategies, stats)
    sample = EvalSample(
        question_id=gt.question_id,
        question=gt.question,
        question_type=gt.question_type,
        sources=sources,
        ground_truth=gt,
        route_used=stats.get("route_used", ""),
        strategies_used=stats.get("strategies_used", []),
        strategy_errors=stats.get("strategy_errors", {}),
    )
    extra = {"event_registry_events": stats.get("event_registry_events")}
    return sample, source_detail(sample, data.get("sources", [])), applied, extra


def source_detail(sample: EvalSample, api_sources: list[dict]) -> list[dict]:
    """Per-passage record: position-aligned API provenance + gold overlap."""
    gt_refs = parse_reference(sample.ground_truth.reference)
    return [
        {
            "id": src.id, "book": src.book, "chapter": src.chapter, "title": src.title,
            "verse_range": src.verse_range, "strategy": api.get("strategy"),
            "found_by": api.get("found_by"), "score": api.get("score"),
            "rerank_score": api.get("rerank_score"),
            "gold": bool(gt_refs) and binary_relevance(src, gt_refs),
        }
        for src, api in zip(sample.sources, api_sources)
    ]


def load_ids(path: Path) -> set[str]:
    """Question ids from a JSON list or one-id-per-line text file."""
    text = path.read_text(encoding="utf-8").strip()
    ids = json.loads(text) if text.startswith("[") else text.split()
    return {i.strip() for i in ids if i.strip()}


async def collect(use_graph, alpha, top_k, concurrency, only_prefix,
                  graph_strategies=None, ids: set[str] | None = None,
                  ) -> tuple[list[EvalSample], dict, dict, dict]:
    gts = load_ground_truth()
    if only_prefix:
        gts = [g for g in gts if g.question_id.startswith(tuple(only_prefix))]
    if ids is not None:
        unknown = sorted(ids - {g.question_id for g in gts})
        if unknown:
            raise ValueError(f"--ids-file names unknown question ids: {unknown}")
        gts = [g for g in gts if g.question_id in ids]
    sem = asyncio.Semaphore(concurrency)
    raw_sources: dict[str, list] = {}
    applied_by_q: dict[str, list[str] | None] = {}
    extra_by_q: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=180.0) as client:
        tasks = [_query_one(client, sem, gt, use_graph, alpha, top_k, graph_strategies)
                 for gt in gts]
        out = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            sample, srcs, applied, extra = await coro
            out.append(sample)
            raw_sources[sample.question_id] = srcs
            applied_by_q[sample.question_id] = applied
            extra_by_q[sample.question_id] = extra
            done += 1
            if done % 20 == 0:
                print(f"  collected {done}/{len(gts)}")
    order = {g.question_id: i for i, g in enumerate(gts)}
    out.sort(key=lambda s: order[s.question_id])
    return out, raw_sources, applied_by_q, extra_by_q


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
    """Metrics at k per question; averages skip infrastructure failures."""
    per_q = compute_retrieval_metrics(samples, k=k)
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall: dict[str, list[float]] = defaultdict(list)
    per_question: dict[str, dict[str, float]] = {}
    n_invalid = 0
    for s in samples:
        vals = {m.name: m.value for m in per_q[s.question_id]}
        invalid = is_infra_failure(s)
        per_question[s.question_id] = {
            **vals,
            "route": s.route_used,
            "strategies": s.strategies_used,
            "sources": [src.id for src in s.sources],
            "strategy_errors": s.strategy_errors,
            "invalid": invalid,
        }
        if invalid:
            n_invalid += 1
            continue
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
        "n_invalid": n_invalid,
        "per_question": per_question,
    }


def _fmt(ms: dict, m: str) -> str:
    v = ms.get(m)
    return f"{v:.3f}" if v is not None else "n/a"


def print_table(agg: dict, label: str, k: int = 5) -> None:
    print(f"\n=== {label} (n={agg['n']}) ===")
    header = "type".ljust(16) + "".join(
        m.replace("_at_k", f"@{k}").replace("verse_recall", "vrec").replace("anchor_coverage", "anch").ljust(11)
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
    excluded = sorted(q for q in pa.keys() & pb.keys()
                      if pa[q].get("invalid") or pb[q].get("invalid"))
    print(f"\nexcluded (invalid in either run): {excluded}"
          "  — by_type/overall above are per-run means, not paired; use ab_compare.py")
    common = (pa.keys() & pb.keys()) - set(excluded)
    moved = []
    for qid in common:
        d = pb[qid]["hit_rate"] - pa[qid]["hit_rate"]
        if abs(d) >= 0.5:
            moved.append((qid, d))
    if moved:
        print("\nhit_rate flips:")
        for qid, d in sorted(moved):
            print(f"  {'▲' if d > 0 else '▼'} {qid} ({d:+.0f})")

    vr_moved = []
    for qid in common:
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
    parser.add_argument("--graph-strategies", nargs="*", default=None,
                        help="graph strategies allowed to run (e.g. graph_event, or 'all'; "
                             "no values = none); omit = backend default")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--metric-k", type=int, default=None,
                        help="score the first N sources (default: --top-k); runs compared "
                             "with ab_compare.py must share it")
    parser.add_argument("--ids-file", type=Path, default=None,
                        help="only these question ids (JSON list or one per line)")
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

    applied_by_q: dict[str, list[str] | None] = {}
    if args.from_raw:
        if args.graph_strategies is not None:
            print("warning: --graph-strategies is ignored with --from-raw")
        samples = samples_from_raw(args.from_raw)
        raw_sources = None
    else:
        ids = load_ids(args.ids_file) if args.ids_file else None
        samples, raw_sources, applied_by_q, extra_by_q = asyncio.run(
            collect(args.use_graph, args.alpha, args.top_k, args.concurrency, args.only,
                    args.graph_strategies, ids)
        )

    metric_k = args.metric_k or args.top_k
    agg = aggregate(samples, k=metric_k)
    if raw_sources:
        for qid, srcs in raw_sources.items():
            if qid in agg["per_question"]:
                agg["per_question"][qid]["source_detail"] = srcs
                agg["per_question"][qid]["graph_strategies"] = applied_by_q.get(qid)
                agg["per_question"][qid].update(extra_by_q.get(qid, {}))
    applied_counts = Counter(
        "legacy (not reported)" if v is None else ",".join(v) or "(none)"
        for v in applied_by_q.values()
    )
    agg["config"] = {
        "from_raw": str(args.from_raw) if args.from_raw else None,
        "use_graph": args.use_graph,
        "fusion_alpha": args.alpha,
        "top_k": args.top_k,
        "metric_k": metric_k,
        "metric_version": metric_version(),
        "only": args.only,
        "ids_file": str(args.ids_file) if args.ids_file else None,
        "graph_strategies_requested": args.graph_strategies,
        "graph_strategies_applied": dict(applied_counts),
    }
    print_table(agg, args.label, k=metric_k)

    _OUT_DIR.mkdir(exist_ok=True)
    out = _OUT_DIR / f"{args.label}.json"
    out.write_text(json.dumps(agg, ensure_ascii=False, indent=2))
    print(f"\nsaved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Recompute every Round 3 number in the paper (sec6b_round3.tex).

Reads the three September 2026 evaluation archives
(evaluation/results_{graph,no_graph,semantic}/) and prints:

  1. overall / legacy-100 / expansion-400 means per configuration
  2. paired differences with 95% bootstrap CIs (fixed seed)
  3. per question type x family means
  4. the noise floor: questions whose contexts were byte-identical in the
     graph and no-graph runs (answer-side deltas = sampling + judge noise)
  5. the slot analysis: graph-route questions bucketed by how many top-5
     slots graph strategies hold, graph minus no-graph
  6. route statistics, hit flips, legacy misses, answer-correctness ceiling

Aggregates are plain means over valid samples, which reproduces the
`overall` / `by_type` / `by_family` blocks of evaluation_results.json
exactly; the script asserts this before printing anything.

Usage:  python3 paper/tools/round3_stats.py [--json OUT.json]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

EVAL_DIR = Path(__file__).resolve().parents[2] / "evaluation"
CONFIGS = ("graph", "no_graph", "semantic")
GRAPH_STRATEGIES = {
    "graph_person", "graph_event", "graph_place", "graph",
    "entity_query", "entity_path", "cross_ref_expand", "cross_reference",
}
METRICS = (
    "hit_rate", "recall_at_k", "verse_recall_at_k", "anchor_coverage_at_k",
    "mrr", "ndcg_at_k", "ragas_context_recall", "answer_coverage",
    "ragas_answer_correctness", "ragas_faithfulness",
    "ragas_faithfulness_strict", "ragas_answer_relevancy",
)
PAIRED_METRICS = (
    "hit_rate", "verse_recall_at_k", "anchor_coverage_at_k", "mrr",
    "ragas_context_recall", "answer_coverage", "ragas_answer_correctness",
    "ragas_faithfulness", "ragas_faithfulness_strict",
)
BOOTSTRAP_B = 10_000
SEED = 20260930
TRACE_QUESTIONS = ("EVENT_QUESTION_020", "PERSON_QUESTION_066", "GENERAL_BIBLE_QUESTION_048")
EPS = 1e-9  # coverage steps such as 1.0 - 0.8 are not exact in binary


def r3(x: float) -> str:
    """Round half up to 3 decimals, as printed in the paper."""
    return str(Decimal(repr(round(x, 10))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def load(config: str) -> tuple[dict, dict, dict]:
    d = EVAL_DIR / f"results_{config}"
    report = json.loads((d / "evaluation_results.json").read_text())
    samples = {}
    for s in report["samples"]:
        m = {x["name"]: (x["value"] if x.get("valid", True) else None)
             for x in s["metrics"]}
        samples[s["question_id"]] = {**s, "m": m}
    raw = {x["question_id"]: x
           for x in json.loads((d / "raw_responses.json").read_text())}
    return report, samples, raw


def mean_of(ev: dict, qids, metric: str):
    vals = [ev[q]["m"].get(metric) for q in qids]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def check_aggregates(report: dict, ev: dict) -> None:
    def close(mine, stored):
        return stored is None or mine is None or abs(round(mine, 4) - stored) < 1e-4
    qids = list(ev)
    for k in METRICS:
        assert close(mean_of(ev, qids, k)[0], report["overall"].get(k)), k
    for t, block in report["by_type"].items():
        qs = [q for q in qids if ev[q]["question_type"] == t]
        for k in METRICS:
            assert close(mean_of(ev, qs, k)[0], block.get(k)), (t, k)
    for f, block in report["by_family"].items():
        qs = [q for q in qids if ev[q]["family"] == f]
        for k in METRICS:
            assert close(mean_of(ev, qs, k)[0], block.get(k)), (f, k)


def paired_ci(ev_a: dict, ev_b: dict, qids, metric: str, rng) -> dict:
    pairs = [(ev_a[q]["m"].get(metric), ev_b[q]["m"].get(metric)) for q in qids]
    d = np.array([a - b for a, b in pairs if a is not None and b is not None])
    idx = rng.integers(0, len(d), size=(BOOTSTRAP_B, len(d)))
    boot = np.sort(d[idx].mean(axis=1))
    return {
        "n": int(len(d)), "mean": float(d.mean()),
        "lo": float(boot[int(0.025 * BOOTSTRAP_B)]),
        "hi": float(boot[int(0.975 * BOOTSTRAP_B) - 1]),
        "win": int((d > 1e-9).sum()), "loss": int((d < -1e-9).sum()),
    }


def source_ids(raw_item: dict) -> list[str]:
    return [s["id"] for s in raw_item["sources"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, help="also dump all numbers here")
    args = ap.parse_args()

    reports, ev, raw = {}, {}, {}
    for c in CONFIGS:
        reports[c], ev[c], raw[c] = load(c)
        check_aggregates(reports[c], ev[c])
    qids = list(ev["graph"])
    fam = {q: ev["graph"][q]["family"] for q in qids}
    typ = {q: ev["graph"][q]["question_type"] for q in qids}
    out: dict = {"meta": {c: reports[c]["meta"] for c in CONFIGS}}

    # Infrastructure failures: a configuration returned no source at all
    # because every strategy errored (not a retrieval decision).
    failures = sorted(q for q in qids for c in CONFIGS
                      if not raw[c][q]["sources"] and raw[c][q]["strategy_errors"])
    out["infrastructure_failures"] = {
        q: {c: raw[c][q]["strategy_errors"] for c in CONFIGS if raw[c][q]["strategy_errors"]}
        for q in failures}

    subsets = {
        "all": qids,
        "legacy": [q for q in qids if fam[q] == "legacy_head"],
        "expansion": [q for q in qids if fam[q] != "legacy_head"],
    }

    # 1. aggregate table
    out["aggregate"] = {
        s: {c: {k: mean_of(ev[c], qs, k)[0] for k in METRICS} for c in CONFIGS}
        for s, qs in subsets.items()}
    print("== 1. means (aggregate archives include infrastructure failures)")
    for s, block in out["aggregate"].items():
        print(f"-- {s} (n={len(subsets[s])})")
        for k in METRICS:
            print(f"   {k:27s}" + "".join(f"{r3(block[c][k]):>8s}" for c in CONFIGS))

    # 2. paired contrasts, infrastructure failures excluded
    rng = np.random.default_rng(SEED)
    clean = {s: [q for q in qs if q not in failures] for s, qs in subsets.items()}
    out["paired"] = {}
    print(f"\n== 2. paired differences, 95% bootstrap CI (B={BOOTSTRAP_B}, "
          f"seed={SEED}; excluded: {failures})")
    for a, b in (("graph", "no_graph"), ("no_graph", "semantic"), ("graph", "semantic")):
        for s, qs in clean.items():
            for k in PAIRED_METRICS:
                r = paired_ci(ev[a], ev[b], qs, k, rng)
                out["paired"][f"{a}-{b}|{s}|{k}"] = r
                print(f"   {a:>8}-{b:<8} {s:9s} {k:27s} n={r['n']:3d} "
                      f"{r['mean']:+.3f} [{r['lo']:+.3f}, {r['hi']:+.3f}] "
                      f"W/L {r['win']}/{r['loss']}")

    # 3. type x family
    groups = defaultdict(list)
    for q in qids:
        groups[(typ[q], "ALL")].append(q)
        groups[(typ[q], fam[q])].append(q)
    out["type_family"] = {}
    print("\n== 3. type x family (hit, verse recall, anchor coverage, coverage)")
    for key in sorted(groups):
        qs = groups[key]
        row = {c: {k: mean_of(ev[c], qs, k)[0] for k in
                   ("hit_rate", "verse_recall_at_k", "anchor_coverage_at_k",
                    "answer_coverage")} for c in CONFIGS}
        out["type_family"]["|".join(key)] = {"n": len(qs), **row}
        print(f"   {key[0]:23s} {key[1]:21s} n={len(qs):3d} " + " | ".join(
            " ".join(r3(row[c][k]) for c in CONFIGS)
            for k in ("hit_rate", "verse_recall_at_k", "anchor_coverage_at_k",
                      "answer_coverage")))

    # 4. noise floor
    same_ctx = [q for q in qids if raw["graph"][q]["sources"]
                and raw["graph"][q]["contexts"] == raw["no_graph"][q]["contexts"]]
    out["noise_floor"] = {"n": len(same_ctx), "routes": Counter(
        raw["graph"][q]["route_used"] for q in same_ctx)}
    print(f"\n== 4. noise floor: {len(same_ctx)} questions with identical contexts "
          f"in graph and no-graph runs; routes {dict(out['noise_floor']['routes'])}")
    for k in ("answer_coverage", "ragas_answer_correctness", "ragas_faithfulness",
              "ragas_faithfulness_strict", "ragas_context_recall"):
        d = np.array([ev["graph"][q]["m"][k] - ev["no_graph"][q]["m"][k] for q in same_ctx
                      if ev["graph"][q]["m"].get(k) is not None
                      and ev["no_graph"][q]["m"].get(k) is not None])
        ge = float((np.abs(d) >= 0.2 - EPS).mean())
        out["noise_floor"][k] = {"n": int(len(d)), "mean": float(d.mean()),
                                 "mean_abs": float(np.abs(d).mean()), "sd": float(d.std()),
                                 "frac_ge_0.2": ge}
        print(f"   {k:27s} meanΔ {d.mean():+.4f}  mean|Δ| {np.abs(d).mean():.4f}  "
              f"sd {d.std():.4f}  |Δ|>=0.2: {ge:.3f}")

    # 5. slot analysis
    def graph_slots(q):
        return sum(1 for s in raw["graph"][q]["sources"] if s["strategy"] in GRAPH_STRATEGIES)
    graph_route_qs = [q for q in qids if q not in failures
                      and raw["graph"][q]["route_used"] == raw["no_graph"][q]["route_used"]
                      and raw["graph"][q]["route_used"] in ("R3", "R4", "R5", "R6")]
    out["slots"] = {}
    zero = [q for q in graph_route_qs if graph_slots(q) == 0]
    zero_same = sum(raw["graph"][q]["contexts"] == raw["no_graph"][q]["contexts"] for q in zero)
    out["slots_zero_identical_contexts"] = {"n": len(zero), "identical": zero_same}
    print(f"\n== 5. slot analysis ({len(graph_route_qs)} questions on the same R3-R6 route in both "
          f"runs), graph - no-graph; zero-slot questions with byte-identical contexts: "
          f"{zero_same}/{len(zero)}")
    for scope, flt in (("all", lambda q: True), ("expansion", lambda q: fam[q] != "legacy_head"),
                       ("legacy", lambda q: fam[q] == "legacy_head")):
        for k in range(6):
            qs = [q for q in graph_route_qs if graph_slots(q) == k and flt(q)]
            if not qs:
                continue
            row = {m: float(np.mean([ev["graph"][q]["m"][m] - ev["no_graph"][q]["m"][m] for q in qs]))
                   for m in ("hit_rate", "verse_recall_at_k", "anchor_coverage_at_k", "answer_coverage")}
            out["slots"][f"{scope}|{k}"] = {"n": len(qs), **row}
            print(f"   {scope:9s} slots={k} n={len(qs):3d} " +
                  " ".join(f"{m[:6]} {v:+.3f}" for m, v in row.items()))

    # 6. routes, flips, misses, correctness ceiling
    print("\n== 6. routes / flips / misses")
    for c in ("graph", "no_graph"):
        print(f"   route distribution {c}: all {dict(Counter(raw[c][q]['route_used'] for q in qids))}"
              f"; legacy {dict(Counter(raw[c][q]['route_used'] for q in subsets['legacy']))}")
    diff_route = [q for q in qids if raw["graph"][q]["route_used"] != raw["no_graph"][q]["route_used"]]
    print(f"   graph vs no-graph route disagreement: {len(diff_route)} questions")
    by_route = {}
    for scope in ("all", "expansion"):
        for r in ("R1", "R2", "R3", "R4", "R5", "R6", "fallback"):
            qs = [q for q in qids if q not in failures and raw["graph"][q]["route_used"] == r
                  and raw["no_graph"][q]["route_used"] == r
                  and (scope == "all" or fam[q] != "legacy_head")]
            if qs:
                by_route[f"{scope}|{r}"] = {"n": len(qs), **{
                    c: {m: mean_of(ev[c], qs, m)[0] for m in ("verse_recall_at_k", "answer_coverage")}
                    for c in ("graph", "no_graph")}}
                b = by_route[f"{scope}|{r}"]
                print(f"   {scope:9s} {r:8s} n={len(qs):3d} vrec {b['graph']['verse_recall_at_k']:.3f}/"
                      f"{b['no_graph']['verse_recall_at_k']:.3f}  cov {b['graph']['answer_coverage']:.3f}/"
                      f"{b['no_graph']['answer_coverage']:.3f}")
    out["by_route"] = by_route
    flips = {"graph_only": [], "no_graph_only": []}
    for q in qids:
        a, b = ev["graph"][q]["m"]["hit_rate"], ev["no_graph"][q]["m"]["hit_rate"]
        if a > b:
            flips["graph_only"].append(q)
        elif b > a:
            flips["no_graph_only"].append(q)
    out["hit_flips"] = flips
    print(f"   hit flips graph-only {len(flips['graph_only'])}: {flips['graph_only']}")
    print(f"   hit flips no-graph-only {len(flips['no_graph_only'])}: {flips['no_graph_only']}")
    out["legacy_misses"] = {c: [q for q in subsets["legacy"] if ev[c][q]["m"]["hit_rate"] == 0]
                            for c in CONFIGS}
    for c in CONFIGS:
        print(f"   legacy misses {c}: {out['legacy_misses'][c]}")
    g = ev["graph"]
    good = [q for q in qids if g[q]["m"]["answer_coverage"] >= 0.8
            and g[q]["m"].get("ragas_answer_correctness") is not None]
    lens = np.array([len(raw["graph"][q]["rag_answer"]) for q in good], dtype=float)
    acs = np.array([g[q]["m"]["ragas_answer_correctness"] for q in good])
    top = [g[q]["m"]["ragas_answer_correctness"] for q in qids
           if g[q]["m"]["verse_recall_at_k"] >= 0.9 and g[q]["m"]["answer_coverage"] >= 0.8
           and g[q]["m"].get("ragas_answer_correctness") is not None]
    out["correctness"] = {"n_cov_ge_0.8": len(good), "r_len_ac": float(np.corrcoef(lens, acs)[0, 1]),
                          "n_ceiling": len(top), "ceiling_mean": float(np.mean(top))}
    print(f"   graph: r(answer length, correctness | coverage>=0.8, n={len(good)}) = "
          f"{out['correctness']['r_len_ac']:+.3f}; correctness mean where verse recall>=0.9 "
          f"and coverage>=0.8 (n={len(top)}) = {out['correctness']['ceiling_mean']:.3f}")

    # 7. faithfulness gate per run and per question type; trace questions
    gate = {}
    for c in CONFIGS:
        per_type = {t: mean_of(ev[c], [q for q in qids if typ[q] == t],
                               "ragas_faithfulness_strict")[0] for t in sorted(set(typ.values()))}
        gate[c] = {"run": mean_of(ev[c], qids, "ragas_faithfulness_strict")[0],
                   "min_type": min(per_type.values()), "per_type": per_type}
        print(f"   strict gate {c}: run {gate[c]['run']:.4f} (>=0.97), "
              f"lowest type {gate[c]['min_type']:.4f} (>=0.95)")
    out["faithfulness_gate"] = gate
    print("\n== 7. traces (id, strategy, fused score, title)")
    for q in TRACE_QUESTIONS:
        for c in ("graph", "no_graph"):
            print(f"   {q} {c:8s} {raw[c][q]['route_used']:8s} " + "; ".join(
                f"{s['id']} {s['strategy']} {s['score']:.3f} {s['title']}"
                for s in raw[c][q]["sources"]))

    if args.json:
        args.json.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=dict))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()

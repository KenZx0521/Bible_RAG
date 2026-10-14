"""驗收 A of prereg §3 (NEW82): run the arms.py CLI three times and check its lists.

    accept_a.py [--out accept/accept_a.json]

Runs ``arms.py --set new82 --vectors PN/encode_out.jsonl --overwrite`` three times:
PYTHONHASHSEED=0 → <store>/new82/lists.json (the official lists), PYTHONHASHSEED=1 →
lists_hashseed1.json, PYTHONHASHSEED=0 with one BLAS / OpenMP thread → lists_threads1.json.
Then checks (each one a row of accept_a.json; passed = all of them):

* A1  D[0:20], C, GD, G, L, LEXPRF equal every archived key of EV / AT prf_lists.json, 82/82;
* A2  S1 pool reach on the 102 stored missing hops: GD_DEGNORM reach 45 and question 11:3,
      GD and GD_DEGNORM equal FM/gd_hub.json;
* A3  the lists part is identical across the three runs (§10 決定性), and every run's meta
      pins the current scripts, vectors and question set;
* A4  the bip graph has the §3 size; the D5≈ input R20 equals PN/rr_d5_in.json and, with the
      archived PN/rr_d5_out.jsonl scores, gives the stored missing_rr (§4).

Pools < 30 and GD's top 10 at 40 vs 200 PPR iterations are reported, not checked. Reads
the store only (archived files through their pinned sha256); writes the three lists into
the store and accept_a.json here. Exit 0 when passed, 1 when a check fails, 2 on errors.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import _eval_metrics as M      # the D5≈ evaluate.py uses
import arms
import gd_common as gd

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
OUT_DIR = gd.OUT_ROOT / "new82"
VECTORS = gd.PN / "encode_out.jsonl"
SINGLE_THREAD = {k: "1" for k in gd.THREAD_ENV}
RUNS = {"hashseed0": (OUT_DIR / "lists.json", {"PYTHONHASHSEED": "0"}),
        "hashseed1": (OUT_DIR / "lists_hashseed1.json", {"PYTHONHASHSEED": "1"}),
        "threads1": (OUT_DIR / "lists_threads1.json", {"PYTHONHASHSEED": "0", **SINGLE_THREAD})}
ARCHIVED = (("D[0:20]", "ev", "d20"), ("D[0:20]", "at", "d20"), ("C", "ev", "ctrl_extra"),
            ("C", "at", "CTRL"), ("GD", "ev", "PPR_DENSEONLY"), ("G", "ev", "PPR_BIP"),
            ("G", "at", "PPR_BIP"), ("L", "ev", "BM25_Q"), ("L", "at", "BM25Q"),
            ("LEXPRF", "at", "LEXPRF"))
REACH_KEYS = ("reach", "graph_only", "dense_only", "q_w", "q_l")
BIP_SIZE = {"edges": 16616, "name_nodes": 2929, "passages": 2773}      # §3
PREREG_DEGNORM = {"reach": 45, "q_w": 11, "q_l": 3}                    # §3 驗收 A
STORED_MISSING = (102, 63)                                             # §4 (hops, questions)
LONG_ITERS = 200


class Checks:
    """Named expected / got rows; passed when every row matched."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def __call__(self, name: str, expected: Any, got: Any) -> bool:
        self.rows.append({"name": name, "expected": expected, "got": got, "pass": expected == got})
        return expected == got

    @property
    def passed(self) -> bool:
        return all(r["pass"] for r in self.rows)


def archived(path: Path) -> Any:
    return json.loads(gd.read_pinned(path, gd.ARCHIVE_SHA256[path]))


def run_arms(out: Path, env: Mapping[str, str]) -> float:
    cmd = [sys.executable, "-B", str(gd.EXP_DIR / "arms.py"), "--set", "new82", "--vectors",
           str(VECTORS), "--out", str(out), "--overwrite"]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env},
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise gd.GdError(f"arms.py exited {proc.returncode}: {proc.stderr.strip()[-400:]}")
    return round(time.perf_counter() - t0, 2)


def reach(qset: gd.QuestionSet, lists: Mapping[str, Mapping[str, list]], arm: str) -> dict[str, int]:
    """FM/gd_hub.py S1: per stored missing hop a = gold in D[0:20] ∪ extra, b = gold in D[0:30];
    question W:L compares the sums."""
    tot = graph_only = dense_only = wins = losses = 0
    for q in qset.questions:
        d30, extra = lists[q.qid]["D30"], set(lists[q.qid][arm])
        golds = gd.question_gold(q)
        sa = sb = 0
        for h in sorted(q.missing_hops):
            a, b = bool(golds[h] & (set(d30[:20]) | extra)), bool(golds[h] & set(d30))
            tot, graph_only, dense_only = tot + a, graph_only + (a and not b), dense_only + (b and not a)
            sa, sb = sa + a, sb + b
        wins, losses = wins + (sa > sb), losses + (sa < sb)
    return dict(zip(REACH_KEYS, (tot, graph_only, dense_only, wins, losses)))


def check_lists(ok: Checks, qset: gd.QuestionSet, lists: Mapping[str, Mapping[str, list]]) -> dict:
    """A1 and A2; returns the mismatching question ids per archived key."""
    refs = {"ev": archived(gd.EV / "prf_lists.json"), "at": archived(gd.AT / "prf_lists.json")}
    bad = {}
    for arm, src, key in ARCHIVED:
        miss = [q for q in qset.ids
                if (lists[q]["D30"][:20] if arm == "D[0:20]" else lists[q][arm]) != refs[src][q][key]]
        ok(f"A1 {arm} == {src.upper()}/prf_lists.json:{key}", "82/82", f"{82 - len(miss)}/82")
        if miss:
            bad[f"{arm}:{src}:{key}"] = miss
    hub = archived(gd.FM / "gd_hub.json")
    for arm in ("GD_DEGNORM", "GD"):
        got = reach(qset, lists, arm)
        ok(f"A2 {arm} S1 pool reach == FM/gd_hub.json", {k: hub[arm][k] for k in REACH_KEYS}, got)
        if arm == "GD_DEGNORM":
            ok("A2 GD_DEGNORM reach 45, question 11:3 (prereg §3)", PREREG_DEGNORM,
               {k: got[k] for k in PREREG_DEGNORM})
    ok("A2 stored missing hops / questions", list(STORED_MISSING),
       [sum(len(q.missing_hops) for q in qset.questions), sum(bool(q.missing_hops) for q in qset.questions)])
    return bad


def check_runs(ok: Checks, qset: gd.QuestionSet, docs: Mapping[str, dict]) -> None:
    """A3: identical lists across the runs; each meta pins the current files and the set."""
    first = docs["hashseed0"]["lists"]
    for name, doc in docs.items():
        meta = doc["meta"]
        ok(f"A3 {name}: lists == hashseed0 lists", True, doc["lists"] == first)
        ok(f"A3 {name}: meta lists_sha256 == recomputed", meta["lists_sha256"], gd.lists_sha256(doc["lists"]))
        files = {p.name: p for p in (*arms.SCRIPT_FILES, *gd.MODULE_FILES)}
        ok(f"A3 {name}: meta script sha256 == current files",
           {n: gd.file_sha256(p) for n, p in files.items()}, {n: meta["sha256"].get(n) for n in files})
        ok(f"A3 {name}: meta set / ids / vectors",
           ["new82", qset.ids_sha256, gd.ARCHIVE_SHA256[VECTORS]],
           [meta["set"], meta["ids_sha256"], meta["sha256"].get("query_vectors")])
    ok("A3 PYTHONHASHSEED recorded", ["0", "1", "0"],
       [docs[n]["meta"]["pythonhashseed"] for n in ("hashseed0", "hashseed1", "threads1")])
    ok("A3 thread env recorded for threads1", dict(SINGLE_THREAD), docs["threads1"]["meta"]["thread_env"])


def check_d5(ok: Checks, qset: gd.QuestionSet, lists: Mapping[str, Mapping[str, list]]) -> None:
    """A4 (§4): R20 vs the container's D5 input; D5≈ on the archived D5 scores vs missing_rr."""
    d5_in = {i["sid"].split("|")[0]: i["pids"] for i in archived(gd.PN / "rr_d5_in.json")}
    ok("A4 R20 == PN/rr_d5_in.json pids", "82/82",
       f"{sum(lists[q]['R20'] == d5_in[q] for q in qset.ids)}/82")
    scores: dict[str, dict] = {}
    for line in gd.read_pinned(gd.PN / "rr_d5_out.jsonl",
                               gd.ARCHIVE_SHA256[gd.PN / "rr_d5_out.jsonl"]).decode("utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("type") == "r":
            scores[rec["sid"].split("|")[0]] = rec["scores"]
    same = sum(M.d5_missing(gd.question_gold(q), lists[q.qid]["R20"], scores[q.qid]) == q.missing_hops
               for q in qset.questions)
    ok("A4 D5≈ (R20 + archived D5 scores) == stored missing_rr", "82/82", f"{same}/82")


def report(ctx: arms.ArmContext, qset: gd.QuestionSet, doc: dict, wall: Mapping[str, float]) -> dict:
    meta, lists = doc["meta"], doc["lists"]
    vecs, _ = arms.load_query_vectors(VECTORS, qset.ids)
    long = {}
    for q in qset.questions:
        rank = ctx.dense.ranking(vecs[q.qid])
        seeds = {ctx.graph.row[p]: 1.0 / (i + 1) for i, p in enumerate(rank[:arms.N_SEEDS])}
        r = arms.ppr(ctx.graph, arms.scaled(seeds, 1.0), iters=LONG_ITERS)
        long[q.qid] = arms.take_extra((ctx.graph.passages[i] for i in arms.ppr_order(r)),
                                      set(rank[:arms.N_BASE]))
    return {"pool_lt30": {a: len(v) for a, v in meta["pool_lt30"].items()},
            "pool_size_min": {a: min(s[a] for s in meta["pool_size"].values()) for a in arms.ARMS},
            "bip": meta["graph"], "gd_top10_40_vs_200_iters_equal": sum(
                long[q] == lists[q]["GD"] for q in qset.ids),
            "r20_sizes": {"min": min(len(v["R20"]) for v in lists.values()),
                          "max": max(len(v["R20"]) for v in lists.values())},
            "cli_wall_seconds": dict(wall), "lists_sha256": meta["lists_sha256"],
            "g_questions_without_names": sorted(q for q, n in meta["g_question_names"].items() if not n),
            "blas": meta["blas"]}


def accept_a(out: Path) -> tuple[dict[str, Any], int]:
    gd.assert_set_allowed("new82")
    qset = gd.load_new82()
    wall = {name: run_arms(path, env) for name, (path, env) in RUNS.items()}
    docs = {name: json.loads(path.read_text(encoding="utf-8")) for name, (path, _) in RUNS.items()}
    lists = docs["hashseed0"]["lists"]
    ok = Checks()
    ok("lists.json question ids == NEW82 (file order)", list(qset.ids), list(lists))
    mismatches = check_lists(ok, qset, lists)
    check_runs(ok, qset, docs)
    ctx = arms.load_context()
    ok("A4 bip edges / name nodes / passages", BIP_SIZE,
       {"edges": ctx.graph.n_edges, "name_nodes": len(ctx.graph.names), "passages": ctx.graph.n_pass})
    check_d5(ok, qset, lists)
    doc = {"accept": "A", "spec": "prereg.md §3 驗收 A (NEW82)", "passed": ok.passed,
           "lists_sha256": docs["hashseed0"]["meta"]["lists_sha256"],
           "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "checker": {"path": str(HERE.relative_to(REPO)), "sha256": gd.file_sha256(HERE),
                       "imports": {Path(M.__file__).name: gd.file_sha256(M.__file__)}},
           "inputs": {**{name: {"path": str(path), "sha256": gd.file_sha256(path)}
                         for name, (path, _) in RUNS.items()},
                      **{str(p.relative_to(gd.STORE)): s for p, s in gd.ARCHIVE_SHA256.items()},
                      "prereg.md": gd.file_sha256(gd.PREREG_PATH)},
           "script_sha256": docs["hashseed0"]["meta"]["sha256"],
           "checks": ok.rows, "mismatches": mismatches, "report": report(ctx, qset, docs["hashseed0"], wall)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc, (0 if ok.passed else 1)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=gd.ACCEPT_DIR / "accept_a.json")
    args = ap.parse_args(argv)
    doc, code = accept_a(args.out)
    for row in doc["checks"]:
        print(("PASS " if row["pass"] else "FAIL ") + row["name"])
    print(f"驗收 A passed={doc['passed']} -> {args.out}")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except gd.GdError as err:
        print(f"accept_a.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)

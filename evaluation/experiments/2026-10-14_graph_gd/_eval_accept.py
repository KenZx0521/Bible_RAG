"""Acceptance B of prereg §3 (private part of evaluate.py).

build_reference() derives the archived top-k sets the way X/x_arms/reproduce_sel.py
merged() does: the four archived reranker score files merged in its order
(pn_d5, pn_sel, ev, at; later files overwrite), pools from EV/AT prf_lists.json. The
reference keeps every source sha and the merged scores themselves (for the drift).
accept_b() compares a new run's per-question top-k sets for C, GD, G, L, LEXPRF at
k=5 and 10 with it. The measured drift (max |new − archived| over the same (question,
passage) pairs) must stay within §10's 1e-5: above it the run is an infrastructure
failure and nothing is classified. Within it, a differing set is a boundary question only
when both cut gaps (new and archived) are below 10× the drift; anything else, or any pool
that differs, fails. The reference file is only trusted when it equals a fresh build from
the pinned archive; the run's lists and scores are read pinned (_eval_inputs.py) unless a
chain check passes pinned=False.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import _eval_inputs as I
import _eval_metrics as M
import gd_common as gd

REF_PATH = gd.OUT_ROOT / "new82" / "accept_b_reference.json"
SCORE_SOURCES = (   # (name, path, sha256) in the merge order of reproduce_sel.py merged()
    ("pn_d5", gd.PN / "rr_d5_out.jsonl", "dd1ed56c1c9dcb8b0ab3e903476d18923088531ba030bb94381a8f697c11caa5"),
    ("pn_sel", gd.PN / "sel_out.jsonl", "19f5dd052c9c345c01480f0236ee89e744532620757b147fb2ed6ab2e374b54d"),
    ("ev", gd.EV_SEL_OUT, gd.ARCHIVE_SHA256[gd.EV_SEL_OUT]),
    ("at", gd.AT / "rr_out.jsonl", "9de667ad89f2ac455a9c8ad13058b415b0b04baf065b74cb027c22f20f3dbe7e"))
LIST_SOURCES = {name: (path, gd.ARCHIVE_SHA256[path])
                for name, path in (("ev", gd.EV / "prf_lists.json"), ("at", gd.AT / "prf_lists.json"))}
REF_ARMS = {"C": ("ev", "ctrl_extra"), "GD": ("ev", "PPR_DENSEONLY"), "G": ("ev", "PPR_BIP"),
            "L": ("ev", "BM25_Q"), "LEXPRF": ("at", "LEXPRF")}   # reproduce_sel.py pools
ACCEPT_ARMS = tuple(REF_ARMS)
# §3 驗收 B 彙總參考值 (X/x_arms/reproduce_sel.json), order C, GD, G, L, LEXPRF
PREREG_SUMMARY = {
    "all_hops_hit": {10: dict(zip(ACCEPT_ARMS, (137, 151, 146, 143, 141))),
                     5: dict(zip(ACCEPT_ARMS, (119, 126, 124, 120, 122)))},
    "missing_hops_hit": {10: dict(zip(ACCEPT_ARMS, (17, 31, 26, 24, 21))),
                         5: dict(zip(ACCEPT_ARMS, (7, 14, 13, 10, 12)))}}
DRIFT_FACTOR = 10
DRIFT_MAX = gd.DRIFT_TOL    # §10: a larger new−archived difference is an infrastructure failure

__all__ = ["REF_PATH", "SCORE_SOURCES", "LIST_SOURCES", "ACCEPT_ARMS", "PREREG_SUMMARY",
           "DRIFT_FACTOR", "DRIFT_MAX", "build_reference", "accept_b", "summary"]


# ------------------------------------------------------------------ reference

def _archived_scores() -> tuple[dict[str, dict[str, float]], dict[str, dict[str, dict[str, float]]]]:
    """(merged q -> pid -> score, per-source scores) of the pinned archive files."""
    per_source: dict[str, dict[str, dict[str, float]]] = {}
    for name, path, sha in SCORE_SOURCES:
        src: dict[str, dict[str, float]] = defaultdict(dict)
        for line in gd.read_pinned(path, sha).decode("utf-8").splitlines():
            rec = json.loads(line) if line.strip() else {}
            if rec.get("type") == "r":
                src[rec["sid"].split("|")[0]].update(rec["scores"])
        per_source[name] = src
    merged: dict[str, dict[str, float]] = defaultdict(dict)
    for name, _, _ in SCORE_SOURCES:
        for qid, scores in per_source[name].items():
            merged[qid].update(scores)
    return merged, per_source


def _archived_pools(ids: list[str]) -> dict[str, dict[str, list[str]]]:
    docs = {n: json.loads(gd.read_pinned(p, sha)) for n, (p, sha) in LIST_SOURCES.items()}
    for name, doc in docs.items():
        gd.expect(f"{name} prf_lists ids", sorted(doc), ids)
    for q in ids:
        gd.expect(f"{q} d20 of ev and at", docs["ev"][q]["d20"], docs["at"][q]["d20"])
    return {q: {arm: docs[src][q]["d20"] + docs[src][q][key] for arm, (src, key) in REF_ARMS.items()}
            for q in ids}


def summary(qset: gd.QuestionSet, tops: Mapping[str, Mapping[str, Mapping[int, Any]]]) -> dict:
    """§3 驗收 B 彙總: all-hop and missing-hop hits per arm and k; tops[qid][arm][k] = top-k."""
    out: dict[str, dict[int, dict[str, int]]] = {key: {k: {} for k in M.KS} for key in PREREG_SUMMARY}
    for k in M.KS:
        for arm in ACCEPT_ARMS:
            hits = {q.qid: M.hop_hits(gd.question_gold(q), tops[q.qid][arm][k]) for q in qset.questions}
            out["all_hops_hit"][k][arm] = sum(map(sum, hits.values()))
            out["missing_hops_hit"][k][arm] = sum(hits[q.qid][h] for q in qset.questions
                                                  for h in q.missing_hops)
    return out


def _max_cross_drift(per_source: Mapping[str, Mapping[str, Mapping[str, float]]]) -> float:
    names = [n for n, _, _ in SCORE_SOURCES]
    return max((abs(s - per_source[b][q][p]) for i, a in enumerate(names) for b in names[i + 1:]
                for q, row in per_source[a].items() for p, s in row.items()
                if p in per_source[b].get(q, {})), default=0.0)


def build_reference() -> dict[str, Any]:
    """The archived reference of 驗收 B; its summary must equal the prereg numbers."""
    qset = gd.load_new82()
    ids = sorted(qset.ids)
    merged, per_source = _archived_scores()
    gd.expect("archived scored questions", sorted(merged), ids)
    pools = _archived_pools(ids)
    questions, tops = {}, {}
    for q in ids:
        tops[q] = {a: {k: M.top_k(pools[q][a], merged[q], k) for k in M.KS} for a in ACCEPT_ARMS}
        questions[q] = {"pools": pools[q],
                        "topk": {str(k): {a: list(tops[q][a][k]) for a in ACCEPT_ARMS} for k in M.KS},
                        "cut_gap": {str(k): {a: M.cut_gap(pools[q][a], merged[q], k) for a in ACCEPT_ARMS}
                                    for k in M.KS},
                        "scores": dict(sorted(merged[q].items()))}
    got = summary(qset, tops)
    gd.expect("reference summary vs prereg §3 驗收 B", got, PREREG_SUMMARY)
    gaps = [g for row in questions.values() for by_arm in row["cut_gap"].values()
            for g in by_arm.values() if g is not None]
    return {"kind": "accept_b_reference", "set": qset.name, "ids_sha256": qset.ids_sha256,
            "merge_order": [n for n, _, _ in SCORE_SOURCES],
            "score_sources": [{"name": n, "path": str(p), "sha256": s} for n, p, s in SCORE_SOURCES],
            "list_sources": {n: {"path": str(p), "sha256": s} for n, (p, s) in LIST_SOURCES.items()},
            "arms": list(ACCEPT_ARMS), "ks": list(M.KS), "summary": _jsonable(got),
            "archived_cross_run_drift": _max_cross_drift(per_source), "min_cut_gap": min(gaps),
            "questions": questions}


def _jsonable(s: Mapping[str, Mapping[int, Mapping[str, int]]]) -> dict:
    return {key: {str(k): dict(v) for k, v in by_k.items()} for key, by_k in s.items()}


# ------------------------------------------------------------------ acceptance B

def _load_reference(ref_path: Path) -> tuple[dict[str, Any], str]:
    """The reference file and its sha256; it must equal a fresh build from the pinned archive."""
    data = Path(ref_path).read_bytes()
    ref = json.loads(data)
    gd.expect("reference kind", ref.get("kind"), "accept_b_reference")
    body = {k: v for k, v in ref.items() if k != "meta"}
    if body != build_reference():
        raise gd.IntegrityError(f"{ref_path}: content differs from build_reference() on the pinned archive")
    return ref, hashlib.sha256(data).hexdigest()


def _drift(ref_q: Mapping[str, Mapping[str, Any]],
           new: Mapping[str, Mapping[str, float]]) -> tuple[float, int]:
    """Max |new − archived| over (question, passage) pairs scored in both, and their count."""
    diffs = [abs(s - ref_q[q]["scores"][p]) for q, row in new.items() for p, s in row.items()
             if p in ref_q[q]["scores"]]
    if not diffs:
        raise gd.GdError("no (question, passage) pair is scored in both the new run and the reference")
    return max(diffs), len(diffs)


def check_scored(pools: Mapping[str, Mapping[str, Sequence[str]]],
                 by_qid: Mapping[str, Mapping[str, float]], ids: Sequence[str]) -> None:
    """Every ACCEPT_ARMS pool passage has a score; else GdError naming the question and arm
    (as evaluate.py report does), e.g. for a file scored with score.py rerank --arms."""
    for q in ids:
        for arm in ACCEPT_ARMS:
            absent = [p for p in pools[arm][q] if p not in by_qid[q]]
            if absent:
                raise gd.GdError(f"{q} / {arm}: pool passages without a reranker score: {absent}")


def _mismatch(qid: str, arm: str, k: int, pool: tuple[str, ...], scores: Mapping[str, float],
              ref_q: Mapping[str, Any], limit: float) -> tuple[str, dict[str, Any]] | None:
    """None when the top-k sets agree; else ('boundary' | 'failed', row). Boundary needs both
    cut gaps (new, archived) below `limit` = 10 × measured drift."""
    new_top = set(M.top_k(pool, scores, k))
    ref_top = set(ref_q["topk"][str(k)][arm])
    if new_top == ref_top:
        return None
    gaps = (M.cut_gap(pool, scores, k), ref_q["cut_gap"][str(k)][arm])
    row = {"qid": qid, "arm": arm, "k": k, "new_only": sorted(new_top - ref_top),
           "ref_only": sorted(ref_top - new_top), "gap_new": gaps[0], "gap_ref": gaps[1]}
    return ("boundary" if None not in gaps and max(gaps) < limit else "failed"), row


def accept_b(lists_path: Path, scores_path: Path, ref_path: Path,
             pinned: bool = True) -> tuple[dict[str, Any], int]:
    """(result document, exit code): 0 when the drift is within 1e-5 and every top-k set
    equals the reference or is a boundary question."""
    gd.assert_set_allowed("new82")
    qset = gd.load_new82()
    ids = sorted(qset.ids)
    ref, ref_sha = _load_reference(ref_path)
    lists = I.Lists(lists_path, qset, pinned=pinned)
    scores = I.Scores(scores_path, qset, lists.content_sha256 if pinned else None)
    lacking = [a for a in ACCEPT_ARMS if a not in lists.arms]
    if lacking:
        raise gd.GdError(f"{lists_path}: arms {lacking} are absent")
    check_scored(lists.pools, scores.by_qid, ids)
    rq = ref["questions"]
    drift, n_pairs = _drift(rq, scores.by_qid)
    drift_ok = drift <= DRIFT_MAX
    limit = DRIFT_FACTOR * drift if drift_ok else 0.0     # no boundary class past the §10 limit
    pool_bad = [{"qid": q, "arm": a} for q in ids for a in ACCEPT_ARMS
                if list(lists.pools[a][q]) != rq[q]["pools"][a]]
    found: dict[str, list] = {"boundary": [], "failed": []}
    for q, arm, k in ((q, a, k) for q in ids for a in ACCEPT_ARMS for k in M.KS):
        hit = _mismatch(q, arm, k, lists.pools[arm][q], scores.by_qid[q], rq[q], limit)
        if hit:
            found[hit[0]].append(hit[1])
    tops = {q: {a: {k: M.top_k(lists.pools[a][q], scores.by_qid[q], k) for k in M.KS}
                for a in ACCEPT_ARMS} for q in ids}
    got = summary(qset, tops)
    n_sets = len(ids) * len(ACCEPT_ARMS) * len(M.KS)
    passed = drift_ok and not (pool_bad or found["failed"])
    return {"passed": passed, "pinned": pinned, "lists_sha256": lists.content_sha256,
            "drift": {"max_abs": drift, "n_pairs": n_pairs, "max_allowed": DRIFT_MAX, "ok": drift_ok,
                      "factor": DRIFT_FACTOR, "limit": limit,
                      **({} if drift_ok else {"infrastructure_failure":
                                              f"drift {drift:.3g} > {DRIFT_MAX:g} (§10)"})},
            "topk_sets": {"compared": n_sets, "equal": n_sets - len(found["boundary"]) - len(found["failed"]),
                          **found},
            "pool_mismatches": pool_bad,
            "inputs": {"lists": {"path": str(lists.path), "content_sha256": lists.content_sha256},
                       "scores": {"path": str(scores.path), "refchecks": [
                           {k: r[k] for k in ("n_pairs", "max_abs_diff", "pass")} for r in scores.refchecks]}},
            "inputs_meta": {"lists": dict(lists.meta), "scores": list(scores.metas)},
            "summary": {"new": _jsonable(got), "reference": ref["summary"],
                        "prereg": _jsonable(PREREG_SUMMARY), "new_equals_prereg": got == PREREG_SUMMARY},
            "cut_gaps": M.cut_gap_table(lists.pools, scores.by_qid, ACCEPT_ARMS, ids),
            "reference": {"path": str(ref_path), "sha256": ref_sha,
                          "archived_cross_run_drift": ref["archived_cross_run_drift"],
                          "min_cut_gap": ref["min_cut_gap"]}}, (0 if passed else 1)

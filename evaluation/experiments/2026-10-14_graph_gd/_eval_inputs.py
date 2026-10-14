"""Inputs of evaluate.py: arms.py lists and score.py scores, with their provenance (§10).

Lists rebuilds every §3 pool from a lists.json (shape checked by gd.check_entry). Scores
reads a score.py JSON-lines file. Pinned (the default for real runs) means the inputs must
prove where they came from, otherwise nothing is computed:

* lists: meta.set / ids_sha256 equal the question set, meta layers / vectors / build equal
  the gd_common pins, meta.lists_sha256 equals the content hash recomputed here, and the
  query vectors' container meta passes the embedder pins;
* scores: every meta line passes the reranker pins and run settings (batch 16, 12 threads),
  its host part names these lists (content hash), this question set, one and the same
  set of scorer scripts and one and the same set of scored arms (score.py rerank --arms;
  none recorded = every arm), and every r line is followed by a passing §10 refcheck line.
  A pool whose passages lack scores (an arm left out by --arms) fails in _eval_report.Table.

Unpinned inputs (converted archive files in chain checks) only get the shape and the
container fingerprint checks; reports record which mode ran.

WScores reads a score.py rerank-w file (§3 W, _score_w.read_w) and is always checked in
full: its meta lines must name the content hashes of these lists and of these whole-passage
scores, its single-window passages must carry exactly their whole-passage score, and it
must cover the C∪GD pool of every question.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import _score_io as sio
import _score_w as sw
import gd_common as gd

__all__ = ["Lists", "Scores", "WScores"]


class Lists:
    """arms.py output: per question D30, R20 and each arm's extra (§3 pool = D30[:20]+extra)."""

    def __init__(self, path: Path, qset: gd.QuestionSet, pinned: bool = True) -> None:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if not (isinstance(doc, dict) and isinstance(doc.get("lists"), dict)):
            raise gd.GdError(f"{path}: expected {{'meta': …, 'lists': {{qid: …}}}}")
        rows, ids = doc["lists"], qset.ids
        gd.expect(f"{path} question ids", sorted(rows), sorted(ids))
        for q in ids:
            gd.check_entry(q, rows[q])
        self.arms = tuple(a for a in gd.ARMS if any(a in rows[q] for q in ids))
        partial = [a for a in self.arms if not all(a in rows[q] for q in ids)]
        if partial:
            raise gd.GdError(f"{path}: arms {partial} are missing for some questions "
                             "(an arm must cover every question)")
        self.path, self.pinned = Path(path), pinned
        self.content_sha256 = gd.lists_sha256(rows)
        self.meta: Mapping[str, Any] = MappingProxyType(dict(doc.get("meta") or {}))
        if pinned:
            _check_lists_meta(self.path, self.meta, qset, self.content_sha256)
        self.dense = MappingProxyType({q: tuple(rows[q][gd.D_KEY]) for q in ids})
        self.r20 = MappingProxyType({q: tuple(rows[q].get(gd.R20_KEY) or ()) for q in ids})
        self.pools = MappingProxyType({a: MappingProxyType(
            {q: gd.arm_pool(rows[q], a) for q in ids}) for a in self.arms})


def _check_lists_meta(path: Path, meta: Mapping[str, Any], qset: gd.QuestionSet,
                      content_sha: str) -> None:
    got = {k: meta.get(k) for k in ("set", "ids_sha256", "build_id", "layers", "vectors_sha256",
                                     "lists_sha256")}
    want = {"set": qset.name, "ids_sha256": qset.ids_sha256, "build_id": gd.BUILD_ID,
            "layers": dict(gd.LAYER_VERSIONS), "vectors_sha256": gd.VECTORS_SHA256,
            "lists_sha256": content_sha}
    gd.expect(f"{path} meta (provenance of the lists)", got, want)
    gd.verify_container_meta(meta.get("query_vectors_meta") or {}, "embedder")


class Scores:
    """score.py output: meta lines, one r line per question, refcheck lines (see module doc)."""

    def __init__(self, path: Path, qset: gd.QuestionSet, lists_sha256: str | None) -> None:
        metas, rows, order = [], {}, []
        for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            kind = rec.get("type")
            if kind == "meta":
                gd.verify_container_meta(rec, "reranker", strict=lists_sha256 is not None)
                metas.append(rec)
            elif kind == "r":
                _score_row(path, n, rec, rows)
            elif kind == "refcheck":
                sio.check_refcheck(rec)
            else:
                raise gd.GdError(f"{path}:{n}: unknown line type {kind!r}")
            order.append(rec)
        if not metas:
            raise gd.IntegrityError(f"{path}: no container meta line (§10)")
        gd.expect(f"{path} question ids", sorted(rows), sorted(qset.ids))
        self.pinned = lists_sha256 is not None
        if self.pinned:
            _check_scores_provenance(path, metas, order, qset, lists_sha256)
        arms = {tuple((m.get("host") or {}).get("arms") or ()) for m in metas}
        if len(arms) != 1:
            raise gd.IntegrityError(f"{path}: meta lines record different scored arms {sorted(arms)}")
        self.arms: tuple[str, ...] | None = arms.pop() or None   # None: every arm (before --arms)
        self.path = Path(path)
        self.metas = tuple(metas)
        self.refchecks = tuple(r for r in order if r.get("type") == "refcheck")
        self.by_qid = MappingProxyType(rows)


def _check_scores_provenance(path: Path, metas: list[dict], order: list[dict],
                             qset: gd.QuestionSet, lists_sha: str) -> None:
    scripts = {k: ((metas[0].get("host") or {}).get("sha256") or {}).get(k) for k in sio.SCRIPT_NAMES}
    for m in metas:
        sio.check_host(m, lists_sha, scripts)
        gd.expect(f"{path} scored question set", (m["host"].get("set"), m["host"].get("set_ids_sha256")),
                  (qset.name, qset.ids_sha256))
    if None in scripts.values():
        raise gd.IntegrityError(f"{path}: meta host does not record {list(sio.SCRIPT_NAMES)}")
    if sio.needs_refcheck(order):
        raise gd.IntegrityError(f"{path}: scores without a later passing refcheck line (§10: "
                                "every scoring run re-scores the 32 reference pairs)")


def _score_row(path: Path, n: int, rec: Mapping[str, Any], rows: dict) -> None:
    qid = rec.get("sid")
    if qid in rows:
        raise gd.GdError(f"{path}:{n}: question {qid!r} scored twice")
    if rec.get("missing"):
        raise gd.GdError(f"{path}:{n}: {qid} has unscored passages {rec['missing']} (§10 分數缺漏)")
    scores = rec.get("scores")
    if not (isinstance(scores, dict) and all(isinstance(v, (int, float)) for v in scores.values())):
        raise gd.GdError(f"{path}:{n}: {qid} scores must be a {{pid: number}} object")
    rows[qid] = MappingProxyType(dict(scores))


class WScores:
    """score.py rerank-w output (§3 W): per question the W score of every passage of its C∪GD
    pool, bound to `lists` and `scores` (content hashes, single-window passages)."""

    def __init__(self, path: Path, qset: gd.QuestionSet, lists: Lists, scores: Scores) -> None:
        lacking = [a for a in sw.W_ARMS if a not in lists.arms]
        if lacking:
            raise gd.GdError(f"{lists.path}: W needs arms {list(sw.W_ARMS)}; {lacking} are absent")
        expected = {q: tuple(sorted(set(lists.pools["C"][q]) | set(lists.pools["GD"][q])))
                    for q in qset.ids}
        self.by_qid, self.metas, self.n_refchecks = sw.read_w(
            Path(path), qset, expected, scores.by_qid, lists.content_sha256)
        self.path = Path(path)
        self.scores_sha256 = sw.scores_content_sha256(scores.by_qid)

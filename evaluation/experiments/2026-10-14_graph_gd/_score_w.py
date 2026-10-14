"""W (逐窗重排) score files of the GD experiment (prereg §3 W, §5 必報敏感度; shared by
score.py rerank-w and evaluate.py --scores-w).

W re-scores the C∪GD pool of each question, D30[:20] ∪ C's extra ∪ GD's extra (W_ARMS), with
the window-max reranker score of rerank_w_stdin.py. A passage that fits one window keeps
its whole-passage score, which comes from the finished score.py rerank file of the same
lists (WholeScores) and is never re-scored. Pure host code: nothing here talks to the
container.

A W file holds, per container run, a meta line (the container's own, with
window_max_length, plus "host" = score.py's gd.collect_meta with kind "rerank-w", the
lists content hash, the whole-score content hash (scores_sha256), arms ["C", "GD"] and the
sha256 of W_SCRIPT_NAMES), then one line per question
{"type": "w", "sid", "scores": {pid: W score}, "n_windows": {pid: n}, "elapsed_s"}, and after
every run that scored something a §10 refcheck line, exactly like a rerank file.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import gd_common as gd
from _score_io import (SCRIPT_NAMES, Record, Writer, arms_union, check_host, check_refcheck,
                       completed, needs_refcheck, scan_jsonl)

__all__ = ["W_ARMS", "W_KIND", "W_LINE", "W_MAX_LENGTH", "W_SCRIPT_NAMES", "WholeScores",
           "scores_content_sha256", "read_whole_scores", "w_pools", "check_w_container_line",
           "complete_w_line", "check_w_record", "check_w_meta", "completed_w", "read_w", "w_writer",
           "scored_windows", "report_w_time"]

W_ARMS = ("C", "GD")                 # §3 W: 只算 C、GD
W_KIND = "rerank-w"                  # host "kind" of a W file's meta lines
W_LINE = "w"                         # line type of a W score line
W_MAX_LENGTH = 512                   # rerank_w_stdin.py MAXLEN (the reranker's max_length)
W_SCRIPT_NAMES = ("score.py", "_score_io.py", "_score_w.py", "rerank_w_stdin.py",
                  "rerank_stdin.py")  # rerank_stdin.py re-scores the §10 reference pairs


def _is_score(value: Any) -> bool:
    return type(value) is float and 0.0 <= value <= 1.0


def scores_content_sha256(by_qid: Mapping[str, Mapping[str, float]]) -> str:
    """Content hash of a scores file: sha256 of the compact JSON of {qid: {pid: score}}, both
    sorted. Unlike the file sha it ignores meta and refcheck lines and the line order."""
    doc = {q: {p: by_qid[q][p] for p in sorted(by_qid[q])} for q in sorted(by_qid)}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WholeScores:
    """A finished, pinned score.py rerank file of these lists: its whole-passage scores."""
    path: Path
    by_qid: Mapping[str, Mapping[str, float]]
    content_sha256: str
    arms: tuple[str, ...] | None            # host "arms"; None = every arm (file before --arms)


def _recorded(metas: Sequence[Record], key: str, what: str) -> Any:
    """The one value every meta line's host part records under `key`."""
    values = {json.dumps((m.get("host") or {}).get(key), sort_keys=True) for m in metas}
    if len(values) != 1:
        raise gd.IntegrityError(f"meta lines disagree on {what}: {sorted(values)}")
    return json.loads(values.pop())


def read_whole_scores(path: Path, qset: gd.QuestionSet, lists: Mapping[str, Mapping[str, list]],
                      lists_sha: str) -> WholeScores:
    """The rerank file `path` after the checks of a resume (pins, run settings, these lists,
    one set of scorer scripts, one set of arms, every pool scored exactly, a passing refcheck
    after every r line), for every question of the lists, with W_ARMS among its arms."""
    scan = scan_jsonl(path)
    if scan.cut_tail:
        raise gd.IntegrityError(f"{path}: an unfinished scores file (cut last line)")
    metas = [r for r in scan.records if r.get("type") == "meta"]
    if not metas:
        raise gd.IntegrityError(f"{path}: no container meta line (§10)")
    gd.expect(f"{path} scored question set", _recorded(metas, "set", "the set"), qset.name)
    gd.expect(f"{path} scored question ids", _recorded(metas, "set_ids_sha256", "the ids"),
              qset.ids_sha256)
    scripts = {n: ((metas[0].get("host") or {}).get("sha256") or {}).get(n) for n in SCRIPT_NAMES}
    if None in scripts.values():
        raise gd.IntegrityError(f"{path}: meta host does not record {list(SCRIPT_NAMES)}")
    arms = _recorded(metas, "arms", "the scored arms")
    lacking = [a for a in W_ARMS if arms is not None and a not in arms]
    if lacking:
        raise gd.IntegrityError(f"{path} scored arms {arms}: W needs {list(W_ARMS)} (§3 W)")
    expected = {q: arms_union(q, lists[q], arms) for q in lists}
    done = completed(scan.records, expected, lists_sha, scripts)
    gd.expect(f"{path} scored questions", sorted(done), sorted(lists))
    if needs_refcheck(scan.records):
        raise gd.IntegrityError(f"{path}: scores without a later passing refcheck line (§10)")
    by_qid = {r["sid"]: MappingProxyType(dict(r["scores"]))
              for r in scan.records if r.get("type") == "r"}
    return WholeScores(Path(path), MappingProxyType(by_qid), scores_content_sha256(by_qid),
                       None if arms is None else tuple(arms))


def w_pools(lists: Mapping[str, Mapping[str, list]], ids: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """§3 W pool of each question: D30[:20] ∪ C's extra ∪ GD's extra, in pid order."""
    return {q: arms_union(q, lists[q], W_ARMS) for q in ids}


# ------------------------------------------------------------------ lines

def check_w_container_line(rec: Record, item: Record) -> None:
    """A rerank_w_stdin.py line: windows counted for every pid of the item, a [0, 1] score for
    exactly the multi-window ones, nothing missing from the build."""
    sid, pids = item["sid"], list(item["pids"])
    gd.expect(f"{sid} container line type", rec.get("type"), W_LINE)
    if rec.get("missing"):
        raise gd.IntegrityError(f"{sid}: the build lacks passages {rec['missing']}")
    n_windows, scores = rec.get("n_windows"), rec.get("scores")
    if not (isinstance(n_windows, dict) and sorted(n_windows) == pids
            and all(type(n) is int and n >= 1 for n in n_windows.values())):
        raise gd.IntegrityError(f"{sid}: window counts differ from the W pool")
    multi = sorted(p for p, n in n_windows.items() if n > 1)
    if not (isinstance(scores, dict) and sorted(scores) == multi
            and all(map(_is_score, scores.values()))):
        raise gd.IntegrityError(f"{sid}: container scores must cover exactly the multi-window passages")


def complete_w_line(rec: Record, whole: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    """The file line of a checked container line: window maxima of the multi-window passages,
    the whole-passage score of every single-window one (§3 W; WF/exp/rr_probe_in_container.py:102-108)."""
    sid, n_windows = rec["sid"], rec["n_windows"]
    scores = {p: (rec["scores"][p] if n_windows[p] > 1 else whole[sid][p]) for p in sorted(n_windows)}
    return {"type": W_LINE, "sid": sid, "scores": scores,
            "n_windows": {p: n_windows[p] for p in sorted(n_windows)}, "elapsed_s": rec["elapsed_s"]}


def check_w_record(rec: Record, expected: Mapping[str, Sequence[str]],
                   whole: Mapping[str, Mapping[str, float]]) -> None:
    """A W file line covers exactly its question's W pool; a single-window passage carries
    exactly its whole-passage score."""
    sid = rec.get("sid")
    if rec.get("type") != W_LINE or sid not in expected:
        raise gd.IntegrityError(f"unexpected W line for {sid!r} (type {rec.get('type')!r})")
    scores, n_windows = rec.get("scores"), rec.get("n_windows")
    pids = list(expected[sid])
    if not (isinstance(scores, dict) and isinstance(n_windows, dict)
            and sorted(scores) == pids and sorted(n_windows) == pids):
        raise gd.IntegrityError(f"{sid}: W pids differ from the C∪GD pool")
    if not all(type(n) is int and n >= 1 for n in n_windows.values()) \
            or not all(map(_is_score, scores.values())):
        raise gd.IntegrityError(f"{sid}: W window counts or scores are malformed")
    off = [p for p in pids if n_windows[p] == 1 and scores[p] != whole[sid].get(p)]
    if off:
        raise gd.IntegrityError(f"{sid}: single-window passages {off[:3]} do not carry their "
                                "whole-passage score (§3 W: 只有一窗的段沿用整段分數)")


def check_w_meta(meta: Record, lists_sha: str, scores_sha: str, scripts: Mapping[str, str]) -> None:
    """A W meta line: reranker pins and run settings, the 512-token windows, and a host part of
    kind rerank-w naming these lists, these whole scores, arms C and GD and these scripts."""
    gd.verify_container_meta(meta, "reranker", strict=True)
    gd.expect("W window max_length", meta.get("window_max_length"), W_MAX_LENGTH)
    check_host(meta, lists_sha, scripts, W_ARMS)
    host = meta.get("host") or {}
    gd.expect("W meta kind", host.get("kind"), W_KIND)
    gd.expect("whole-score content sha256 recorded in the W file", host.get("scores_sha256"),
              scores_sha)


def completed_w(records: Sequence[Record], expected: Mapping[str, Sequence[str]],
                whole: WholeScores | Mapping[str, Mapping[str, float]], lists_sha: str,
                scripts: Mapping[str, str]) -> frozenset[str]:
    """Questions a W file already holds; any foreign or inconsistent line raises."""
    by_qid = whole.by_qid if isinstance(whole, WholeScores) else whole
    scores_sha = scores_content_sha256(by_qid)
    done: set[str] = set()
    seen_meta = False
    for rec in records:
        kind = rec.get("type")
        if kind == "meta":
            check_w_meta(rec, lists_sha, scores_sha, scripts)
            seen_meta = True
            continue
        if kind == "refcheck":
            check_refcheck(rec)
            continue
        if not seen_meta:
            raise gd.IntegrityError("a W line precedes every meta line")
        check_w_record(rec, expected, by_qid)
        if rec["sid"] in done:
            raise gd.IntegrityError(f"{rec['sid']} is W-scored twice")
        done.add(rec["sid"])
    return frozenset(done)


def read_w(path: Path, qset: gd.QuestionSet, expected: Mapping[str, Sequence[str]],
           whole: Mapping[str, Mapping[str, float]], lists_sha: str
           ) -> tuple[Mapping[str, Mapping[str, float]], tuple[dict, ...], int]:
    """A finished W file of these lists and whole scores, for every question of the set:
    (qid -> pid -> W score, its meta lines, its number of refcheck lines)."""
    scan = scan_jsonl(path)
    if scan.cut_tail:
        raise gd.IntegrityError(f"{path}: an unfinished W file (cut last line)")
    metas = tuple(r for r in scan.records if r.get("type") == "meta")
    if not metas:
        raise gd.IntegrityError(f"{path}: no container meta line (§10)")
    gd.expect(f"{path} W question set", _recorded(metas, "set", "the set"), qset.name)
    gd.expect(f"{path} W question ids", _recorded(metas, "set_ids_sha256", "the ids"),
              qset.ids_sha256)
    scripts = {n: ((metas[0].get("host") or {}).get("sha256") or {}).get(n) for n in W_SCRIPT_NAMES}
    if None in scripts.values():
        raise gd.IntegrityError(f"{path}: meta host does not record {list(W_SCRIPT_NAMES)}")
    done = completed_w(scan.records, expected, whole, lists_sha, scripts)
    gd.expect(f"{path} W-scored questions", sorted(done), sorted(qset.ids))
    if needs_refcheck(scan.records, W_LINE):
        raise gd.IntegrityError(f"{path}: W scores without a later passing refcheck line (§10)")
    rows = {r["sid"]: MappingProxyType(dict(r["scores"]))
            for r in scan.records if r.get("type") == W_LINE}
    return MappingProxyType(rows), metas, sum(r.get("type") == "refcheck" for r in scan.records)


# ------------------------------------------------------------------ score.py rerank-w helpers

def w_writer(write: Writer, expected: Mapping[str, Sequence[str]], whole: WholeScores) -> Writer:
    """Container lines -> W file lines: a meta line must use W_MAX_LENGTH windows; a w line
    gets the whole-passage score of its single-window passages and is checked again."""
    def put(rec: Record) -> None:
        if rec.get("type") == "meta":
            gd.expect("W window max_length", rec.get("window_max_length"), W_MAX_LENGTH)
            write(rec)
            return
        line = complete_w_line(rec, whole.by_qid)
        check_w_record(line, expected, whole.by_qid)
        write(line)
    return put


def scored_windows(line: Record) -> int:
    """Windows the container scored for one question (single-window passages are not)."""
    return sum(n for n in line["n_windows"].values() if n > 1)


def report_w_time(lines: Sequence[Record], wall: float) -> None:
    counts = [n for r in lines for n in r["n_windows"].values()]
    multi, windows = sum(n > 1 for n in counts), sum(map(scored_windows, lines))
    scoring = sum(float(r["elapsed_s"]) for r in lines)
    print(f"W passages {len(counts)}; multi-window {multi} ({multi / max(len(counts), 1):.1%}), "
          f"mean {sum(counts) / max(len(counts), 1):.3f} windows/passage; {windows} windows "
          f"scored; wall {wall:.1f}s; in-container {scoring:.1f}s "
          f"({scoring / max(windows, 1):.3f} s/window)")

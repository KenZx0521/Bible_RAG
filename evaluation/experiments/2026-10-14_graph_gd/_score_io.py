"""Score-file formats of the GD experiment (shared by score.py, which re-exports it, and evaluate.py).

The container payload, the arms.py lists and their §3 pool unions (gd.pool_union, or
arms_union for the arms chosen with score.py rerank --arms), the JSON-lines outputs (scan
with a cut last line, resume bookkeeping, line checks), the query vectors and the archived
§10 reference pairs. Pure host code: nothing here talks to the container.

A scores file holds, per container run, a meta line (the container's own plus "host" =
score.py's gd.collect_meta with the lists content hash, the scored arms and the scorer
scripts' sha256), then one r line per question; every rerank run that scored something
ends with a "refcheck" line (the 32 reference pairs re-scored, §10). evaluate.py accepts
the file only when every r line is followed by a passing refcheck. Files written before
--arms existed carry no host "arms": they scored every arm of their lists.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

import gd_common as gd

__all__ = ["N_REF_PAIRS", "EV_SCORES", "SCRIPT_NAMES", "Record", "Writer", "build_script",
           "pool_union", "parse_arms", "lists_arms", "arms_union", "load_lists", "Scan",
           "scan_jsonl", "check_score_record", "check_host", "check_refcheck", "completed",
           "needs_refcheck", "fresh", "write_new_jsonl", "drop_cut_tail", "line_appender",
           "decode_vector", "compare_vectors", "vectors", "check_against_ref", "reference_pairs",
           "refpair_items", "refcheck_record", "select_ids", "positive_int", "report_time"]

N_REF_PAIRS = 32                          # §10 reference pairs
EV_SCORES = gd.EV_SEL_OUT
EV_INPUT = gd.EV_SEL_IN                   # the EV queries of the reference pairs
ENCODE_TOL = gd.DRIFT_TOL                 # §3 re-encode max|Δ|
SCRIPT_NAMES = ("score.py", "_score_io.py", "rerank_stdin.py")   # pinned per scores file
pool_union = gd.pool_union

Record = Mapping[str, Any]
Writer = Callable[[Record], None]


def build_script(body: str, items: Sequence[Record]) -> str:
    """The stdin script: PAYLOAD_B64 (base64 of the UTF-8 JSON items) before the body."""
    raw = json.dumps(list(items), ensure_ascii=False).encode("utf-8")
    return f'PAYLOAD_B64 = "{base64.b64encode(raw).decode("ascii")}"\n' + body


def parse_arms(spec: str | None) -> tuple[str, ...] | None:
    """--arms 'C,GD' -> ('C', 'GD') in gd.ARMS order; None (no option) means every arm."""
    if spec is None:
        return None
    arms = [a.strip() for a in spec.split(",") if a.strip()]
    unknown = sorted(set(arms) - set(gd.ARMS))
    if not arms or unknown or len(set(arms)) != len(arms):
        raise gd.GdError(f"--arms must be distinct arms out of {list(gd.ARMS)} (got {spec!r})")
    return tuple(a for a in gd.ARMS if a in arms)


def lists_arms(lists: Mapping[str, Mapping[str, list]]) -> tuple[str, ...]:
    """The arms any question of the lists carries, in gd.ARMS order."""
    return tuple(a for a in gd.ARMS if any(a in entry for entry in lists.values()))


def arms_union(qid: str, entry: Mapping[str, Sequence[str]],
               arms: Sequence[str] | None = None) -> tuple[str, ...]:
    """D30[:20] ∪ the extra of each of `arms`, in pid order; None = every arm (gd.pool_union)."""
    if arms is None:
        return gd.pool_union(qid, entry)
    gd.check_entry(qid, entry)
    lacking = [a for a in arms if a not in entry]
    if not arms or lacking:
        raise gd.IntegrityError(f"{qid}: the lists carry no extra for arms {lacking or '(none)'}")
    return tuple(sorted(set(entry[gd.D_KEY][:gd.N_BASE]).union(*(entry[a] for a in arms))))


def load_lists(path: Path, cli_set: str | None) -> tuple[str, Mapping[str, Mapping[str, list]]]:
    """(set name, lists) of an arms.py output; the set comes from meta 'set' and/or --set."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("lists"), dict):
        raise gd.GdError(f"{path}: expected {{'meta': ..., 'lists': {{qid: {{arm: [pid]}}}}}}")
    named = (doc.get("meta") or {}).get("set")
    if cli_set and named and cli_set != named:
        raise gd.GdError(f"--set {cli_set!r} but {path} meta says set {named!r}")
    if not (cli_set or named):
        raise gd.GdError(f"{path} meta has no 'set'; pass --set")
    return cli_set or named, doc["lists"]


@dataclass(frozen=True)
class Scan:
    records: tuple[dict, ...]  # complete, parsed lines in file order
    keep_bytes: int            # file length up to and including the last complete line
    cut_tail: bool             # an incomplete last line follows keep_bytes


def scan_jsonl(path: Path) -> Scan:
    """Parse a JSON-lines file; only its last line may be cut (unterminated or unparsable)."""
    if not Path(path).exists():
        return Scan((), 0, False)
    lines = Path(path).read_bytes().split(b"\n")
    tail = lines.pop()   # bytes after the last newline
    records: list[dict] = []
    offset = 0
    for i, raw in enumerate(lines):
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as err:
            if i == len(lines) - 1 and not tail:
                return Scan(tuple(records), offset, True)
            raise gd.IntegrityError(f"{path}: line {i + 1} is not JSON ({err}); "
                                    "only the last line may be incomplete") from err
        offset += len(raw) + 1
    return Scan(tuple(records), offset, bool(tail))


def check_score_record(rec: Record, expected: Mapping[str, Sequence[str]]) -> None:
    """An r line scores exactly its question's union with [0, 1] floats, nothing missing."""
    sid = rec.get("sid")
    if rec.get("type") != "r" or sid not in expected:
        raise gd.IntegrityError(f"unexpected score line for {sid!r} (type {rec.get('type')!r})")
    if rec.get("missing"):
        raise gd.IntegrityError(f"{sid}: the build lacks passages {rec['missing']}")
    scores = rec.get("scores")
    if not isinstance(scores, dict) or sorted(scores) != list(expected[sid]):
        raise gd.IntegrityError(f"{sid}: scored pids differ from the pool union")
    bad = [p for p, s in scores.items() if not (type(s) is float and 0.0 <= s <= 1.0)]
    if bad:
        raise gd.IntegrityError(f"{sid}: scores outside [0, 1] for {bad[:3]}")


def check_host(meta: Record, lists_sha: str, scripts: Mapping[str, str],
               arms: Sequence[str] | None = None) -> None:
    """A meta line's host part: these lists (content hash), these scorer scripts and, when
    `arms` is given, these scored arms (host "arms")."""
    host = meta.get("host") or {}
    gd.expect("lists content sha256 recorded in the scores file", host.get("lists_sha256"), lists_sha)
    got = {name: (host.get("sha256") or {}).get(name) for name in scripts}
    gd.expect("scorer script sha256 recorded in the scores file", got, dict(scripts))
    if arms is not None:
        gd.expect("arms recorded in the scores file (score.py rerank --arms)", host.get("arms"),
                  list(arms))


def check_refcheck(rec: Record) -> None:
    """A refcheck line: its container ran on the pins and the 32 pairs stayed within 1e-5."""
    gd.verify_container_meta(rec.get("container_meta") or {}, "reranker", strict=True)
    if not (rec.get("n_pairs") == N_REF_PAIRS and rec.get("pass") is True
            and float(rec.get("max_abs_diff", "inf")) <= gd.DRIFT_TOL):
        raise gd.IntegrityError(f"failed or malformed reference check (max|Δ| "
                                f"{rec.get('max_abs_diff')}); §10: start a new scores file")


def completed(records: Sequence[Record], expected: Mapping[str, Sequence[str]], lists_sha: str,
              scripts: Mapping[str, str], arms: Sequence[str] | None = None) -> frozenset[str]:
    """Questions a scores file already holds; any foreign or inconsistent line raises."""
    done: set[str] = set()
    seen_meta = False
    for rec in records:
        kind = rec.get("type")
        if kind == "meta":
            gd.verify_container_meta(rec, "reranker", strict=True)
            check_host(rec, lists_sha, scripts, arms)
            seen_meta = True
            continue
        if kind == "refcheck":
            check_refcheck(rec)
            continue
        if not seen_meta:
            raise gd.IntegrityError("a score line precedes every meta line")
        check_score_record(rec, expected)
        if rec["sid"] in done:
            raise gd.IntegrityError(f"{rec['sid']} is scored twice")
        done.add(rec["sid"])
    return frozenset(done)


def needs_refcheck(records: Sequence[Record], line_type: str = "r") -> bool:
    """True when some score line (type `line_type`: r, or w for W files) has no refcheck after it."""
    last = {r.get("type"): i for i, r in enumerate(records)}
    return line_type in last and last.get("refcheck", -1) < last[line_type]


def fresh(path: Path) -> Path:
    """`path`, which must not exist yet: raw outputs are never overwritten."""
    if Path(path).exists():
        raise gd.GdError(f"{path} exists; raw outputs are not overwritten")
    return Path(path)


def write_new_jsonl(path: Path, records: Sequence[Record]) -> None:
    """Write a new JSON-lines output whole (via <path>.partial, then rename)."""
    part = fresh(path).with_name(Path(path).name + ".partial")
    with open(part, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    os.replace(part, path)


def drop_cut_tail(scan: Scan, out: Path) -> None:
    """Truncate `out` to its last complete line when scan_jsonl found a cut one."""
    if scan.cut_tail:
        with open(out, "r+b") as fh:
            fh.truncate(scan.keep_bytes)
        print(f"dropped the incomplete last line of {out}")


def line_appender(fh: Any) -> Writer:
    """A Writer appending one JSON line to the open file and flushing it, so a crash keeps
    every finished question."""
    def append(rec: Record) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
    return append


def decode_vector(rec: Record, _item: Record | None = None) -> np.ndarray:
    """The float32 query vector of a q line (also the Sink check of encode lines)."""
    gd.expect(f"{rec.get('sid')} line type", rec.get("type"), "q")
    return gd.decode_vector_b64(rec["vec_b64"], str(rec.get("sid")))


def compare_vectors(new: Mapping[str, np.ndarray],
                    ref: Mapping[str, np.ndarray]) -> dict[str, float]:
    """max|Δ| per sid against ref (looked up as sid, then 'sid|Q'), in float64."""
    out = {}
    for sid, vec in new.items():
        old = ref.get(sid, ref.get(f"{sid}|Q"))
        if old is None:
            raise gd.IntegrityError(f"reference vectors have no {sid}")
        out[sid] = float(np.max(np.abs(vec.astype(np.float64) - old.astype(np.float64))))
    return out


def vectors(path: Path) -> dict:
    return {r["sid"]: decode_vector(r) for r in scan_jsonl(path).records if r.get("type") == "q"}


def check_against_ref(out: Path, ref: Path) -> None:
    """§3 re-encode check; the result is kept next to the vectors as <out>.refcheck.json."""
    diffs = compare_vectors(vectors(out), vectors(ref))
    worst = max(diffs.values())
    report = {"ref": str(ref), "ref_sha256": gd.file_sha256(ref), "tol": ENCODE_TOL,
              "max_abs_diff": diffs, "worst": worst, "pass": worst <= ENCODE_TOL}
    side = fresh(out.with_name(out.name + ".refcheck.json"))
    side.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"encode vs {ref.name}: max|Δ| {worst:.3g} over {len(diffs)} vectors "
          f"(tol {ENCODE_TOL:g}) -> {side.name}")
    if worst > ENCODE_TOL:
        raise gd.IntegrityError(f"re-encoded vectors differ by {worst:.3g} > {ENCODE_TOL:g} (§3)")


def reference_pairs(path: Path = EV_SCORES,
                    n: int = N_REF_PAIRS) -> list[tuple[str, str, float]]:
    """The first n (qid, pid, score) of the pinned archived scores file, sorted by (qid, pid)."""
    data = gd.read_pinned(path, gd.ARCHIVE_SHA256[path]).decode("utf-8")
    pairs: dict[tuple[str, str], float] = {}
    for line in data.splitlines():
        rec = json.loads(line) if line.strip() else {}
        if rec.get("type") != "r":
            continue
        qid, _, tag = rec["sid"].partition("|")
        if tag not in ("", "Q"):
            raise gd.IntegrityError(f"{path}: {rec['sid']} is not a question-query score")
        for pid, s in rec["scores"].items():
            if pairs.setdefault((qid, pid), s) != s:
                raise gd.IntegrityError(f"{path}: ({qid}, {pid}) has two different scores")
    return [(q, p, pairs[(q, p)]) for q, p in sorted(pairs)[:n]]


def refpair_items(ref: Sequence[tuple[str, str, float]], qset: gd.QuestionSet) -> list[dict]:
    """One item per question of the reference pairs; its query must be the EV query."""
    by_id = qset.by_id()
    archived = {i["sid"]: i["query"]
                for i in json.loads(gd.read_pinned(EV_INPUT, gd.ARCHIVE_SHA256[EV_INPUT]))}
    groups: dict[str, list[str]] = {}
    for qid, pid, _ in ref:
        groups.setdefault(qid, []).append(pid)
    for qid in groups:
        gd.expect(f"{qid} question vs the EV query", by_id[qid].question, archived.get(f"{qid}|Q"))
    return [{"sid": q, "query": by_id[q].question, "pids": sorted(p)} for q, p in groups.items()]


def refcheck_record(ref: Sequence[tuple[str, str, float]], new: Mapping[str, Mapping[str, float]],
                    container_meta: Record) -> dict[str, Any]:
    """The §10 refcheck line: per pair (qid, pid, archived, new, |Δ|) and the verdict."""
    diffs = [(q, p, old, new[q][p], abs(new[q][p] - old)) for q, p, old in ref]
    worst = max(d[-1] for d in diffs)
    return {"type": "refcheck", "source": str(EV_SCORES),
            "source_sha256": gd.ARCHIVE_SHA256[EV_SCORES], "tol": gd.DRIFT_TOL,
            "n_pairs": len(diffs), "max_abs_diff": worst, "pass": worst <= gd.DRIFT_TOL,
            "container_meta": {k: v for k, v in container_meta.items() if k not in ("host", "chunk")},
            "pairs": [list(d) for d in diffs]}


# ------------------------------------------------------------------ CLI helpers

def select_ids(spec: str | None, qset: gd.QuestionSet) -> list[str]:
    """--ids 'a,b' in the given order (default: the whole set); distinct ids of the set."""
    ids = [s.strip() for s in spec.split(",") if s.strip()] if spec else list(qset.ids)
    bad = sorted(set(ids) - set(qset.ids))
    if bad or len(set(ids)) != len(ids) or not ids:
        raise gd.GdError(f"--ids must be distinct {qset.name} ids (unknown: {bad[:3]})")
    return ids


def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return int(text)


def report_time(lines: Sequence[Record], wall: float) -> None:
    pairs = sum(len(r["scores"]) for r in lines)
    scoring = sum(float(r["elapsed_s"]) for r in lines)
    print(f"pairs {pairs}; wall {wall:.1f}s ({wall / max(pairs, 1):.3f} s/pair); "
          f"in-container scoring {scoring:.1f}s ({scoring / max(pairs, 1):.3f} s/pair)")

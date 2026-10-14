"""Host runner for the container side of the GD experiment (prereg §3, §10).

Subcommands:
  encode   --set new82 [--ids a,b,...] --out V.jsonl [--ref REF.jsonl]
      Query vectors from encode_stdin.py. --ref compares each vector with REF (sid qid or
      'qid|Q', e.g. PN/encode_out.jsonl): max|Δ| must be ≤1e-5 (§3).
  rerank   --lists L.json --out S.jsonl [--set new82] [--chunk N]
      Reranker scores (rerank_stdin.py) of each question's pool union D30[:20] ∪ every arm's
      extra, in pid order, N questions per container run; then, in one more container run,
      the §10 reference pairs, appended as a "refcheck" line (|Δ|>1e-5 fails). Re-running
      resumes: questions the file holds are skipped, a cut last line is dropped, and a
      missing final refcheck is redone even when no question is left.
  refpairs --out R.jsonl
      The same 32 reference pairs (first (qid, pid) of EV/ev_sel_out.jsonl) on their own.

Outputs are JSON lines (formats in _score_io.py): per container run a meta line (the
container's own, checked against the gd_common pins and run settings before anything is
kept, plus "host" = gd.collect_meta with the scorer scripts' and the lists' sha256), then
{"type": "q", "sid", "vec_b64"} or {"type": "r", "sid", "scores": {pid: score}, "missing":
[], "elapsed_s"} per question. Raw outputs are never overwritten. Pin mismatches and
infrastructure failures exit 2 with one line; the confirmation sets stay locked until their
prereg appendices exist and both acceptance files passed (gd.assert_set_allowed).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import _score_io
import gd_common as gd
from _score_io import (  # noqa: F401  (the format helpers are re-exported for tests)
    EV_SCORES, N_REF_PAIRS, SCRIPT_NAMES, Record, Scan, Writer, build_script, check_score_record,
    compare_vectors, completed, decode_vector, fresh, load_lists, needs_refcheck, pool_union,
    reference_pairs, refcheck_record, scan_jsonl, write_new_jsonl)

SCRIPT = Path(__file__).resolve()
IO_MODULE = Path(_score_io.__file__).resolve()
ENCODE_STDIN = SCRIPT.parent / "encode_stdin.py"
RERANK_STDIN = SCRIPT.parent / "rerank_stdin.py"
PREREG = gd.PREREG_PATH      # what the appendix guard reads (tests point it elsewhere)
ACCEPT = gd.ACCEPT_DIR       # where the guard looks for accept_a.json / accept_b.json
EV_INPUT = gd.EV_SEL_IN
DEFAULT_CHUNK = 10           # questions per container run (one model load each)
REF_TOL = ENCODE_TOL = gd.DRIFT_TOL   # §10 reference-pair drift, §3 re-encode max|Δ|


class ContainerError(gd.GdError):
    """The container script failed, printed a non-JSON line, or stopped early."""


# ------------------------------------------------------------------ container runs

def run_container(script: str, err_path: Path, on_line: Callable[[dict], None]) -> None:
    """Feed `script` to gd.CONTAINER_PYTHON and each stdout JSON line to on_line.

    stderr is appended to err_path; if on_line raises, the container is killed."""
    with open(err_path, "ab") as err:
        proc = subprocess.Popen(list(gd.CONTAINER_PYTHON), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=err)
        try:
            try:
                proc.stdin.write(script.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError as e:
                raise ContainerError(f"container closed its input (exit {proc.wait()}); "
                                     f"see {err_path}") from e
            for raw in proc.stdout:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise ContainerError(f"non-JSON container output {raw[:120]!r}") from e
                on_line(rec)
            rc = proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    if rc != 0:
        raise ContainerError(f"container script exited {rc}; see {err_path}")


@dataclass
class Sink:
    """One container run: its meta line is checked against the pins before anything is
    written, then one line per item in payload order, each checked by `check`."""
    kind: str                                  # 'reranker' | 'embedder'
    items: Sequence[Record]
    host: Record
    write: Writer
    check: Callable[[Record, Record], Any]     # (line, item); raises when the line is bad
    lines: list[Record] = field(default_factory=list)
    has_meta: bool = False

    def __call__(self, rec: dict) -> None:
        if not self.has_meta:
            gd.verify_container_meta(rec, self.kind, strict=True)
            self.write({**rec, "host": self.host, "chunk": [i["sid"] for i in self.items]})
            self.has_meta = True
            return
        if len(self.lines) == len(self.items):
            raise ContainerError(f"container sent more than {len(self.items)} item lines")
        item = self.items[len(self.lines)]
        gd.expect("container line order", rec.get("sid"), item["sid"])
        self.check(rec, item)
        self.write(rec)
        self.lines.append(rec)

    def finish(self) -> list[Record]:
        if not self.has_meta or len(self.lines) != len(self.items):
            raise ContainerError(f"container stopped after {len(self.lines)} of "
                                 f"{len(self.items)} items")
        return self.lines


def check_rerank_line(rec: Record, item: Record) -> None:
    check_score_record(rec, {item["sid"]: item["pids"]})


def reranker_sink(items: Sequence[Record], host: Record, write: Writer) -> Sink:
    """A Sink for rerank_stdin.py: strict run settings (batch 16, 12 threads) on its meta line."""
    return Sink("reranker", items, host, write, check_rerank_line)


def err_log(out: Path) -> Path:
    return out.with_name(out.name + ".err.log")


def script_files(stdin_script: Path) -> dict[str, Path]:
    """The scorer's own files (SCRIPT_NAMES order for rerank) hashed into every meta line."""
    return {"score.py": SCRIPT, "_score_io.py": IO_MODULE, stdin_script.name: stdin_script}


def script_shas() -> dict[str, str]:
    """sha256 of score.py, _score_io.py and rerank_stdin.py, as a scores file must record them."""
    return {name: gd.file_sha256(path) for name, path in script_files(RERANK_STDIN).items()}


def host_meta(kind: str, files: Mapping[str, Path], qset: gd.QuestionSet, **extra: Any) -> dict:
    """§10 meta of this run; also checks the running container's image (gd.IMAGE_ID)."""
    return gd.collect_meta(files, kind=kind, set=qset.name, set_sources=dict(qset.sources),
                           set_ids_sha256=qset.ids_sha256,
                           container_image_id=gd.container_image_id(), **extra)


def score_chunks(items: Sequence[Record], write: Writer, host: Record, err: Path,
                 chunk: int) -> list[Record]:
    """Score `items`, `chunk` questions per container run; returns their r lines."""
    body = RERANK_STDIN.read_text(encoding="utf-8")
    out: list[Record] = []
    for start in range(0, len(items), chunk):
        part = items[start:start + chunk]
        sink = reranker_sink(part, host, write)
        run_container(build_script(body, part), err, sink)
        out += sink.finish()
        print(f"  scored {start + len(part)}/{len(items)} questions, "
              f"{sum(len(r['scores']) for r in out)} pairs", flush=True)
    return out


def report_time(lines: Sequence[Record], wall: float) -> None:
    pairs = sum(len(r["scores"]) for r in lines)
    scoring = sum(float(r["elapsed_s"]) for r in lines)
    print(f"pairs {pairs}; wall {wall:.1f}s ({wall / max(pairs, 1):.3f} s/pair); "
          f"in-container scoring {scoring:.1f}s ({scoring / max(pairs, 1):.3f} s/pair)")


# ------------------------------------------------------------------ rerank

def rerank_plan(lists_path: Path, cli_set: str | None) -> tuple[gd.QuestionSet, dict, str]:
    """(question set, qid -> pool union in set order, lists content sha256) after the guard."""
    name, lists = load_lists(lists_path, cli_set)
    gd.assert_set_allowed(name, PREREG, ACCEPT)
    qset = gd.load_question_set(name)
    unknown = sorted(set(lists) - set(qset.ids))
    if unknown:
        raise gd.IntegrityError(f"{lists_path} has questions outside {name}: {unknown[:3]}")
    expected = {q: pool_union(q, lists[q]) for q in qset.ids if q in lists}
    return qset, expected, gd.lists_sha256(lists)


def cmd_rerank(args: argparse.Namespace) -> None:
    lists_path, out = Path(args.lists), Path(args.out)
    qset, expected, lists_sha = rerank_plan(lists_path, args.set)
    scan = scan_jsonl(out)
    done = completed(scan.records, expected, lists_sha, script_shas())
    todo = [q for q in expected if q not in done]
    print(f"rerank {qset.name}: {len(expected)}/{len(qset.ids)} questions in lists, {len(done)} "
          f"done, {len(todo)} to score ({sum(len(expected[q]) for q in todo)} pairs)")
    if scan.cut_tail:
        with open(out, "r+b") as fh:
            fh.truncate(scan.keep_bytes)
        print(f"dropped the incomplete last line of {out}")
    if not (todo or needs_refcheck(scan.records)):
        return
    host = host_meta("rerank", {**script_files(RERANK_STDIN), "lists": lists_path}, qset,
                     chunk_size=args.chunk, lists_sha256=lists_sha)
    by_id = qset.by_id()
    items = [{"sid": q, "query": by_id[q].question, "pids": list(expected[q])} for q in todo]
    t0 = time.monotonic()
    with open(out, "a", encoding="utf-8") as fh:
        def append(rec: Record) -> None:   # flushed per line: a crash keeps finished questions
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        lines = score_chunks(items, append, host, err_log(out), args.chunk)
        report_time(lines, time.monotonic() - t0)
        _, check = run_refcheck(host, err_log(out))
        append(check)
    finish_refcheck(check, out)


# ------------------------------------------------------------------ refpairs (§10)

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


def run_refcheck(host: Record, err: Path) -> tuple[list[Record], dict]:
    """Re-score the §10 reference pairs in one container run: (its lines, the refcheck line)."""
    ref = reference_pairs()
    items = refpair_items(ref, gd.load_new82())
    lines: list[Record] = []
    scored = score_chunks(items, lines.append, host, err, len(items))
    return lines, refcheck_record(ref, {r["sid"]: r["scores"] for r in scored}, lines[0])


def finish_refcheck(check: Mapping[str, Any], out: Path) -> None:
    print(f"refcheck: {check['n_pairs']} pairs, max|Δ| {check['max_abs_diff']:.3g} "
          f"(tol {REF_TOL:g}) -> {out}")
    if not check["pass"]:
        raise gd.IntegrityError(f"reference pairs drifted by {check['max_abs_diff']:.3g} > "
                                f"{REF_TOL:g} (§10 基礎設施失敗; start a new scores file)")


def cmd_refpairs(args: argparse.Namespace) -> None:
    gd.assert_set_allowed("new82", PREREG, ACCEPT)
    out = fresh(Path(args.out))
    host = host_meta("refpairs", {**script_files(RERANK_STDIN), "ev_sel_out": EV_SCORES},
                     gd.load_new82())
    t0 = time.monotonic()
    lines, check = run_refcheck(host, err_log(out))
    report_time([r for r in lines if r.get("type") == "r"], time.monotonic() - t0)
    write_new_jsonl(out, [*lines, check])
    finish_refcheck(check, out)


# ------------------------------------------------------------------ encode

def select_ids(spec: str | None, qset: gd.QuestionSet) -> list[str]:
    ids = [s.strip() for s in spec.split(",") if s.strip()] if spec else list(qset.ids)
    bad = sorted(set(ids) - set(qset.ids))
    if bad or len(set(ids)) != len(ids) or not ids:
        raise gd.GdError(f"--ids must be distinct {qset.name} ids (unknown: {bad[:3]})")
    return ids


def cmd_encode(args: argparse.Namespace) -> None:
    gd.assert_set_allowed(args.set, PREREG, ACCEPT)
    out = fresh(Path(args.out))
    qset = gd.load_question_set(args.set)
    ids, by_id = select_ids(args.ids, qset), qset.by_id()
    items = [{"sid": q, "query": by_id[q].question} for q in ids]
    host = host_meta("encode", script_files(ENCODE_STDIN), qset, ids=ids,
                     ids_sha256=gd.ids_sha256(ids))
    lines: list[Record] = []
    sink = Sink("embedder", items, host, lines.append, decode_vector)
    script = build_script(ENCODE_STDIN.read_text(encoding="utf-8"), items)
    run_container(script, err_log(out), sink)
    sink.finish()
    write_new_jsonl(out, lines)
    print(f"encode {args.set}: {len(ids)} vectors -> {out}")
    if args.ref:
        check_against_ref(out, Path(args.ref))


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


# ------------------------------------------------------------------ CLI

def positive_int(text: str) -> int:
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return int(text)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encode", help="query vectors (encode_stdin.py)")
    enc.add_argument("--set", required=True)
    enc.add_argument("--ids", help="comma-separated question ids (default: the whole set)")
    enc.add_argument("--out", required=True)
    enc.add_argument("--ref", help="vectors jsonl to compare with (max|Δ| ≤ 1e-5)")
    rr = sub.add_parser("rerank", help="reranker scores of each question's pool union")
    rr.add_argument("--lists", required=True)
    rr.add_argument("--out", required=True)
    rr.add_argument("--set", help="question set (default: the lists.json meta 'set')")
    rr.add_argument("--chunk", type=positive_int, default=DEFAULT_CHUNK,
                    help="questions per container run")
    ref = sub.add_parser("refpairs", help="re-score the 32 EV reference pairs (§10)")
    ref.add_argument("--out", required=True)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    handler = {"encode": cmd_encode, "rerank": cmd_rerank, "refpairs": cmd_refpairs}[args.cmd]
    try:
        handler(args)
    except (gd.GdError, subprocess.CalledProcessError, OSError) as err:
        print(f"score.py {args.cmd}: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

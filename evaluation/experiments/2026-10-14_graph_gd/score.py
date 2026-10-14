"""Host runner for the container side of the GD experiment (prereg §3, §10).

Subcommands:
  encode   --set new82 [--ids a,b,...] --out V.jsonl [--ref REF.jsonl]
      Query vectors from encode_stdin.py. --ref compares each vector with REF (sid qid or
      'qid|Q', e.g. PN/encode_out.jsonl): max|Δ| must be ≤1e-5 (§3).
  rerank   --lists L.json --out S.jsonl [--set new82] [--arms C,GD] [--chunk N]
      Reranker scores (rerank_stdin.py) of each question's pool union D30[:20] ∪ the extra
      of every arm (or of the --arms ones, recorded in meta as host "arms"; E3 uses C,GD),
      in pid order, N questions per container run; then, in one more container run, the
      §10 reference pairs, appended as a "refcheck" line (|Δ|>1e-5 fails). Re-running
      resumes: questions the file holds are skipped, a cut last line is dropped, and a
      missing final refcheck is redone even when no question is left.
  rerank-w --lists L.json --scores S.jsonl --out W.jsonl [--ids a,b] [--chunk N]
      §3 W (逐窗重排): window-max scores (rerank_w_stdin.py) of each question's C∪GD pool,
      single-window passages taking their whole-passage score from S (the finished rerank
      file of the same lists, read with every resume check), then the refcheck line as in
      rerank. Lines and meta: _score_w.py. Resumes like rerank; --ids scores only those
      questions (a later run without it completes the file).
  refpairs --out R.jsonl
      The same 32 reference pairs (first (qid, pid) of EV/ev_sel_out.jsonl) on their own.

Outputs are JSON lines (formats in _score_io.py): per container run a meta line (the
container's own, checked against the gd_common pins and run settings before anything is
kept, plus "host" = gd.collect_meta with the scorer scripts' and the lists' sha256), then
{"type": "q", "sid", "vec_b64"}, {"type": "r", "sid", "scores": {pid: score}, "missing": [],
"elapsed_s"} or {"type": "w", "sid", "scores", "n_windows", "elapsed_s"} per question. Raw
outputs are never overwritten. Pin mismatches and
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
import _score_w as sw
import gd_common as gd
from _score_io import (  # noqa: F401  (the format helpers are re-exported for tests)
    EV_SCORES, N_REF_PAIRS, SCRIPT_NAMES, Record, Scan, Writer, arms_union, build_script,
    check_against_ref, check_score_record, compare_vectors, completed, decode_vector,
    drop_cut_tail, fresh, line_appender, lists_arms, load_lists, needs_refcheck, parse_arms,
    pool_union, positive_int, reference_pairs, refcheck_record, refpair_items, report_time,
    scan_jsonl, select_ids, write_new_jsonl)

SCRIPT = Path(__file__).resolve()
IO_MODULE = Path(_score_io.__file__).resolve()
W_MODULE = Path(sw.__file__).resolve()
ENCODE_STDIN = SCRIPT.parent / "encode_stdin.py"
RERANK_STDIN = SCRIPT.parent / "rerank_stdin.py"
RERANK_W_STDIN = SCRIPT.parent / "rerank_w_stdin.py"
PREREG = gd.PREREG_PATH      # what the appendix guard reads (tests point it elsewhere)
ACCEPT = gd.ACCEPT_DIR       # where the guard looks for accept_a.json / accept_b.json
DEFAULT_CHUNK = 10           # questions per container run (one model load each)
REF_TOL = gd.DRIFT_TOL       # §10 reference-pair drift


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


def script_files(*stdin_scripts: Path) -> dict[str, Path]:
    """The scorer's own files hashed into every meta line: score.py and the modules it loads
    (SCRIPT_NAMES / W_SCRIPT_NAMES order), then the container scripts the run feeds."""
    return {"score.py": SCRIPT, "_score_io.py": IO_MODULE, "_score_w.py": W_MODULE,
            **{path.name: path for path in stdin_scripts}}


def script_shas() -> dict[str, str]:
    """sha256 of SCRIPT_NAMES, as a scores file must record them."""
    files = script_files(RERANK_STDIN)
    return {name: gd.file_sha256(files[name]) for name in SCRIPT_NAMES}


def w_script_files() -> dict[str, Path]:
    """W runs feed rerank_w_stdin.py, and rerank_stdin.py for the §10 reference pairs."""
    return script_files(RERANK_W_STDIN, RERANK_STDIN)


def w_script_shas() -> dict[str, str]:
    """sha256 of W_SCRIPT_NAMES, as a W file must record them."""
    return {name: gd.file_sha256(path) for name, path in w_script_files().items()}


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


# ------------------------------------------------------------------ rerank

def guarded_lists(lists_path: Path, cli_set: str | None) -> tuple[gd.QuestionSet, dict]:
    """(question set, lists) after the confirmation-set guard; lists may hold a subset."""
    name, lists = load_lists(lists_path, cli_set)
    gd.assert_set_allowed(name, PREREG, ACCEPT)
    qset = gd.load_question_set(name)
    unknown = sorted(set(lists) - set(qset.ids))
    if unknown:
        raise gd.IntegrityError(f"{lists_path} has questions outside {name}: {unknown[:3]}")
    return qset, lists


def rerank_plan(lists_path: Path, cli_set: str | None, arms_spec: str | None = None
                ) -> tuple[gd.QuestionSet, dict, str, tuple[str, ...]]:
    """(question set, qid -> pool union of the arms in set order, lists content sha256, arms)."""
    qset, lists = guarded_lists(lists_path, cli_set)
    arms = parse_arms(arms_spec) or lists_arms(lists)
    expected = {q: arms_union(q, lists[q], arms) for q in qset.ids if q in lists}
    return qset, expected, gd.lists_sha256(lists), arms


def cmd_rerank(args: argparse.Namespace) -> None:
    lists_path, out = Path(args.lists), Path(args.out)
    qset, expected, lists_sha, arms = rerank_plan(lists_path, args.set, args.arms)
    scan = scan_jsonl(out)
    done = completed(scan.records, expected, lists_sha, script_shas(), arms)
    todo = [q for q in expected if q not in done]
    print(f"rerank {qset.name} arms {','.join(arms)}: {len(expected)}/{len(qset.ids)} questions "
          f"in lists, {len(done)} done, {len(todo)} to score "
          f"({sum(len(expected[q]) for q in todo)} pairs)")
    drop_cut_tail(scan, out)
    if not (todo or needs_refcheck(scan.records)):
        return
    host = host_meta("rerank", {**script_files(RERANK_STDIN), "lists": lists_path}, qset,
                     chunk_size=args.chunk, lists_sha256=lists_sha, arms=list(arms))
    by_id = qset.by_id()
    items = [{"sid": q, "query": by_id[q].question, "pids": list(expected[q])} for q in todo]
    t0 = time.monotonic()
    with open(out, "a", encoding="utf-8") as fh:
        append = line_appender(fh)
        lines = score_chunks(items, append, host, err_log(out), args.chunk)
        report_time(lines, time.monotonic() - t0)
        _, check = run_refcheck(host, err_log(out))
        append(check)
    finish_refcheck(check, out)


# ------------------------------------------------------------------ rerank-w (§3 W)

def score_w_chunks(items: Sequence[Record], put: Writer, host: Record, err: Path,
                   chunk: int) -> list[Record]:
    """W-score `items`, `chunk` questions per container run; returns the container lines."""
    body = RERANK_W_STDIN.read_text(encoding="utf-8")
    out: list[Record] = []
    for start in range(0, len(items), chunk):
        part = items[start:start + chunk]
        sink = Sink("reranker", part, host, put, sw.check_w_container_line)
        run_container(build_script(body, part), err, sink)
        out += sink.finish()
        print(f"  W-scored {start + len(part)}/{len(items)} questions, "
              f"{sum(map(sw.scored_windows, out))} windows", flush=True)
    return out


def cmd_rerank_w(args: argparse.Namespace) -> None:
    lists_path, scores_path, out = Path(args.lists), Path(args.scores), Path(args.out)
    qset, lists = guarded_lists(lists_path, args.set)
    lists_sha = gd.lists_sha256(lists)
    whole = sw.read_whole_scores(scores_path, qset, lists, lists_sha)
    ids = [q for q in qset.ids if q in lists]
    expected = sw.w_pools(lists, ids)
    wanted = set(select_ids(args.ids, qset) if args.ids else ids)
    outside = sorted(wanted - set(ids))
    if outside:
        raise gd.GdError(f"--ids {outside[:3]} are not in {lists_path}")
    scan = scan_jsonl(out)
    done = sw.completed_w(scan.records, expected, whole, lists_sha, w_script_shas())
    todo = [q for q in ids if q in wanted and q not in done]      # set order
    print(f"rerank-w {qset.name}: {len(ids)} questions in lists, {len(done)} done, {len(todo)} "
          f"to W-score ({sum(len(expected[q]) for q in todo)} passages)")
    drop_cut_tail(scan, out)
    if not (todo or needs_refcheck(scan.records, sw.W_LINE)):
        return
    host = host_meta(sw.W_KIND, {**w_script_files(), "lists": lists_path, "scores": scores_path},
                     qset, chunk_size=args.chunk, lists_sha256=lists_sha,
                     scores_sha256=whole.content_sha256, arms=list(sw.W_ARMS))
    by_id = qset.by_id()
    items = [{"sid": q, "query": by_id[q].question, "pids": list(expected[q])} for q in todo]
    t0 = time.monotonic()
    with open(out, "a", encoding="utf-8") as fh:
        append = line_appender(fh)
        lines = score_w_chunks(items, sw.w_writer(append, expected, whole), host, err_log(out),
                               args.chunk)
        sw.report_w_time(lines, time.monotonic() - t0)
        _, check = run_refcheck(host, err_log(out))
        append(check)
    finish_refcheck(check, out)


# ------------------------------------------------------------------ refpairs (§10)

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


# ------------------------------------------------------------------ CLI

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
    rr.add_argument("--arms", help="comma-separated arms whose extra is scored (default: every arm)")
    rr.add_argument("--chunk", type=positive_int, default=DEFAULT_CHUNK,
                    help="questions per container run")
    rw = sub.add_parser("rerank-w", help="§3 W window-max scores of each question's C∪GD pool")
    rw.add_argument("--lists", required=True)
    rw.add_argument("--scores", required=True, help="the finished rerank file of these lists")
    rw.add_argument("--out", required=True)
    rw.add_argument("--set", help="question set (default: the lists.json meta 'set')")
    rw.add_argument("--ids", help="comma-separated question ids to W-score now (default: all)")
    rw.add_argument("--chunk", type=positive_int, default=DEFAULT_CHUNK,
                    help="questions per container run")
    ref = sub.add_parser("refpairs", help="re-score the 32 EV reference pairs (§10)")
    ref.add_argument("--out", required=True)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    handler = {"encode": cmd_encode, "rerank": cmd_rerank, "rerank-w": cmd_rerank_w,
               "refpairs": cmd_refpairs}[args.cmd]
    try:
        handler(args)
    except (gd.GdError, subprocess.CalledProcessError, OSError, json.JSONDecodeError) as err:
        print(f"score.py {args.cmd}: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The single claude ledger of the GEN confirmation set (prereg §3.9, §8.2): every agent run of every root.

Kinds and where their runs live (all under the out root, store reports/gen_confirm_20261020/):

* probe  PROBE_ROOT/<n>/: one sub-root per CLI probe invocation (prereg §8.1-2: at most PROBE_MAX_RUNS of them,
         PROBE_CAP_USD in all)
* qset   QSET_ROOT and below (p1/, p2/: the blind P1/P2 writers, QSET_CAP_USD in all)
* ho     HO_ROOT and below (drafts, audits, fixes and Kay's revisions, in whatever sub-roots the HO runner uses)

A run root is any directory under those bases holding transcripts/<run>.jsonl, reserve/<run>.json or
prompts/<run>.json (a claude_g launch record, which names budget_usd). A run counts its result event's
total_cost_usd; a run without one (still running, crashed, or reserved and never started) counts the cap its
reservation names, else its prompts record's, else the kind's largest job cap, so it is never cheaper than its cap
(§8.2: 每次開跑前先保留).

``check(job_cap, kind)`` (§3.9: 花費＋該 job 上限 ≤ 49 才開跑) refuses unless spent + job_cap ≤ USD_CAP −
START_MARGIN_USD over every root, and per kind: probe spent + job_cap ≤ PROBE_CAP_USD and the run's root one of
at most PROBE_MAX_RUNS invocation roots; qset spent + job_cap ≤ QSET_CAP_USD. A job cap must be positive and at most
the kind's largest job cap (ho JOB_CAP_USD, qset QSET_JOB_CAP_USD, probe PROBE_CAP_USD). ``reserve`` takes the
same check and writes the reservation under one lock (a threading lock per out root inside a process, an
fcntl.flock on <out root>/ledger.lock across processes: HO and qset may run as separate processes), so parallel
jobs never overrun a cap together; it refuses a root outside its kind's base and a run id already used.
``release`` drops a reservation only when nothing ran (no transcript, no prompts record).

Read-only views: ``snapshot()`` (per run, per root, per kind, total), ``spent_by_root()`` and ``spent_of(runs)``
(K-P, §8.1-7: pilot spend per opened slot, from the pilot's run ids or its own sub-root); ``write_snapshot()``
writes ledger.json under the same lock. A transcript torn mid-line (even mid-character) never blocks the ledger:
the torn line is skipped and the run counts its cap. Writes go through g_common.write_json (tests use tmp out
roots). Nothing here launches an agent.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import g_common as GC
from hog_common import BudgetRefused, HoError, now, read_json, write_json

KINDS = ("probe", "qset", "ho")
BASES = {"probe": GC.PROBE_ROOT.relative_to(GC.OUT_ROOT), "qset": GC.QSET_ROOT.relative_to(GC.OUT_ROOT),
         "ho": GC.HO_ROOT.relative_to(GC.OUT_ROOT)}
KIND_JOB_CAP = GC.KIND_JOB_CAP_USD                   # the kind's largest job cap
SPEND_LIMIT_USD = GC.SPEND_LIMIT_USD                 # 49
LOCK_NAME, SNAPSHOT_NAME = GC.LEDGER_LOCK, GC.LEDGER_SNAPSHOT
RUN_DIRS = ("transcripts", "reserve", "prompts")
SKIP_DIRS = frozenset(RUN_DIRS) | {"bin", "hookbin", "clibin"}
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")
EPS = 1e-9

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_RESULT_CACHE: dict[tuple[str, int, int], float | None] = {}


@dataclass(frozen=True)
class RunCost:
    root: str                   # relative to the out root, e.g. "ho", "qset/p1", "probe/1"
    run_id: str
    kind: str
    cost_usd: float
    source: str                 # result | reserve | prompts | cap_assumed

    @property
    def key(self) -> str:
        return f"{self.root}/{self.run_id}"


def result_cost(transcript: Path) -> float | None:
    """total_cost_usd of the transcript's last result event (None without one); cached on size and mtime. A line
    torn mid-JSON or mid-character (a killed run, a full disk, a run still writing) is skipped, never raised."""
    st = transcript.stat()
    key = (str(transcript), st.st_size, st.st_mtime_ns)
    if key not in _RESULT_CACHE:
        cost = None
        for line in reversed(transcript.read_bytes().decode("utf-8", errors="replace").splitlines()):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("type") == "result":
                c = e.get("total_cost_usd")
                cost = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None
                break
        _RESULT_CACHE[key] = cost
    return _RESULT_CACHE[key]


def budget_of(path: Path) -> float | None:
    """budget_usd of a reservation or prompts record (None when absent or unreadable)."""
    try:
        b = read_json(path).get("budget_usd")
    except (OSError, ValueError, AttributeError):
        return None
    return float(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else None


def run_ids(root: Path) -> set[str]:
    """Run ids of one run root: transcripts, reservations, and prompts records that name a budget."""
    root = Path(root)
    ids = {p.stem for p in (root / "transcripts").glob("*.jsonl")} | {p.stem for p in (root / "reserve").glob("*.json")}
    ids |= {p.stem for p in (root / "prompts").glob("*.json") if budget_of(p) is not None}
    return ids


def has_run(root: Path, run_id: str) -> bool:
    root = Path(root)
    return any(p.exists() for p in (root / "transcripts" / f"{run_id}.jsonl", root / "reserve" / f"{run_id}.json",
                                    root / "prompts" / f"{run_id}.json"))


def run_cost(root: Path, run_id: str, kind: str) -> tuple[float, str]:
    root = Path(root)
    t = root / "transcripts" / f"{run_id}.jsonl"
    if t.is_file():
        cost = result_cost(t)
        if cost is not None:
            return cost, "result"
    for src in ("reserve", "prompts"):
        b = budget_of(root / src / f"{run_id}.json")
        if b is not None:
            return b, src
    return KIND_JOB_CAP[kind], "cap_assumed"


class Ledger:
    """The ledger of one out root (the store's by default; tests use a tmp one)."""

    def __init__(self, out_root: Path | str = GC.OUT_ROOT):
        self.out_root = Path(out_root)

    # ---------------------------------------------------------------- layout
    def base(self, kind: str) -> Path:
        if kind not in KINDS:
            raise HoError(f"ledger kind {kind!r} is not one of {KINDS}")
        return self.out_root / BASES[kind]

    def run_roots(self, kind: str) -> list[Path]:
        base, out = self.base(kind), []
        if not base.is_dir():
            return out
        for d, subdirs, _ in os.walk(base):
            if any(s in RUN_DIRS for s in subdirs):
                out.append(Path(d))
            subdirs[:] = sorted(s for s in subdirs if s not in SKIP_DIRS)
        return sorted(out)

    def kind_of(self, root: Path) -> str:
        """The kind whose base holds `root`; a probe root must be a direct sub-root of PROBE_ROOT."""
        r = Path(root).resolve()
        for kind in KINDS:
            b = self.base(kind).resolve()
            if (r.parent == b) if kind == "probe" else (r == b or b in r.parents):
                return kind
        raise HoError(f"run root {root} is not under a ledger base of {self.out_root} "
                      f"({sorted(map(str, BASES.values()))})")

    def rel(self, root: Path) -> str:
        return Path(root).resolve().relative_to(self.out_root.resolve()).as_posix()

    # ---------------------------------------------------------------- reading
    def costs(self) -> list[RunCost]:
        out = []
        for kind in KINDS:
            for root in self.run_roots(kind):
                for run in sorted(run_ids(root)):
                    cost, src = run_cost(root, run, kind)
                    out.append(RunCost(self.rel(root), run, kind, round(cost, 6), src))
        return out

    def probe_invocations(self, costs: Iterable[RunCost] | None = None) -> list[str]:
        return sorted({c.root for c in (self.costs() if costs is None else costs) if c.kind == "probe"})

    def snapshot(self) -> dict[str, Any]:
        costs = self.costs()
        by_root: dict[str, float] = {}
        for c in costs:
            by_root[c.root] = by_root.get(c.root, 0.0) + c.cost_usd
        by_kind = {k: round(sum(c.cost_usd for c in costs if c.kind == k), 6) for k in KINDS}
        return {"runs": {c.key: {"kind": c.kind, "cost_usd": c.cost_usd, "source": c.source} for c in costs},
                "by_root": {k: round(v, 6) for k, v in sorted(by_root.items())}, "by_kind": by_kind,
                "total_usd": round(sum(by_kind.values()), 6), "cap_usd": GC.USD_CAP, "limit_usd": SPEND_LIMIT_USD,
                "probe_invocations": self.probe_invocations(costs), "probe_cap_usd": GC.PROBE_CAP_USD,
                "probe_max_runs": GC.PROBE_MAX_RUNS, "qset_cap_usd": GC.QSET_CAP_USD, "utc": now()}

    def spent(self) -> float:
        return round(sum(c.cost_usd for c in self.costs()), 6)

    def spent_by_root(self) -> dict[str, float]:
        return dict(self.snapshot()["by_root"])

    def spent_of(self, runs: Iterable[tuple[Path | str, str]]) -> float:
        """Total of the named runs, (root, run_id) pairs; a run nobody reserved or launched counts 0."""
        idx = {c.key: c.cost_usd for c in self.costs()}
        keys = [f"{self.rel(Path(r) if Path(r).is_absolute() else self.out_root / r)}/{rid}" for r, rid in runs]
        return round(sum(idx.get(k, 0.0) for k in keys), 6)

    def write_snapshot(self) -> Path:
        """ledger.json, written under the budget lock (write_json's tmp name is shared by every writer)."""
        with self.locked():
            return write_json(self.out_root / SNAPSHOT_NAME, self.snapshot())

    # ---------------------------------------------------------------- the budget lock
    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        key = str(self.out_root.resolve())
        with _LOCKS_GUARD:
            lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
        with lock:
            path = GC.writable(self.out_root / LOCK_NAME)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o664)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)                        # closing the descriptor drops the flock

    def _refusal(self, costs: list[RunCost], job_cap: float, kind: str, root: Path | None) -> str | None:
        number = isinstance(job_cap, (int, float)) and not isinstance(job_cap, bool)
        if not (number and 0 < job_cap <= KIND_JOB_CAP[kind] + EPS):
            raise HoError(f"job cap {job_cap!r} is not in (0, {KIND_JOB_CAP[kind]:g}] for kind {kind}")
        total = sum(c.cost_usd for c in costs)
        if total + job_cap > SPEND_LIMIT_USD + EPS:
            return (f"已花 {total:.3f} + 本 job 上限 {job_cap:g} > {SPEND_LIMIT_USD:g} USD"
                    f"（硬上限 {GC.USD_CAP:g} − 餘裕 {GC.START_MARGIN_USD:g}），不啟動")
        sub = sum(c.cost_usd for c in costs if c.kind == kind)
        if kind == "probe":
            inv = self.probe_invocations(costs)
            if root is not None and self.rel(root) not in inv and len(inv) >= GC.PROBE_MAX_RUNS:
                return f"probe 已跑 {len(inv)} 次（上限 {GC.PROBE_MAX_RUNS}），不啟動"
            if sub + job_cap > GC.PROBE_CAP_USD + EPS:
                return f"probe 已花 {sub:.3f} + 上限 {job_cap:g} > {GC.PROBE_CAP_USD:g} USD，不啟動"
        if kind == "qset" and sub + job_cap > GC.QSET_CAP_USD + EPS:
            return f"qset 已花 {sub:.3f} + 上限 {job_cap:g} > {GC.QSET_CAP_USD:g} USD，不啟動"
        return None

    def _root_kind(self, root: Path | None, kind: str) -> None:
        if root is not None and self.kind_of(root) != kind:
            raise HoError(f"run root {root} belongs to kind {self.kind_of(root)}, not {kind}")

    def check(self, job_cap: float, kind: str, root: Path | None = None) -> float:
        """The amount spent, when a job of this cap may start (BudgetRefused otherwise); reserves nothing."""
        self.base(kind)
        self._root_kind(root, kind)
        with self.locked():
            costs = self.costs()
            why = self._refusal(costs, job_cap, kind, root)
        if why:
            raise BudgetRefused(why)
        return round(sum(c.cost_usd for c in costs), 6)

    def reserve(self, kind: str, root: Path, run_id: str, job_cap: float) -> Path:
        """check() and the reservation <root>/reserve/<run_id>.json, atomically under the budget lock."""
        if not (isinstance(run_id, str) and RUN_ID.fullmatch(run_id)):
            raise HoError(f"run id {run_id!r} is not a plain id")
        self.base(kind)
        self._root_kind(root, kind)
        with self.locked():
            if has_run(root, run_id):
                raise HoError(f"run id {run_id} already exists in {self.rel(root)}")
            costs = self.costs()
            why = self._refusal(costs, job_cap, kind, Path(root))
            if why:
                raise BudgetRefused(why)
            return write_json(Path(root) / "reserve" / f"{run_id}.json",
                              {"run_id": run_id, "kind": kind, "root": self.rel(root), "budget_usd": job_cap,
                               "spent_before_usd": round(sum(c.cost_usd for c in costs), 6), "pid": os.getpid(),
                               "at": now()})

    def release(self, root: Path, run_id: str) -> bool:
        """Drop a reservation whose run never started (no transcript, no prompts record); True when dropped."""
        root = Path(root)
        with self.locked():
            if (root / "transcripts" / f"{run_id}.jsonl").exists() or (root / "prompts" / f"{run_id}.json").exists():
                return False
            path = root / "reserve" / f"{run_id}.json"
            if not path.is_file():
                return False
            GC.writable(path).unlink()
            return True


def ledger(out_root: Path | str = GC.OUT_ROOT) -> Ledger:
    return Ledger(out_root)


def check(job_cap: float, kind: str, root: Path | None = None, out_root: Path | str = GC.OUT_ROOT) -> float:
    return Ledger(out_root).check(job_cap, kind, root)


def reserve(kind: str, root: Path, run_id: str, job_cap: float, out_root: Path | str = GC.OUT_ROOT) -> Path:
    return Ledger(out_root).reserve(kind, root, run_id, job_cap)


def release(root: Path, run_id: str, out_root: Path | str = GC.OUT_ROOT) -> bool:
    return Ledger(out_root).release(root, run_id)


def snapshot(out_root: Path | str = GC.OUT_ROOT) -> dict[str, Any]:
    return Ledger(out_root).snapshot()


def spent_by_root(out_root: Path | str = GC.OUT_ROOT) -> dict[str, float]:
    return Ledger(out_root).spent_by_root()


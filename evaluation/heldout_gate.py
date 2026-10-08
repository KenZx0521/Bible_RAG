#!/usr/bin/env python3
"""G-HELDOUT, as pre-registered in experiments/2026-10-09_r2/prereg.md (scoring: src/heldout.py).

  collect  ask BACKEND_URL every held-out question (backend defaults,
           retrieval_only, top-k 5) and save what the score needs: route_used,
           event_registry_events, intent, sources (id, passage_id, strategy) and
           the /health build id, which must be --build. Exit 1 when any answer
           is invalid (HTTP error or infrastructure failure): rerun the arm with
           --overwrite (prereg: infrastructure failures only, at most twice).
  score    judge the R1 and R2 runs against their builds' contract
           event_registry.json and routing_lexicon.json (<contracts-root>/<build>/,
           the manifest must name the build) → report JSON.

Exit codes of score: 0 PASS, 1 FAIL, 3 SIGNOFF (R2 triggered < 30 questions:
descriptive, Kay signs off), 2 input error (refused before judging).

Usage (from evaluation/):
    BACKEND_URL=http://localhost:8002 .venv/bin/python heldout_gate.py collect \\
        --arm R1 --build b20261008_6daa4f31 --out experiments/2026-10-09_r2/heldout_R1.json
    BACKEND_URL=http://localhost:<R2 port> .venv/bin/python heldout_gate.py collect \\
        --arm R2 --build <R2 build> --out experiments/2026-10-09_r2/heldout_R2.json
    .venv/bin/python heldout_gate.py score --r1 experiments/2026-10-09_r2/heldout_R1.json \\
        --r2 experiments/2026-10-09_r2/heldout_R2.json \\
        --out experiments/2026-10-09_r2/gate_heldout.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import heldout  # noqa: E402
from src.config import settings  # noqa: E402
from src.provenance import from_health  # noqa: E402

EXIT_PASS, EXIT_FAIL, EXIT_INPUT, EXIT_SIGNOFF = 0, 1, 2, 3
EXIT_OF = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "SIGNOFF": EXIT_SIGNOFF}
TIMEOUT = 600.0


def _check_out(out: Path, inputs: Sequence[Path], overwrite: bool) -> None:
    for path in inputs:
        if out.exists() and out.resolve() == path.resolve():
            raise heldout.HeldoutError(f"--out {out} is an input file")
    if out.exists() and not overwrite:
        raise heldout.HeldoutError(f"{out} exists; pass --overwrite to replace it")


# ---------------------------------------------------------------- collect

async def _ask(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str,
               item: heldout.Item) -> dict:
    async with sem:
        try:
            resp = await client.post(f"{url}/api/v1/query",
                                     json={"question": item.question, **heldout.REQUEST})
        except httpx.HTTPError as exc:
            return heldout.response_row(item.id, None, None, repr(exc)[:300])
    try:
        body = resp.json() if resp.status_code == 200 else resp.text[:300]
    except ValueError:
        body = resp.text[:300]
    return heldout.response_row(item.id, resp.status_code, body)


async def collect(items: Sequence[heldout.Item], url: str, build: str, concurrency: int = 3,
                  transport: httpx.AsyncBaseTransport | None = None) -> tuple[dict, list[dict]]:
    """(health provenance meta, rows in item order); refuses a backend serving another build."""
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
        health = await client.get(f"{url}/api/v1/health")
        health.raise_for_status()
        prov = from_health(health.json())
        if prov.data_build_id != build:
            raise heldout.HeldoutError(f"{url} serves {prov.data_build_id}, not --build {build}")
        sem = asyncio.Semaphore(concurrency)
        rows = await asyncio.gather(*(_ask(client, sem, url, item) for item in items))
    return prov.meta(), list(rows)


def run_collect(args: argparse.Namespace, transport=None) -> int:
    data = heldout.load_heldout(args.heldout)
    _check_out(args.out, [args.heldout], args.overwrite)
    url = settings.backend_url
    prov, rows = asyncio.run(collect(data.items, url, args.build, args.concurrency, transport))
    run = {"schema": heldout.RUN_SCHEMA,
           "meta": {"arm": args.arm, "backend_url": url, **prov, "heldout_path": str(args.heldout),
                    "heldout_sha256": data.sha256, "request": dict(heldout.REQUEST),
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
           "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    invalid = {r["id"]: r["invalid"] for r in rows if r["invalid"]}
    triggered = sum(bool(r.get("event_registry_events")) for r in rows)
    print(f"{args.arm} {prov['data_build_id']}: {len(rows)} questions, {triggered} triggered, "
          f"invalid {len(invalid)} {invalid or ''}\nsaved → {args.out}")
    return EXIT_FAIL if invalid else EXIT_PASS


# ---------------------------------------------------------------- score

def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise heldout.HeldoutError(f"{path}: not a JSON object")
    return data


def load_contracts(root: Path, run: dict, arm: str) -> tuple[dict, dict]:
    """(event_registry.json, routing_lexicon.json) of the run's build; its manifest must name it."""
    build = (run.get("meta") or {}).get("data_build_id")
    if not isinstance(build, str) or not build:
        raise heldout.HeldoutError(f"{arm}: meta has no data_build_id")
    directory = root / build
    named = _read_json(directory / "manifest.json").get("build_id")
    if named != build:
        raise heldout.HeldoutError(f"{directory}/manifest.json names {named}, not {build}")
    return (_read_json(directory / "event_registry.json"),
            _read_json(directory / "routing_lexicon.json"))


def run_score(args: argparse.Namespace) -> dict:
    data = heldout.load_heldout(args.heldout)
    paths = {"R1": args.r1, "R2": args.r2}
    _check_out(args.out, [*paths.values(), args.heldout], args.overwrite)
    runs = {arm: _read_json(path) for arm, path in paths.items()}
    contracts = {arm: load_contracts(args.contracts_root, run, arm) for arm, run in runs.items()}
    report = heldout.heldout_gate(runs, contracts, data)
    return {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "inputs": {**{arm: str(p) for arm, p in paths.items()},
                       "heldout": str(args.heldout), "contracts_root": str(args.contracts_root)},
            **report}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def print_report(report: dict) -> None:
    print("G-HELDOUT (held-out event questions), R2 against R1")
    for arm, s in report["arms"].items():
        m = s["misses"]
        print(f"  {arm} {s['data_build_id']}: triggered {s['n_triggered']}/{s['n_items']}, "
              f"correct {s['n_correct']}, precision {_pct(s['precision'])}; recall "
              f"{s['recall']['n_correct']}/{s['recall']['n_positive']} "
              f"(string hit {s['string_hit_recall']['n_hit']}); misses trigger "
              f"{len(m['trigger'])} route {len(m['route'])} wrong_event {len(m['wrong_event'])}")
        if s["errors"]:
            print(f"     errors: {s['errors']}")
    c = report["criteria"]
    ni = c["noninferiority"]
    print(f"precision (R2, n={c['n_triggered']['n']}, needs ≥ {heldout.MIN_TRIGGERS}) "
          f"{_pct(c['precision']['value'])} ≥ {heldout.MIN_PRECISION}")
    print(f"paired: R2 lose/R1 win {len(ni['r2_lose_r1_win'])} − R2 win/R1 lose "
          f"{len(ni['r2_win_r1_lose'])} = {ni['net_loss']} ≤ {heldout.MAX_NET_LOSS}")
    print(f"\nG-HELDOUT: {report['verdict']}")
    for reason in report["fail_reasons"]:
        print(f"  - {reason}")


# ---------------------------------------------------------------- CLI

def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="ask BACKEND_URL every held-out question")
    c.add_argument("--arm", choices=heldout.ARMS, required=True)
    c.add_argument("--build", required=True, help="the build the arm must serve (/health)")
    c.add_argument("--concurrency", type=int, default=3)
    s = sub.add_parser("score", help="judge the R1 and R2 runs")
    s.add_argument("--r1", type=Path, required=True, help="the R1 arm's collect output")
    s.add_argument("--r2", type=Path, required=True, help="the R2 arm's collect output")
    s.add_argument("--contracts-root", type=Path, default=settings.rag_store / "contracts")
    for p in (c, s):
        p.add_argument("--heldout", type=Path, default=heldout.HELDOUT_PATH)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, transport=None) -> int:
    args = _parse_args(argv)
    try:
        if args.cmd == "collect":
            return run_collect(args, transport)
        report = run_score(args)
    except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
        # HeldoutError, ProvenanceError, JSON, a contract or run without a required field
        print(f"error: {exc!r}" if isinstance(exc, KeyError) else f"error: {exc}",
              file=sys.stderr)
        return EXIT_INPUT
    print_report(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved → {args.out}")
    return EXIT_OF[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())

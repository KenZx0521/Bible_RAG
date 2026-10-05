#!/usr/bin/env python3
"""KG quality gate: hard checks, ratcheted records and warnings (plan §3.6).

Context (docs/records/2026-10-04_kg_data_layer_fix_plan.md §3.6–3.7): the KG
data-layer fix rebuilds into staging and promotes only after this gate passes.
Every defect family from the 2026-10 audit has a measurable check here, so a
rebuild cannot silently regress (unfixed EV-06 would drop the event registry
from 33 to 31 events) and each fix batch can show its effect as a number.
The checks live in scripts/kg_validate/; this file is the CLI plus D1.

Modes:
  --live --target prod|staging   read-only projection of a running Neo4j
                                 (store selection and its guards: check_identity.resolve_target)
  --snapshot DIR                 offline JSONL snapshot (format below)
Both modes build the same in-memory graph and run the same check code, so a
snapshot scores exactly what the graph loaded from it would. --dump-snapshot
writes a live graph in snapshot format, which is how that parity is tested.
Live Neo4j holds one row per MENTIONS edge, not every occurrence: readings
that need occurrences (R3's all_forms_* metrics, R9) are n/a there and on its
dump, and have baselines of their own that only a full snapshot fills.

Severity per check comes from config/kg_quality_baseline/ (index.json lists
one file per check family; the gate reads them merged, and --ratchet/--accept
write each check back to its own file):
  hard    each metric must meet its target            -> exit 1
  record  each metric must not regress past baseline  -> exit 2
  warn    report only (W: label/relationship counts drifting > ±tolerance_pct)
A metric's own "severity" (hard|record) overrides its check's for that metric,
e.g. a record ratchet inside a hard check: it regresses (exit 2), never fails.
Batch 0 hard checks are H1, H2, H7 and D1; `hard_from` records the batch at
which each record check is planned to become hard. A check that raised
(error), or a metric that came back None without a declared reason
(unmeasured), exits 1 whatever its severity: a check that did not run never
passes. Declared n/a (D1 and H5 on a snapshot; R3 all-forms and R9 without
occurrence rows, R9 also when no row carries a text_id) is reported with its
reason, not failed.

--ratchet moves stored baselines only toward improvement (and fills null
ones); a regressed metric keeps its old baseline and the run exits 2. Metrics
with direction "equal" (H10's Event-MENTIONS fingerprint) never move by
ratchet: an intentional change is approved with --accept ID (it cannot bypass
a hard target, only the stored record value). Direction "subset" (PROBES
.failing, R6.failing_probes) stores the failing probe ids: any id outside the
stored set is a regression even when the count is unchanged, and --ratchet
only removes ids. Their counts (failures, probe_failures) carry count_of and
are always stored as len(ids). H7's sha target is read from config/step0_sha.json
(--step0-sha), the file check_step0.py records, and is never copied here.

Snapshot format kg_snapshot/v1 (JSONL = one object per line). Every file is
required; --allow-partial scores an incomplete one with the checks that read
a missing file reported n/a, and refuses --ratchet/--accept:
  manifest.json           format, embedding_queue_sha256?, constraints? [{label, property, type}],
                          position_base? ("full_text" | "body"), mentions_granularity?
                          ("occurrence", default | "edge": one row per edge, as --dump-snapshot writes)
  entities.jsonl          entity_id, labels | type, canonical_name, aliases, description
  mentions.jsonl          one row per mention occurrence, in load order: source_label (Pericope|Chunk),
                          source_id, entity_id, text_span, start_pos, end_pos, source_region?,
                          text_id? (embedding_queue item the positions index), source?, curated?.
                          Legacy entity_mentions.jsonl rows (source_type pericope|chunk|verse) are
                          mapped like import_neo4j: a verse becomes its parent Pericope. Rows collapse
                          to one MENTIONS edge per (label, source, entity); the first row wins, as the
                          import's MERGE does. R3's all-forms reading and R9 read every row.
  relations.jsonl         head_id, relation | type, tail_id, source_pericope_id, extraction_phase,
                          notes, curated?, backfilled?
  cross_references.jsonl  source_id, target_id, source, votes, curated?, tsk?, source_verses?, target_verses?
  pericopes.jsonl         id, book_id, verse_range        chunks.jsonl  id, pericope_id
  books.jsonl             id, name
Text checks (R2, R9) read --embedding-queue (output/embedding_queue.jsonl), the K0
artifact whose sha H7 pins.

Usage (from the project root):
    scripts/.venv/bin/python scripts/validate_kg.py --live --target prod
    scripts/.venv/bin/python scripts/validate_kg.py --live --target staging
    scripts/.venv/bin/python scripts/validate_kg.py --snapshot output/kg --json
    scripts/.venv/bin/python scripts/validate_kg.py --live --target prod --ratchet

Exit code: 0 pass, 1 failure (hard target, error or unmeasured), 2 ratchet
regression (a failure wins).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))

from check_identity import Target, open_neo4j, resolve_target  # noqa: E402,F401  (re-exported)
from kg_validate.gate import apply_ratchet, evaluate, external_targets, print_report  # noqa: E402
from kg_validate.model import (  # noqa: E402,F401  (re-exported: the gate's public surface)
    KG,
    SnapshotError,
    XRef,
    load_live,
    load_snapshot,
    write_snapshot,
)
from kg_validate.registry import (  # noqa: E402,F401
    CHECKS,
    DEFAULT_EMBEDDING_QUEUE,
    CheckResult,
    Context,
    check,
    load_baseline,
    load_probes,
    run_checks,
    save_baseline,
)
from kg_validate.checks_probes import evaluate_probes  # noqa: E402,F401

DEFAULT_BASELINE = _PROJECT_ROOT / "config" / "kg_quality_baseline"
DEFAULT_PROBES = _PROJECT_ROOT / "config" / "kg_probes.yaml"
DEFAULT_STEP0_SHA = _PROJECT_ROOT / "config" / "step0_sha.json"
EXPORT_EVENT_REGISTRY = _SCRIPT_DIR / "export_event_registry.py"


# D1 is defined here, next to the subprocess it runs, so the CLI owns the one
# place the gate starts another script (tests replace _run_registry_check).
def _run_registry_check(cmd: list[str], env: dict) -> tuple[int, str]:
    proc = subprocess.run(cmd, env=env, cwd=_PROJECT_ROOT, capture_output=True, text=True, timeout=900)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


@check("D1", external=True)
def check_d1(kg: KG, ctx: Context) -> CheckResult:
    if kg.mode != "live":
        return CheckResult({"drift": None}, {"skipped": "export_event_registry --check reads live Neo4j"},
                           not_applicable={"drift": "snapshot mode: export_event_registry --check reads live Neo4j"})
    if ctx.target is None:
        return CheckResult({"drift": None}, {"skipped": "no live target"})
    # load_dotenv in the child does not override an existing variable, so the
    # target URI set here wins over .env's prod URI.
    env = {**os.environ, "NEO4J_URI": ctx.target.neo4j_uri, "NEO4J_USER": ctx.target.neo4j_user,
           "NEO4J_PASSWORD": ctx.target.neo4j_password}
    code, output = _run_registry_check([sys.executable, str(EXPORT_EVENT_REGISTRY), "--check"], env)
    return CheckResult({"drift": 0 if code == 0 else 1}, {"exit_code": code, "output": output[-500:]})


def _read_live(target: Target, name: str) -> KG:
    driver = open_neo4j(target)
    try:
        # fail fast: execute_read would retry a refused connection for ~30 s
        driver.verify_connectivity()
        return load_live(driver, origin=f"live:{name} ({target.neo4j_uri})")
    finally:
        driver.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true", help="read a running Neo4j (read-only)")
    source.add_argument("--snapshot", type=Path, help="kg_snapshot/v1 directory")
    parser.add_argument("--target", choices=("prod", "staging"), default="prod",
                        help="with --live: which stores to read (default prod)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="with --snapshot: score a snapshot that lacks files (no --ratchet/--accept)")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="baseline directory (index.json + one file per check family) or a single file")
    parser.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--step0-sha", type=Path, default=DEFAULT_STEP0_SHA,
                        help="check_step0's baseline; H7's embedding_queue sha target")
    parser.add_argument("--embedding-queue", type=Path, default=DEFAULT_EMBEDDING_QUEUE,
                        help="K0 text artifact for R2/R9 and H7's sha")
    parser.add_argument("--only", help="comma-separated check ids to run")
    parser.add_argument("--ratchet", action="store_true",
                        help="move baselines toward improvement (never back) and write the baseline file")
    parser.add_argument("--accept", default="",
                        help="comma-separated check ids whose current values become the baseline "
                             "(human approval of an intentional change, e.g. H10 or W)")
    parser.add_argument("--dump-snapshot", type=Path, help="with --live: also write the graph as a snapshot")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    return parser


def _load(args, target: Target | None) -> KG:
    """The graph to score; raises on an unreadable target or snapshot."""
    if args.live:
        kg = _read_live(target, args.target)
        if args.dump_snapshot:
            write_snapshot(kg, args.dump_snapshot)
        return kg
    return load_snapshot(args.snapshot, allow_partial=args.allow_partial)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    accept = {c for c in args.accept.split(",") if c}
    only = {c for c in args.only.split(",") if c} if args.only else None
    unknown = (accept | (only or set())) - set(CHECKS)
    if unknown:
        parser.error(f"unknown check ids: {sorted(unknown)}")
    if args.dump_snapshot and not args.live:
        parser.error("--dump-snapshot needs --live")

    baseline = load_baseline(args.baseline)
    probes = load_probes(args.probes)
    try:
        target = resolve_target(args.target) if args.live else None
        kg = _load(args, target)
    except Exception as e:  # noqa: BLE001  (unreadable target or snapshot: exit 1, never a pass)
        print(f"ERROR: cannot read {args.target if args.live else args.snapshot}: {e}", file=sys.stderr)
        return 1
    if kg.missing and (args.ratchet or accept):
        print(f"ERROR: refusing --ratchet/--accept on a partial snapshot (missing {list(kg.missing)}): "
              "its empty sets would be written into the baseline shared with live runs", file=sys.stderr)
        return 1

    ctx = Context(baseline=baseline, probes=probes, embedding_queue=args.embedding_queue, target=target)
    results = run_checks(kg, ctx, only)
    if args.ratchet or accept:
        measured = {"at": date.today().isoformat(), "origin": kg.origin}
        updated = apply_ratchet(baseline, results, args.ratchet, accept, measured)
        if updated != baseline:
            save_baseline(args.baseline, updated)
            baseline = updated

    report = {"origin": kg.origin, "baseline": str(args.baseline), "partial": list(kg.missing),
              **evaluate(results, baseline, external_targets(baseline, args.step0_sha))}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(report)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Edge-set equality gate (batch 1A-T2; plan docs/records/
2026-10-04_kg_batch1_plan.md §2.1 閘門「邊集合等同」): the semantic layer of
--target holds exactly the edges 6.05 says it should.

The semantic layer is every Entity-Entity edge but MENTIONS and
CROSS_REFERENCES, read in one READ transaction (check_identity's target
guards apply). After the W1 chain it is what 6.1 imported from
relations_clean.jsonl, minus the edges 10.2's DETACH DELETE of the generic
Events took along; 10.4 and 10.5 add only MENTIONS, and 10.3 is retired.

The reference is the 6.05 report (--report) and the relations_clean.jsonl its
output.path names. The file must hash to output.sha256, and its rows minus
expected_after_10_2.generic_event_ids must give that section's edges,
edge_set_sha256 and by_ee_key; otherwise the report does not describe the
file and nothing is compared. Live and reference are then compared on:
  * edges, the edge count;
  * edge_set_sha256 (relation_postprocess): the sorted head, type, tail,
    source lines, so an edge pointing elsewhere is caught even when every
    count still matches;
  * by_ee_key, the count per 'TYPE phase=P source=S' (diff_kg's ee_edges
    key), which also sees the phase the sha leaves out.
With --expect, the live edge_set_sha256 must also equal the committed
expected file's (1A-T4's relations_expected.json): a report regenerated
after the expectation was registered cannot certify itself (plan §3).

Exit codes: 0 all equal; 1 different (the ee-key deltas and up to 10
missing and 10 extra lines are printed); 2 cannot check: an invalid report,
output file or expected file (checked before the target is touched), or an
unreadable target.

Usage (from the project root, R2 in a shell that sourced scripts/tools/staging.env):
    scripts/.venv/bin/python scripts/tools/check_edge_set.py --target staging \\
        --expect config/kg_expect/batch1_w1/relations_expected.json
    scripts/.venv/bin/python scripts/tools/check_edge_set.py --target staging --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# The shell as the tool started. Importing relation_postprocess imports the
# entity_extraction package, whose config module runs load_dotenv(): it copies
# .env, prod's NEO4J_URI included, into os.environ. resolve_target judges the
# shell (check_identity docstring), so it is given this copy. The copy is taken
# when this module is first imported: a module that imports check_edge_set must
# do so before anything that loads .env (entity_extraction, relation_postprocess),
# as relations_expect does; test_relations_expect's
# test_target_is_resolved_from_the_shell_not_from_dotenv pins that order.
_SHELL_ENV = dict(os.environ)

from check_identity import open_neo4j, read_query, resolve_target  # noqa: E402
from scripts.relation_extraction import relation_postprocess as pp  # noqa: E402

LIVE_EDGES_CYPHER = """
MATCH (a:Entity)-[r]->(b:Entity)
WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']
RETURN a.entity_id AS head_id, type(r) AS relation, b.entity_id AS tail_id,
       r.source AS source, r.extraction_phase AS extraction_phase
"""
SHOWN = 10
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEY_FIELDS = frozenset({"head_id", "relation", "tail_id"})


class CannotCheck(Exception):
    """An input or the target cannot be read as the gate needs it (exit 2)."""


@dataclass(frozen=True)
class EdgeSet:
    lines: tuple[str, ...]
    sha256: str
    by_ee_key: dict[str, int]

    @classmethod
    def of(cls, rows: list[dict]) -> "EdgeSet":
        return cls(tuple(pp.edge_set_lines(rows)), pp.edge_set_sha256(rows), pp.by_ee_key(rows))

    @property
    def edges(self) -> int:
        return len(self.lines)


# --- inputs (read before the target is touched) --------------------------------

def _read_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CannotCheck(f"{what} {path} is not readable JSON: {e}") from e


def _parse_rows(data: bytes, path: Path) -> list[dict]:
    """One object per non-blank line, split on '\\n' only, as 6.05 writes them."""
    try:
        rows = [json.loads(line) for line in data.decode("utf-8").split("\n") if line.strip()]
    except ValueError as e:
        raise CannotCheck(f"{path} is not JSON lines: {e}") from e
    if not all(isinstance(row, dict) and _KEY_FIELDS <= row.keys() for row in rows):
        raise CannotCheck(f"{path} has a line without {', '.join(sorted(_KEY_FIELDS))}")
    return rows


def _report_fields(report, path: Path) -> tuple[Path, str, set[str], tuple]:
    """(output file, its sha256, the generic Event ids, the claimed (edges, sha, by_ee_key))."""
    try:
        if report["format"] != pp.REPORT_FORMAT:
            raise CannotCheck(f"{path} is a {report['format']!r} report, not {pp.REPORT_FORMAT}")
        out, after = report["output"], report["expected_after_10_2"]
        clean = Path(out["path"])
        claim = (after["edges"], after["edge_set_sha256"], after["by_ee_key"])
        return (clean if clean.is_absolute() else pp.ROOT / clean, out["sha256"],
                set(after["generic_event_ids"]), claim)
    except (KeyError, TypeError) as e:
        raise CannotCheck(f"{path} is not a 6.05 report: {e!r}") from e


def load_reference(report_path: Path) -> tuple[EdgeSet, Path]:
    """The edge set staging should hold after 10.2, rebuilt from the file the report describes."""
    clean, sha256, generic, claim = _report_fields(_read_json(report_path, "report"), report_path)
    try:
        data = clean.read_bytes()
    except OSError as e:
        raise CannotCheck(f"the report's output file is not readable: {e}") from e
    if hashlib.sha256(data).hexdigest() != sha256:
        raise CannotCheck(f"{clean} does not hash to the report's output.sha256 {sha256} "
                          "(rewritten after 6.05?)")
    rows = _parse_rows(data, clean)
    ref = EdgeSet.of([r for r in rows if r["head_id"] not in generic and r["tail_id"] not in generic])
    if (ref.edges, ref.sha256, ref.by_ee_key) != claim:
        raise CannotCheck(f"{report_path}: expected_after_10_2 does not follow from {clean} "
                          f"minus its generic_event_ids ({ref.edges:,} edges, {ref.sha256[:12]})")
    return ref, clean


def load_expect(path: Path) -> str:
    """The committed edge_set_sha256 of an expected file."""
    doc = _read_json(path, "expected file")
    sha = doc.get("edge_set_sha256") if isinstance(doc, dict) else None
    if not (isinstance(sha, str) and _SHA256.fullmatch(sha)):
        raise CannotCheck(f"{path} has no edge_set_sha256 (64 hex)")
    return sha


# --- target ----------------------------------------------------------------------

def resolve_shell_target(name: str):
    """resolve_target against the shell the tool started in (see _SHELL_ENV)."""
    return resolve_target(name, environ=_SHELL_ENV)


def read_live(name: str) -> tuple[list[dict], str]:
    """(the semantic edges of --target, its Neo4j URI), in a READ transaction."""
    try:
        target = resolve_shell_target(name)
        driver = open_neo4j(target)
        try:
            driver.verify_connectivity()  # fail fast instead of retrying a refused connection
            return read_query(driver, LIVE_EDGES_CYPHER), target.neo4j_uri
        finally:
            driver.close()
    except Exception as e:  # noqa: BLE001  (an unreadable target is never "equal")
        raise CannotCheck(f"--target {name} not readable: {type(e).__name__}: {e}") from e


# --- comparison ----------------------------------------------------------------

def _multiset_minus(a: tuple[str, ...], b: tuple[str, ...]) -> list[str]:
    return sorted((Counter(a) - Counter(b)).elements())


def compare(live: EdgeSet, ref: EdgeSet, expect_sha: str | None) -> dict:
    """The failed checks, the ee-key deltas and the missing/extra lines (first SHOWN)."""
    failed = [name for name, a, b in (("edges", live.edges, ref.edges),
                                      ("edge_set_sha256", live.sha256, ref.sha256),
                                      ("by_ee_key", live.by_ee_key, ref.by_ee_key)) if a != b]
    if expect_sha is not None and live.sha256 != expect_sha:
        failed.append("expect.edge_set_sha256")
    keys = sorted(live.by_ee_key.keys() | ref.by_ee_key.keys())
    deltas = {k: {"report": ref.by_ee_key.get(k, 0), "live": live.by_ee_key.get(k, 0)} for k in keys}
    deltas = {k: {**d, "delta": d["live"] - d["report"]} for k, d in deltas.items()
              if d["live"] != d["report"]}
    missing, extra = _multiset_minus(ref.lines, live.lines), _multiset_minus(live.lines, ref.lines)
    return {"failed": failed, "ee_key_deltas": deltas,
            "missing": {"count": len(missing), "sample": missing[:SHOWN]},
            "extra": {"count": len(extra), "sample": extra[:SHOWN]},
            "exit": 1 if failed else 0}


def _side(edges: EdgeSet) -> dict:
    return {"edges": edges.edges, "edge_set_sha256": edges.sha256, "by_ee_key": edges.by_ee_key}


def run(target: str, report_path: Path, expect_path: Path | None) -> dict:
    """The gate's result document; CannotCheck when it cannot be computed."""
    ref, clean = load_reference(report_path)
    expect_sha = load_expect(expect_path) if expect_path is not None else None
    rows, uri = read_live(target)
    live = EdgeSet.of(rows)
    expect = None if expect_path is None else {"path": str(expect_path), "edge_set_sha256": expect_sha}
    return {"target": target, "neo4j_uri": uri, "live": _side(live),
            "report": {"path": str(report_path), "clean": str(clean), **_side(ref)},
            "expect": expect, **compare(live, ref, expect_sha)}


# --- output --------------------------------------------------------------------

def _summary_line(label: str, side: dict, where: str) -> str:
    edges = f"{side['edges']:>7,} edges" if "edges" in side else " " * 13
    keys = f"  {len(side['by_ee_key'])} ee keys" if "by_ee_key" in side else ""
    return f"  {label:<7}{edges}  edge set {side['edge_set_sha256'][:12]}{keys}{where}"


def render(doc: dict) -> str:
    lines = [f"check_edge_set --target {doc['target']} ({doc['neo4j_uri']}): "
             "Entity-Entity edges but MENTIONS and CROSS_REFERENCES",
             _summary_line("live", doc["live"], ""),
             _summary_line("report", doc["report"], f"  ({doc['report']['path']})")]
    if doc["expect"]:
        lines.append(_summary_line("expect", doc["expect"], f"  ({doc['expect']['path']})"))
    if doc["ee_key_deltas"]:
        lines.append("  ee key deltas (report -> live):")
        lines += [f"    {k}: {d['report']:,} -> {d['live']:,} ({d['delta']:+,})"
                  for k, d in doc["ee_key_deltas"].items()]
    if doc["exit"]:
        for name, where in (("missing", "missing from live"), ("extra", "extra in live")):
            part = doc[name]
            shown = f" (first {SHOWN})" if part["count"] > SHOWN else ""
            lines.append(f"  {where}: {part['count']:,}{shown}")
            lines += [f"    {line}" for line in part["sample"]]
        lines.append(f"exit 1: live differs on {', '.join(doc['failed'])}")
    else:
        lines.append(f"exit 0: live equals the report{' and the expected file' if doc['expect'] else ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("staging", "prod"), required=True,
                        help="the Neo4j to read (check_identity.resolve_target's guards apply)")
    parser.add_argument("--report", type=Path, default=pp.DEFAULT_REPORT,
                        help="the 6.05 report (default: output/relations_clean.report.json)")
    parser.add_argument("--expect", type=Path,
                        help="the committed expected file whose edge_set_sha256 live must equal too")
    parser.add_argument("--json", action="store_true", help="print the result as one JSON document")
    args = parser.parse_args(argv)
    try:
        doc = run(args.target, args.report, args.expect)
    except Exception as e:  # noqa: BLE001  (a traceback would exit 1, which here means "different")
        error = str(e) if isinstance(e, CannotCheck) else f"{type(e).__name__}: {e}"
        print(f"CANNOT CHECK: {error}", file=sys.stderr)
        if args.json:
            print(json.dumps({"exit": 2, "error": error}, ensure_ascii=False))
        return 2
    print(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) if args.json else render(doc))
    return doc["exit"]


if __name__ == "__main__":
    sys.exit(main())

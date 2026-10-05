#!/usr/bin/env python3
"""模擬等於實測 for cross references: predict the backend's xref candidates
offline and compare them row by row with a measurement (W1 1B; plan
docs/records/2026-10-04_kg_batch1_plan.md §2.2). One positional action; the
flags are flat, so --help lists all of them.

  seeds    every pericope of --pericopes as a single seed, plus one proxy seed
           set per benchmark question routed R3–R6 without graph (the first 5
           nograph_top5 ids that are pericopes; empty sets dropped). Writes
           {version, questions_sha256, singles, sets}.
  predict  xref_rank (the offline replica of neo4j_db's xref Cypher and
           cross_ref_retriever's weights) over the edges of --target
           prod|staging (READ sessions, check_identity guards) or --edges
           (JSONL of {a, b, source, curated, votes}). Writes {version, params,
           edges_from, rows}: 'single:<pid>' (multi-hop), 'legacy:<pid>'
           (1-hop legacy) and 'q:<qid>' (multi-hop from the set), each row
           [id, hop, curated, weight].
  compare  --pred against --measured, each a full document or a bare
           key -> rows map (the archived planner files). Rows compare as JSON
           (0 is not false, 1 is not 1.0). Exit 1 when the params differ
           (when both carry them), the key sets differ, a row list differs, or
           a sentinel fails in either file: for each SENTINEL_PAIRS pair, both
           ways, single:<x> and legacy:<x> must hold the partner with curated
           false and weight 0.60. Those are the three TSK edges with votes
           >= 999 that the pre-C1 coalesce(r.votes, 999) rule ranked as curated.

The measured side is backend probes/xref_measure (1B-T2): same seed file, the
real retriever functions.

Usage (from the project root):
    PY=scripts/.venv/bin/python
    $PY scripts/tools/xref_probe.py seeds --out seeds.json
    $PY scripts/tools/xref_probe.py predict --seeds seeds.json --target prod --out pred.json
    $PY scripts/tools/xref_probe.py compare --pred pred.json --measured measured.json

Exit code: 0 done / everything matches; 1 a difference, a failed sentinel, or
an unreadable input or target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from check_identity import open_neo4j, read_query, resolve_target  # noqa: E402
from scripts.tools import xref_rank  # noqa: E402

DEFAULT_PERICOPES = _PROJECT_ROOT / "output" / "pericopes.jsonl"
DEFAULT_QUESTIONS = (_PROJECT_ROOT / "docs" / "records" / "2026-10-04_kg_fix" / "batch1" / "inputs"
                     / "bench" / "questions_table.json")
SEED_ROUTES = ("R3", "R4", "R5", "R6")  # routes whose candidates get xref expansion
MAX_SET_SEEDS = 5
# settings.rag_cross_ref_max_hops / rag_cross_ref_expand_limit; the legacy top_k (router) is limit too
PARAMS = {"max_hops": 2, "limit": 10}
SENTINEL_PAIRS = (("jer:29:0", "isa:55:0"), ("rom:8:1", "eph:1:1"), ("rom:8:1", "jer:1:1"))
SENTINEL_WEIGHT = 0.60
EDGES_CYPHER = """
MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
RETURN a.id AS a, b.id AS b, r.source AS source, r.curated AS curated, r.votes AS votes"""
SHOWN = 10


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, doc) -> None:
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------- seeds

def build_seeds(pericopes: Path, questions: Path) -> dict:
    singles = sorted({row["id"] for row in _read_jsonl(pericopes)})
    known = set(singles)
    sets = {}
    for q in _read_json(questions):
        if q["route_nograph"] not in SEED_ROUTES:
            continue
        ids = [entry.split("|")[0] for entry in q["nograph_top5"]]
        ids = [pid for pid in ids if pid in known][:MAX_SET_SEEDS]
        if ids:
            sets[q["qid"]] = ids
    return {"version": 1, "questions_sha256": _sha256(questions), "singles": singles, "sets": sets}


def _cmd_seeds(args) -> int:
    doc = build_seeds(args.pericopes, args.questions)
    _write_json(args.out, doc)
    print(f"seeds: {len(doc['singles'])} singles, {len(doc['sets'])} sets "
          f"-> {2 * len(doc['singles']) + len(doc['sets'])} keys ({args.out})")
    return 0


# ---------------------------------------------------------------- predict

def read_target_edges(name: str) -> tuple[list[dict], dict]:
    """CROSS_REFERENCES of one target, in a READ transaction (resolve_target's guards apply)."""
    target = resolve_target(name)
    driver = open_neo4j(target)
    try:
        driver.verify_connectivity()  # fail fast instead of retrying a refused connection
        edges = read_query(driver, EDGES_CYPHER)
    finally:
        driver.close()
    return edges, {"target": target.name, "neo4j_uri": target.neo4j_uri}


def predict(index: xref_rank.XrefIndex, seeds: dict) -> dict:
    """{key: rows} for the single seeds (multi-hop and legacy) and the seed sets."""
    hops, limit = PARAMS["max_hops"], PARAMS["limit"]
    rows = {}
    for pid in seeds["singles"]:
        rows[f"single:{pid}"] = xref_rank.multi_hop(index, [pid], hops, limit)
        rows[f"legacy:{pid}"] = xref_rank.legacy(index, pid, limit)
    for qid, ids in seeds["sets"].items():
        rows[f"q:{qid}"] = xref_rank.multi_hop(index, ids, hops, limit)
    return {key: [list(r) for r in value] for key, value in rows.items()}


def _cmd_predict(args) -> int:
    seeds = _read_json(args.seeds)
    if seeds.get("version") != 1:
        raise ValueError(f"{args.seeds}: not a version-1 seed file")
    if args.target:
        edges, source = read_target_edges(args.target)
    else:
        edges, source = _read_jsonl(args.edges), {"file": str(args.edges), "sha256": _sha256(args.edges)}
    if not edges:
        raise ValueError(f"no CROSS_REFERENCES edges read from {source}")
    rows = predict(xref_rank.XrefIndex.from_edges(edges), seeds)
    _write_json(args.out, {"version": 1, "params": dict(PARAMS),
                           "edges_from": {**source, "edges": len(edges)}, "rows": rows})
    print(f"predict: {len(rows)} keys from {len(edges)} edges ({args.out})")
    return 0


# ---------------------------------------------------------------- compare

def _split(doc) -> tuple[dict | None, dict]:
    """(params or None, rows) of a full document or a bare key -> rows map."""
    if isinstance(doc.get("rows"), dict):
        return doc.get("params"), doc["rows"]
    return None, doc


def sentinel_failures(rows: dict) -> tuple[int, list[str]]:
    """(assertions checked, failures) for SENTINEL_PAIRS on one rows map."""
    checked, failures = 0, []
    for x, y in SENTINEL_PAIRS:
        for seed, partner in ((x, y), (y, x)):
            for kind in ("single", "legacy"):
                checked += 1
                key = f"{kind}:{seed}"
                hit = [r for r in rows.get(key, []) if r[0] == partner]
                ok = any(r[2] is False and abs(r[3] - SENTINEL_WEIGHT) < 1e-9 for r in hit)
                if not ok:
                    failures.append(f"{key} lacks [{partner!r}, 1, false, {SENTINEL_WEIGHT}]: {hit}")
    return checked, failures


def _first_difference(pred: list, meas: list) -> str:
    i = next((i for i, (a, b) in enumerate(zip(pred, meas)) if json.dumps(a) != json.dumps(b)),
             min(len(pred), len(meas)))
    a, b = (json.dumps(rows[i]) if i < len(rows) else "(none)" for rows in (pred, meas))
    return f"{len(pred)} vs {len(meas)} rows, first difference at #{i}: pred {a} measured {b}"


def compare(pred_doc, measured_doc) -> list[str]:
    """Problems of measured against pred (prints the counts); empty means equal."""
    (pp, pred), (mp, meas) = _split(pred_doc), _split(measured_doc)
    problems = []
    if pp is not None and mp is not None and pp != mp:
        problems.append(f"params differ: pred {pp} measured {mp}")
    only_p, only_m = sorted(set(pred) - set(meas)), sorted(set(meas) - set(pred))
    print(f"keys: pred {len(pred)}, measured {len(meas)}, only in pred {len(only_p)}, "
          f"only in measured {len(only_m)}")
    for side, keys in (("pred", only_p), ("measured", only_m)):
        problems += [f"only in {side}: {k}" for k in keys[:SHOWN]]
    differ = [k for k in sorted(set(pred) & set(meas)) if json.dumps(pred[k]) != json.dumps(meas[k])]
    print(f"rows: {len(differ)} of {len(set(pred) & set(meas))} shared keys differ")
    problems += [f"{k}: {_first_difference(pred[k], meas[k])}" for k in differ[:SHOWN]]
    sentinel_counts = []
    for side, rows in (("pred", pred), ("measured", meas)):
        checked, failures = sentinel_failures(rows)
        sentinel_counts.append(f"{checked - len(failures)}/{checked} in {side}")
        problems += [f"sentinel ({side}): {f}" for f in failures]
    print("sentinels " + ", ".join(sentinel_counts))
    return problems


def _cmd_compare(args) -> int:
    problems = compare(_read_json(args.pred), _read_json(args.measured))
    for problem in problems:
        print(f"  {problem}")
    print("exit 0: prediction equals measurement" if not problems else f"exit 1: {len(problems)} problems")
    return 1 if problems else 0


# ---------------------------------------------------------------- CLI

ACTIONS = {"seeds": _cmd_seeds, "predict": _cmd_predict, "compare": _cmd_compare}
REQUIRED = {"seeds": ("out",), "predict": ("seeds", "out"), "compare": ("pred", "measured")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=sorted(ACTIONS), help="see above")
    parser.add_argument("--pericopes", type=Path, default=DEFAULT_PERICOPES,
                        help="seeds: Step 0 pericopes.jsonl (default output/pericopes.jsonl)")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS,
                        help="seeds: benchmark questions_table.json (default: the batch-1 bench input)")
    parser.add_argument("--out", type=Path, help="seeds / predict: file to write")
    parser.add_argument("--seeds", type=Path, help="predict: seed file written by the seeds action")
    parser.add_argument("--target", choices=("prod", "staging"), help="predict: read the edges from this Neo4j")
    parser.add_argument("--edges", type=Path, help="predict: read the edges from this JSONL instead")
    parser.add_argument("--pred", type=Path, help="compare: the prediction")
    parser.add_argument("--measured", type=Path, help="compare: the measurement")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    missing = [f"--{name}" for name in REQUIRED[args.action] if getattr(args, name) is None]
    if missing:
        parser.error(f"{args.action} needs {' '.join(missing)}")
    if args.action == "predict" and (args.target is None) == (args.edges is None):
        parser.error("predict needs exactly one of --target and --edges")
    try:
        return ACTIONS[args.action](args)
    except Exception as e:  # noqa: BLE001  (an unreadable input or target is never "equal")
        print(f"ERROR: {args.action}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

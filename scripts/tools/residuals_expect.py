#!/usr/bin/env python3
"""W1 residual expectations (batch 1A-T5; plan docs/records/2026-10-04_kg_batch1_plan.md
§3 expected files first, §2.1 「第 0 批的殘差會跟著上線」, §4 「R1 2,124 與 4 個實體的
mention_count 殘差」, K10).

The batch-0 rebuild left residuals that W1 promotes as they are: Entity.mention_count
differs from prod on a few entities (1D unifies its definition), MENTIONS edges carry
properties that differ from prod's (same edges, other start_pos, source_granularity,
created_from, ...), and R1 (MENTIONS in the book-name region) reads higher. W1 changes
neither MENTIONS nor entities, so the W1 staging must show exactly the residuals the
batch-0 staging (b) shows now. This reads them before W1 step 2 rebuilds b, and writes:
  --out        the expected file: {version, basis: {a, b: {target, neo4j_uri, entities,
               sourced_semantic_edges, nodes, relationships (the graph totals: which build
               was read, batch 0 has 13,589 and 319,988; recorded, not checked)}, at (when
               b was read), git_head, premise,
               validate_kg: {a, b: {origin, sha256}}}, mention_count: {entity_id: {a, b,
               delta}}, mentions_props: {edges: {a, b}, only_a, only_b, differing:
               {property: edges}}, validate_kg: {R1: {a, b}}}. At R2, validate_kg's R1
               on the W1 staging must equal validate_kg.R1.b, and --check must pass.
  --allow-out  1A's residuals fragment of the merged W1 allowlist, in diff_kg's --allow
               YAML (diff_kg.render_allowlist): one exact entry per entity whose
               mention_count differs (section mention_count, key the entity_id, delta
               b - a). The merged allowlist takes mention_count from this fragment only;
               diff_kg --merge-out joins it with relations_allow.yaml and 1B's fragment.

mention_count is read with diff_kg's own PROFILE_QUERIES["entities"] and compared
with diff_kg.diff_entities, so the keys and deltas are the ones diff_kg reports at R2.
diff_kg counts MENTIONS but never compares their properties; mentions_props does: an
edge is (source label, source id, entity_id), and per property it counts the edges on
both sides whose value differs (a property missing on one side differs from any value),
plus the edges on one side only.
R1 is book_region_mentions from validate_kg --live --json reports on the same two
targets (--validate-a, --validate-b), never typed by hand: a report's origin must name
the target this tool resolves (live:NAME (URI)), and its R1 must be a measured integer.
validate_kg's own exit code does not matter here (prod fails the 1A and 1B checks
until the W1 promotion).

Exit codes: 0 both files written; 1 the two sides do not hold the same entity ids
(the premise fails: find out why first); 2 cannot generate: usage, a validate_kg report
that is not that target's live R1 (checked before either target is read), either side
holding a semantic edge with a source (6.05's edges: that side is no longer the
batch-0 build, and a residual read off the W1 build would certify it, plan §3), a
differing mention_count that is not an integer on both sides (diff_kg gives it no
delta, so no exact entry could allow it), an entity_id read twice or holding glob
characters, an unreadable target or output path, a MENTIONS edge read twice on one
side. Nothing is written on 1 or 2: both files go to <path>.tmp first and replace
their paths only after both writes succeeded.

--check FILE (R2, after W1 step 2) re-reads only the MENTIONS of both targets and writes
nothing: 0 when mentions_props equals FILE's, 1 when a count differs (each one printed),
2 when FILE is not a registered residuals_expected.json with mentions_props, its basis
names other targets than this run resolves (checked before any read), or a target
cannot be read. b holding 1A's semantic edges is expected there.

Targets resolve through check_identity.resolve_target, as in diff_kg: --a prod is
refused in a shell that exports staging settings, so run this from a shell without
them (staging then resolves to bolt://localhost:7688). Every read is a READ transaction.

Usage (from the project root, before W1 step 2; V = a directory kept for the record,
e.g. bak/<D>, since the expected file records the reports' sha256):
    scripts/.venv/bin/python scripts/validate_kg.py --live --target prod --json > "$V"/validate_prod.json
    (source scripts/tools/staging.env && scripts/.venv/bin/python scripts/validate_kg.py \\
        --live --target staging --json > "$V"/validate_staging.json)
    scripts/.venv/bin/python scripts/tools/residuals_expect.py --a prod --b staging \\
        --validate-a "$V"/validate_prod.json --validate-b "$V"/validate_staging.json \\
        --out config/kg_expect/batch1_w1/residuals_expected.json \\
        --allow-out config/kg_expect/batch1_w1/residuals_allow.yaml
    # R2, after the rebuild, from the same kind of clean shell:
    scripts/.venv/bin/python scripts/tools/residuals_expect.py --a prod --b staging \\
        --check config/kg_expect/batch1_w1/residuals_expected.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from check_identity import open_neo4j, read_query, resolve_target  # noqa: E402
from scripts.tools import diff_kg  # noqa: E402

ENTITIES_CYPHER = diff_kg.PROFILE_QUERIES["entities"]
SOURCED_EDGES_CYPHER = """
MATCH (:Entity)-[r]->(:Entity)
WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES'] AND r.source IS NOT NULL
RETURN count(r) AS n"""
# the graph totals, recorded so a reviewer can tell which build a side was read from (batch 0:
# 13,589 nodes and 319,988 relationships, the R3 counts of plan §1 W0 驗收); never a gate here
NODES_CYPHER = "MATCH (n) RETURN count(n) AS n"
RELATIONSHIPS_CYPHER = "MATCH ()-[r]->() RETURN count(r) AS n"
# the source label as diff_kg's "mentions" section names it; the id as the reviewers' probe read it
MENTIONS_CYPHER = """
MATCH (s)-[m:MENTIONS]->(e:Entity)
RETURN CASE WHEN s:Chunk THEN 'Chunk' WHEN s:Pericope THEN 'Pericope' ELSE head(labels(s)) END AS source_label,
       coalesce(s.id, s.entity_id) AS source_id, e.entity_id AS entity_id, properties(m) AS props"""
R1_METRIC = "book_region_mentions"
VERSION = 1
_GLOB = re.compile(r"[*?\[]")
PREMISE = ("W1 不改 MENTIONS 與實體：W1 staging 的 mention_count、MENTIONS 屬性差異與 R1 必須等於 b"
           "（batch-0 staging，於 W1 Step 2 重建前讀取，語意邊皆無 source）。R2 時 diff_kg 的 mention_count "
           "差異須恰為本檔各實體，validate_kg 的 R1 須等於 validate_kg.R1.b，residuals_expect --check 須讀到"
           "與 mentions_props 相同的逐屬性條數。")
HEADER = (
    "1A residuals fragment of the merged W1 allowlist, written by residuals_expect.py: regenerate it, "
    "never edit it.",
    "delta = b - a per entity (diff_kg's mention_count section), read while b still held the batch-0 build:",
    "W1 changes neither MENTIONS nor entities, so the W1 staging keeps exactly these residuals (K10).",
    "The merged allowlist takes mention_count from this fragment only; R1 is in residuals_expected.json.")
REASON = ("1A K10 第 0 批 mention_count 殘差（1D 統一定義前沿用）：W1 不改 MENTIONS 與實體，"
          "W1 staging 保留 batch-0 staging 的值（{a} {va} → {b} {vb}）")


class Mismatch(Exception):
    """The two sides do not hold the same entities: the premise fails (exit 1)."""


class CannotGenerate(Exception):
    """An input or a target cannot give the expectation, or --check cannot be made (exit 2)."""


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_PROJECT_ROOT, capture_output=True,
                             text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --- inputs ----------------------------------------------------------------------

def _dig(doc, *keys):
    for key in keys:
        doc = doc.get(key) if isinstance(doc, dict) else None
    return doc


def load_r1(path: Path, target) -> tuple[int, dict]:
    """(R1 book_region_mentions, {origin, sha256}) of a validate_kg --live --json report on `target`."""
    try:
        data = path.read_bytes()
        doc = json.loads(data)
    except (OSError, ValueError) as e:
        raise CannotGenerate(f"{path}: not a validate_kg --json report: {e}") from e
    origin = f"live:{target.name} ({target.neo4j_uri})"
    if _dig(doc, "origin") != origin:
        raise CannotGenerate(f"{path}: origin {_dig(doc, 'origin')!r} is not {origin!r}; R1 must come from "
                             f"validate_kg --live --target {target.name} --json")
    value = _dig(doc, "checks", "R1", "metrics", R1_METRIC, "value")
    if not isinstance(value, int) or isinstance(value, bool):
        raise CannotGenerate(f"{path}: R1 {R1_METRIC} is {value!r}, not a measured integer "
                             "(run validate_kg without --only)")
    return value, {"origin": origin, "sha256": hashlib.sha256(data).hexdigest()}


def _read(target, *statements: str) -> list[list[dict]]:
    """Each statement's rows on one target, in one READ-only driver."""
    try:
        driver = open_neo4j(target)
        try:
            driver.verify_connectivity()  # fail fast instead of retrying a refused connection
            return [read_query(driver, statement) for statement in statements]
        finally:
            driver.close()
    except Exception as e:  # noqa: BLE001  (an unreadable target cannot give a residual)
        raise CannotGenerate(f"{target.name} not readable: {type(e).__name__}: {e}") from e


def _unique(rows: list[dict], key, where: str, what: str) -> dict:
    """{key(row): row}; a key read twice is refused (a dict would keep one of them silently)."""
    out = {key(r): r for r in rows}
    if len(out) != len(rows):
        repeated = sorted((k for k, n in Counter(key(r) for r in rows).items() if n > 1), key=str)
        raise CannotGenerate(f"{where}: {what} read more than once: {repeated[:10]}")
    return out


def mention_edges(rows: list[dict], where: str) -> dict[tuple, dict]:
    """{(source label, source id, entity_id): MENTIONS properties} of MENTIONS_CYPHER's rows."""
    edges = _unique(rows, lambda r: (r["source_label"], r["source_id"], r["entity_id"]), where,
                    "MENTIONS edge (source label, source id, entity_id)")
    return {k: r["props"] for k, r in edges.items()}


def read_side(target) -> dict:
    """{entities: {entity_id: row}, sourced: semantic edges with a source, mentions: {edge: properties},
    nodes, relationships: the graph totals} of one target, READ only."""
    rows, sourced, mentions, nodes, rels = _read(target, ENTITIES_CYPHER, SOURCED_EDGES_CYPHER, MENTIONS_CYPHER,
                                                 NODES_CYPHER, RELATIONSHIPS_CYPHER)
    return {"entities": _unique(rows, lambda r: r["entity_id"], target.name, "entity_id"),
            "sourced": sourced[0]["n"], "mentions": mention_edges(mentions, target.name),
            "nodes": nodes[0]["n"], "relationships": rels[0]["n"]}


def read_mentions(target) -> dict[tuple, dict]:
    """--check: the MENTIONS edges of one target, nothing else, READ only."""
    (rows,) = _read(target, MENTIONS_CYPHER)
    return mention_edges(rows, target.name)


# --- expectation -----------------------------------------------------------------

def residuals(a: dict[str, dict], b: dict[str, dict]) -> dict[str, dict]:
    """{entity_id: {a, b, delta}} of diff_kg's mention_count differences of b against a."""
    diffs = diff_kg.diff_entities(a, b)
    one_side = [d for d in diffs if d["section"] == "entity_ids"]
    if one_side:
        sample = ", ".join(f"{d['key']} (only in {'a' if d['a'] else 'b'})" for d in one_side[:10])
        raise Mismatch(f"{len(one_side)} entity ids on one side only: {sample}; W1 changes no entity, "
                       "so b's residuals do not carry over")
    out = {}
    for d in (d for d in diffs if d["section"] == "mention_count"):
        if d["delta"] is None:
            raise CannotGenerate(f"mention_count of {d['key']} is {d['a']!r} on a and {d['b']!r} on b: "
                                 "diff_kg gives it no delta, so no exact entry can allow it")
        if _GLOB.search(d["key"]):
            raise CannotGenerate(f"entity_id {d['key']!r} holds glob characters: an allow key would match others")
        out[d["key"]] = {"a": d["a"], "b": d["b"], "delta": d["delta"]}
    return out


def mentions_props(a: dict[tuple, dict], b: dict[tuple, dict]) -> dict:
    """Per property, the MENTIONS edges on both sides whose value differs; the edges on one side only."""
    differing = Counter()
    for edge in a.keys() & b.keys():
        pa, pb = a[edge], b[edge]
        differing.update(prop for prop in pa.keys() | pb.keys() if pa.get(prop) != pb.get(prop))
    return {"edges": {"a": len(a), "b": len(b)}, "only_a": len(a.keys() - b.keys()),
            "only_b": len(b.keys() - a.keys()), "differing": dict(sorted(differing.items()))}


def build(targets: dict, sides: dict, r1: dict, at: str) -> tuple[dict, str]:
    """(the expected file document, the fragment's YAML)."""
    for side in ("a", "b"):  # both: --a staging --b prod is a valid spelling, and must not skip staging
        if sides[side]["sourced"]:
            raise CannotGenerate(f"{side} ({targets[side].name}) holds {sides[side]['sourced']:,} semantic edges "
                                 "with a source: it is no longer the batch-0 build; the residuals must be read "
                                 "before W1 step 2 (plan §3)")
    mention_count = residuals(sides["a"]["entities"], sides["b"]["entities"])
    basis = {side: {"target": targets[side].name, "neo4j_uri": targets[side].neo4j_uri,
                    "entities": len(sides[side]["entities"]), "sourced_semantic_edges": sides[side]["sourced"],
                    "nodes": sides[side]["nodes"], "relationships": sides[side]["relationships"]}
             for side in ("a", "b")}
    doc = {"version": VERSION,
           "basis": {**basis, "at": at, "git_head": git_head(), "premise": PREMISE,
                     "validate_kg": {side: r1[side][1] for side in ("a", "b")}},
           "mention_count": mention_count,
           "mentions_props": mentions_props(sides["a"]["mentions"], sides["b"]["mentions"]),
           "validate_kg": {"R1": {side: r1[side][0] for side in ("a", "b")}}}
    names = {"a": targets["a"].name, "b": targets["b"].name}
    entries = [{"section": "mention_count", "key": eid, "delta": d["delta"],
                "reason": REASON.format(a=names["a"], va=d["a"], b=names["b"], vb=d["b"])}
               for eid, d in mention_count.items()]
    header = [*HEADER, f"a {names['a']} {basis['a']['neo4j_uri']}, b {names['b']} {basis['b']['neo4j_uri']}: "
                       f"{basis['a']['entities']:,} entities each, {len(entries)} differ"]
    return doc, diff_kg.render_allowlist(entries, header)


def generate(args) -> tuple[dict, str]:
    """Resolve both targets, check both reports, then read both targets."""
    try:
        targets = {"a": resolve_target(args.a), "b": resolve_target(args.b)}
    except ValueError as e:
        raise CannotGenerate(str(e)) from e
    r1 = {side: load_r1(path, targets[side]) for side, path in (("a", args.validate_a), ("b", args.validate_b))}
    sides = {side: read_side(target) for side, target in targets.items()}
    return build(targets, sides, r1, now())


# --- check (R2) ------------------------------------------------------------------

def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def flat_props(props) -> dict[str, int]:
    """mentions_props as {edges.a, edges.b, only_a, only_b, differing.<property>: edges}; ValueError
    for any other shape."""
    if not isinstance(props, dict) or set(props) != {"edges", "only_a", "only_b", "differing"}:
        raise ValueError(f"mentions_props is not {{edges, only_a, only_b, differing}}: {str(props)[:200]}")
    edges, differing = props["edges"], props["differing"]
    if not isinstance(edges, dict) or set(edges) != {"a", "b"} or not isinstance(differing, dict):
        raise ValueError("mentions_props.edges is not {a, b}, or differing is not a mapping")
    flat = {"edges.a": edges["a"], "edges.b": edges["b"], "only_a": props["only_a"], "only_b": props["only_b"],
            **{f"differing.{prop}": n for prop, n in differing.items()}}
    bad = sorted(key for key, n in flat.items() if not _is_count(n))
    if bad:
        raise ValueError(f"mentions_props counts that are not non-negative integers: {bad}")
    return flat


def load_registered(path: Path) -> dict:
    """A residuals_expected.json this tool wrote: mentions_props, and both targets in its basis."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("version") != VERSION:
            raise ValueError(f"not a version {VERSION} residuals_expected.json")
        flat_props(doc.get("mentions_props"))
        for side in ("a", "b"):
            if not all(isinstance(_dig(doc, "basis", side, key), str) for key in ("target", "neo4j_uri")):
                raise ValueError(f"basis.{side} names no target and neo4j_uri")
    except (OSError, ValueError) as e:
        raise CannotGenerate(f"{path}: not a residuals_expected.json with mentions_props written by this "
                             f"tool: {e}") from e
    return doc


def mismatches(registered: dict, measured: dict) -> list[str]:
    """One line per count that differs from the registered one (a property not listed counts 0)."""
    reg, now_ = flat_props(registered), flat_props(measured)
    return [f"{key}: registered {reg.get(key, 0):,}, now {now_.get(key, 0):,}"
            for key in sorted(reg.keys() | now_.keys()) if reg.get(key, 0) != now_.get(key, 0)]


def check(args) -> tuple[dict, list[str]]:
    """(mentions_props read now, the counts that differ from the registered file's); the file and
    the targets are checked before either target is read."""
    registered = load_registered(args.check)
    try:
        targets = {"a": resolve_target(args.a), "b": resolve_target(args.b)}
    except ValueError as e:
        raise CannotGenerate(str(e)) from e
    for side, target in targets.items():
        basis = registered["basis"][side]
        if (basis["target"], basis["neo4j_uri"]) != (target.name, target.neo4j_uri):
            raise CannotGenerate(f"{args.check}: {side} was registered on {basis['target']} "
                                 f"({basis['neo4j_uri']}); this run resolves {target.name} ({target.neo4j_uri})")
    measured = mentions_props(read_mentions(targets["a"]), read_mentions(targets["b"]))
    return measured, mismatches(registered["mentions_props"], measured)


# --- output ----------------------------------------------------------------------

def props_summary(props: dict) -> list[str]:
    differing = ", ".join(f"{prop} {n:,}" for prop, n in props["differing"].items()) or "none"
    return [f"  MENTIONS: {props['edges']['a']:,} -> {props['edges']['b']:,} edges, only a {props['only_a']:,}, "
            f"only b {props['only_b']:,}",
            f"    properties differing on the edges in both: {differing}"]


def summary(doc: dict, entries: int) -> list[str]:
    basis, r1 = doc["basis"], doc["validate_kg"]["R1"]
    a, b = basis["a"], basis["b"]
    return [
        f"residuals_expect: a {a['target']} ({a['neo4j_uri']}), b {b['target']} ({b['neo4j_uri']})",
        f"  entities: {a['entities']:,} each; b semantic edges with a source: {b['sourced_semantic_edges']} "
        "(batch-0 build)",
        f"  graph: a {a['nodes']:,} nodes, {a['relationships']:,} relationships; "
        f"b {b['nodes']:,} nodes, {b['relationships']:,} relationships",
        f"  mention_count: {len(doc['mention_count'])} of {a['entities']:,} entities differ",
        *(f"    {eid} {d['a']} -> {d['b']} ({d['delta']:+d})" for eid, d in doc["mention_count"].items()),
        *props_summary(doc["mentions_props"]),
        f"  R1 {R1_METRIC}: {r1['a']:,} -> {r1['b']:,}",
        f"  fragment: {entries} entries",
    ]


def _write_all(files: list[tuple[Path, str]]) -> list[str]:
    """Write each (path, text) to <path>.tmp, then os.replace them all only once every temp file is
    written, so a failed write leaves each path as it was; the sha256sum line of each file."""
    staged = []
    try:
        for path, text in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            staged.append(path.with_name(path.name + ".tmp"))
            staged[-1].write_text(text, encoding="utf-8")
        for (path, _text), tmp in zip(files, staged):
            os.replace(tmp, path)
    finally:
        for tmp in staged:
            tmp.unlink(missing_ok=True)
    return [f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}  {path}" for path, text in files]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", choices=("prod", "staging"), default="prod",
                        help="diff_kg's a side, the graph the deltas are taken from (default prod)")
    parser.add_argument("--b", choices=("prod", "staging"), default="staging",
                        help="diff_kg's b side (default staging): still the batch-0 build when generating, "
                             "the W1 build at --check")
    parser.add_argument("--validate-a", type=Path,
                        help="validate_kg --live --target <a> --json report (R1 of a); required without --check")
    parser.add_argument("--validate-b", type=Path,
                        help="validate_kg --live --target <b> --json report (R1 of b); required without --check")
    parser.add_argument("--out", type=Path, help="the expected file (JSON) to write; required without --check")
    parser.add_argument("--allow-out", type=Path,
                        help="the allowlist fragment (YAML) to write; required without --check")
    parser.add_argument("--check", type=Path, metavar="FILE",
                        help="R2: re-read the MENTIONS of both targets and compare mentions_props with this "
                             "registered residuals_expected.json; writes nothing")
    return parser


_GENERATE_FLAGS = (("--validate-a", "validate_a"), ("--validate-b", "validate_b"), ("--out", "out"),
                   ("--allow-out", "allow_out"))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.a == args.b:
        parser.error("--a and --b must name different targets")
    given = [flag for flag, dest in _GENERATE_FLAGS if getattr(args, dest) is not None]
    if args.check is not None:
        if given:
            parser.error(f"--check reads no report and writes nothing: drop {', '.join(given)}")
        return _run_check(args)
    if len(given) < len(_GENERATE_FLAGS):
        parser.error("without --check these are required: "
                     + ", ".join(flag for flag, _ in _GENERATE_FLAGS if flag not in given))
    if args.out.resolve() == args.allow_out.resolve():
        parser.error("--out and --allow-out must be different files")
    return _run_generate(args)


def _run_check(args) -> int:
    try:
        measured, differ = check(args)
    except Exception as e:  # noqa: BLE001  (a traceback would exit 1, which here means "differs")
        error = str(e) if isinstance(e, CannotGenerate) else f"{type(e).__name__}: {e}"
        print(f"CANNOT CHECK: {error}", file=sys.stderr)
        return 2
    head = f"MENTIONS properties of a {args.a}, b {args.b} against {args.check}"
    if differ:
        print("\n".join([f"MISMATCH: {head}: {len(differ)} counts differ", *(f"  {line}" for line in differ)]),
              file=sys.stderr)
        return 1
    print("\n".join([f"residuals_expect --check: {head}: equal", *props_summary(measured)]))
    return 0


def _run_generate(args) -> int:
    try:
        doc, fragment = generate(args)
        written = _write_all([(args.out, json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"),
                              (args.allow_out, fragment)])
    except Mismatch as e:
        print(f"MISMATCH: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  (a traceback would exit 1, which here means "mismatch")
        error = str(e) if isinstance(e, CannotGenerate) else f"{type(e).__name__}: {e}"
        print(f"CANNOT GENERATE: {error}", file=sys.stderr)
        return 2
    print("\n".join(summary(doc, len(diff_kg.parse_allowlist(fragment, args.allow_out)))))
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())

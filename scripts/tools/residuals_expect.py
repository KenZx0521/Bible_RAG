#!/usr/bin/env python3
"""W1 residual expectations (batch 1A-T5; plan docs/records/2026-10-04_kg_batch1_plan.md
§3 expected files first, §4 「R1 2,124 與 4 個實體的 mention_count 殘差」, K10).

The batch-0 rebuild left residuals that W1 promotes as they are: Entity.mention_count
differs from prod on a few entities (1D unifies its definition), and R1 (MENTIONS in
the book-name region) reads higher. W1 changes neither MENTIONS nor entities, so the
W1 staging must show exactly the residuals the batch-0 staging (b) shows now. This
reads them before W1 step 2 rebuilds b, and writes:
  --out        the expected file: {version, basis: {a, b: {target, neo4j_uri, entities,
               sourced_semantic_edges}, at (when b was read), git_head, premise,
               validate_kg: {a, b: {origin, sha256}}}, mention_count: {entity_id: {a, b,
               delta}}, validate_kg: {R1: {a, b}}}. At R2, validate_kg's R1 on the W1
               staging must equal validate_kg.R1.b.
  --allow-out  1A's residuals fragment of the merged W1 allowlist, in diff_kg's --allow
               YAML (diff_kg.render_allowlist): one exact entry per entity whose
               mention_count differs (section mention_count, key the entity_id, delta
               b - a). The merged allowlist takes mention_count from this fragment only;
               diff_kg --merge-out joins it with relations_allow.yaml and 1B's fragment.

mention_count is read with diff_kg's own PROFILE_QUERIES["entities"] and compared
with diff_kg.diff_entities, so the keys and deltas are the ones diff_kg reports at R2.
R1 is book_region_mentions from validate_kg --live --json reports on the same two
targets (--validate-a, --validate-b), never typed by hand: a report's origin must name
the target this tool resolves (live:NAME (URI)), and its R1 must be a measured integer.
validate_kg's own exit code does not matter here (prod fails the 1A and 1B checks
until the W1 promotion).

Exit codes: 0 both files written; 1 the two sides do not hold the same entity ids
(the premise fails: find out why first); 2 cannot generate: usage, a validate_kg report
that is not that target's live R1 (checked before either target is read), b holding a
semantic edge with a source (6.05's edges: b is no longer the batch-0 build, and a
residual read off the W1 build would certify it, plan §3), a differing mention_count
that is not an integer on both sides (diff_kg gives it no delta, so no exact entry
could allow it), an entity_id read twice or holding glob characters, an unreadable
target or output path. Nothing is written on 1, and nothing on 2 unless a write itself
failed.

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
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
R1_METRIC = "book_region_mentions"
_GLOB = re.compile(r"[*?\[]")
PREMISE = ("W1 不改 MENTIONS 與實體：W1 staging 的 mention_count 與 R1 必須等於 b（batch-0 staging，"
           "於 W1 Step 2 重建前讀取，語意邊皆無 source）。R2 時 diff_kg 的 mention_count 差異須恰為本檔各實體，"
           "validate_kg 的 R1 須等於 validate_kg.R1.b。")
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
    """An input or a target cannot give the expectation (exit 2)."""


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


def read_side(target) -> dict:
    """{entities: {entity_id: row}, sourced: semantic edges with a source} of one target, READ only."""
    try:
        driver = open_neo4j(target)
        try:
            driver.verify_connectivity()  # fail fast instead of retrying a refused connection
            rows = read_query(driver, ENTITIES_CYPHER)
            sourced = read_query(driver, SOURCED_EDGES_CYPHER)[0]["n"]
        finally:
            driver.close()
    except Exception as e:  # noqa: BLE001  (an unreadable target cannot give a residual)
        raise CannotGenerate(f"{target.name} not readable: {type(e).__name__}: {e}") from e
    entities = {r["entity_id"]: r for r in rows}
    if len(entities) != len(rows):
        repeated = sorted(eid for eid, n in Counter(r["entity_id"] for r in rows).items() if n > 1)
        raise CannotGenerate(f"{target.name}: entity_id read more than once: {repeated[:10]}")
    return {"entities": entities, "sourced": sourced}


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


def build(targets: dict, sides: dict, r1: dict, at: str) -> tuple[dict, str]:
    """(the expected file document, the fragment's YAML)."""
    if sides["b"]["sourced"]:
        raise CannotGenerate(f"b ({targets['b'].name}) holds {sides['b']['sourced']:,} semantic edges with a "
                             "source: it is no longer the batch-0 build; the residuals must be read before "
                             "W1 step 2 (plan §3)")
    mention_count = residuals(sides["a"]["entities"], sides["b"]["entities"])
    basis = {side: {"target": targets[side].name, "neo4j_uri": targets[side].neo4j_uri,
                    "entities": len(sides[side]["entities"]), "sourced_semantic_edges": sides[side]["sourced"]}
             for side in ("a", "b")}
    doc = {"version": 1,
           "basis": {**basis, "at": at, "git_head": git_head(), "premise": PREMISE,
                     "validate_kg": {side: r1[side][1] for side in ("a", "b")}},
           "mention_count": mention_count,
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


# --- output ----------------------------------------------------------------------

def summary(doc: dict, entries: int) -> list[str]:
    basis, r1 = doc["basis"], doc["validate_kg"]["R1"]
    a, b = basis["a"], basis["b"]
    return [
        f"residuals_expect: a {a['target']} ({a['neo4j_uri']}), b {b['target']} ({b['neo4j_uri']})",
        f"  entities: {a['entities']:,} each; b semantic edges with a source: {b['sourced_semantic_edges']} "
        "(batch-0 build)",
        f"  mention_count: {len(doc['mention_count'])} of {a['entities']:,} entities differ",
        *(f"    {eid} {d['a']} -> {d['b']} ({d['delta']:+d})" for eid, d in doc["mention_count"].items()),
        f"  R1 {R1_METRIC}: {r1['a']:,} -> {r1['b']:,}",
        f"  fragment: {entries} entries",
    ]


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}  {path}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", choices=("prod", "staging"), default="prod",
                        help="diff_kg's a side, the graph the deltas are taken from (default prod)")
    parser.add_argument("--b", choices=("prod", "staging"), default="staging",
                        help="diff_kg's b side, still holding the batch-0 build (default staging)")
    parser.add_argument("--validate-a", type=Path, required=True,
                        help="validate_kg --live --target <a> --json report (R1 of a)")
    parser.add_argument("--validate-b", type=Path, required=True,
                        help="validate_kg --live --target <b> --json report (R1 of b)")
    parser.add_argument("--out", type=Path, required=True, help="the expected file (JSON) to write")
    parser.add_argument("--allow-out", type=Path, required=True, help="the allowlist fragment (YAML) to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.a == args.b:
        parser.error("--a and --b must name different targets")
    if args.out.resolve() == args.allow_out.resolve():
        parser.error("--out and --allow-out must be different files")
    try:
        doc, fragment = generate(args)
        written = [_write(args.out, json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"),
                   _write(args.allow_out, fragment)]
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

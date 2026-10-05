#!/usr/bin/env python3
"""Diff two KG targets, read-only: live prod vs a staging rebuild (batch-0 R2 gate).

docs/staging_promotion.md R2 asks that a batch-0 equivalence rebuild match live
"per E–E phase" and "description replay verbatim", with every allowed
difference listed and explained. validate_kg scores one graph against its
baseline and check_identity compares the three stores of one target; neither
compares two graphs. This does, on Neo4j (the store retrieval reads):

  labels           node count per label
  relationships    edge count per relationship type
  ee_edges         Entity–Entity edges per "TYPE phase=P source=S"
  mentions         MENTIONS edges per "SourceLabel source=S"
  xrefs            CROSS_REFERENCES per "source=S"
  xref_provenance  CROSS_REFERENCES per "source=S curated=C tsk=T": the flags Steps 5
                   and 9 write, keyed as xref_probe expect files' xref_provenance
  entity_ids       entity_id present on one side only
  descriptions     Entity.description, verbatim (missing == empty)
  aliases          Entity.aliases as sets (missing == []); a non-list (JSON string)
                   only equals itself
  mention_count    Entity.mention_count per entity_id on both sides (missing == null,
                   which never equals a number); a delta only between two numbers
  registry        export_event_registry.build_registry() run against each side's
                   read-only driver: one key per event that differs, plus "dropped:<id>"
                   for the dropped list
Unset properties print as "-" in keys.

Allowed differences come from a YAML file (--allow). Every difference not
matched by an entry exits 1; entries that matched nothing are listed so a
stale allowance gets noticed, and with --fail-on-unused they exit 1 as well (a
difference uses only the first entry it matches, so an entry shadowed by an
earlier one counts as unused). Entry fields: section, key (fnmatch glob over
the keys above), reason (both non-empty strings, required), and for the count
sections and mention_count at most one bound: delta (exact b - a, an integer)
or max_abs_delta (a non-negative integer). Validation is strict: an unknown field (a misspelt
bound such as max_delta) or a mistyped value is an error, never ignored,
because an ignored bound would make the entry allow any delta. The file
holds version: 1 and allow, nothing else:

    version: 1
    allow:
      - section: ee_edges
        key: "OCCURRED_IN phase=5 *"
        delta: -12
        reason: 10.3 co-occurrence edges are rebuilt from cleaned MENTIONS (EV-03)

Targets resolve through check_identity.resolve_target, whose guards apply:
--a prod is refused in a shell that exports staging settings, so run this
from a shell without them (staging then resolves to bolt://localhost:7688).
Every read is a READ session (execute_read, or READ access for the registry
builder's auto-commit runs).

Usage (from the project root):
    scripts/.venv/bin/python scripts/tools/diff_kg.py                       # prod vs staging
    scripts/.venv/bin/python scripts/tools/diff_kg.py --allow <allow.yaml> --json
    scripts/.venv/bin/python scripts/tools/diff_kg.py --a prod --b staging --allow <allow.yaml> --fail-on-unused --json

Exit code: 0 every difference is allowed (and, under --fail-on-unused, every
allow entry matched one); 1 a difference is not allowed, an allow entry matched
nothing under --fail-on-unused, or a target / the registry could not be read.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from check_identity import open_neo4j, read_query, resolve_target  # noqa: E402

PROFILE_QUERIES = {
    "labels": "MATCH (n) UNWIND labels(n) AS label RETURN label AS key, count(*) AS n",
    "relationships": "MATCH ()-[r]->() RETURN type(r) AS key, count(*) AS n",
    "ee_edges": """
        MATCH (:Entity)-[r]->(:Entity) WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']
        RETURN type(r) AS type, r.extraction_phase AS phase, r.source AS source, count(*) AS n""",
    "mentions": """
        MATCH (s)-[m:MENTIONS]->(:Entity)
        RETURN CASE WHEN s:Chunk THEN 'Chunk' WHEN s:Pericope THEN 'Pericope' ELSE head(labels(s)) END
                   AS source_label, m.source AS source, count(*) AS n""",
    "xrefs": """
        MATCH (:Pericope)-[x:CROSS_REFERENCES]->(:Pericope)
        RETURN x.source AS source, count(*) AS n""",
    "xref_provenance": """
        MATCH (:Pericope)-[x:CROSS_REFERENCES]->(:Pericope)
        RETURN x.source AS source, x.curated AS curated, x.tsk AS tsk, count(*) AS n""",
    "entities": """
        MATCH (e:Entity)
        RETURN e.entity_id AS entity_id, e.description AS description, e.aliases AS aliases,
               e.mention_count AS mention_count""",
}


def _v(value) -> str:
    return "-" if value is None else str(value)


_COUNT_KEYS = {
    "labels": lambda r: r["key"],
    "relationships": lambda r: r["key"],
    "ee_edges": lambda r: f"{r['type']} phase={_v(r['phase'])} source={_v(r['source'])}",
    "mentions": lambda r: f"{r['source_label']} source={_v(r['source'])}",
    "xrefs": lambda r: f"source={_v(r['source'])}",
    "xref_provenance": lambda r: f"source={_v(r['source'])} curated={_v(r['curated'])} tsk={_v(r['tsk'])}",
}
COUNT_SECTIONS = tuple(_COUNT_KEYS)
NUMERIC_SECTIONS = COUNT_SECTIONS + ("mention_count",)  # allow entries may bound their delta
SECTIONS = COUNT_SECTIONS + ("entity_ids", "descriptions", "aliases", "mention_count", "registry")


def read_profile(driver) -> dict:
    """{count section: {key: count}} plus "entities": {entity_id: row}."""
    out: dict = {}
    for section, key_of in _COUNT_KEYS.items():
        counts: Counter = Counter()
        for row in read_query(driver, PROFILE_QUERIES[section]):
            counts[key_of(row)] += row["n"]
        out[section] = dict(counts)
    out["entities"] = {r["entity_id"]: r for r in read_query(driver, PROFILE_QUERIES["entities"])}
    return out


def _diff(section: str, key: str, a, b, **extra) -> dict:
    numeric = isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool)
    return {"section": section, "key": key, "a": a, "b": b, "delta": b - a if numeric else None, **extra}


def diff_counts(section: str, a: dict[str, int], b: dict[str, int]) -> list[dict]:
    return [_diff(section, key, a.get(key, 0), b.get(key, 0))
            for key in sorted(set(a) | set(b)) if a.get(key, 0) != b.get(key, 0)]


def _alias_key(aliases) -> tuple:
    if aliases is None:
        aliases = []
    return ("list", tuple(sorted(set(aliases)))) if isinstance(aliases, list) else ("raw", repr(aliases))


def diff_entities(a: dict[str, dict], b: dict[str, dict]) -> list[dict]:
    out = [_diff("entity_ids", eid, eid in a, eid in b) for eid in sorted(set(a) ^ set(b))]
    for eid in sorted(set(a) & set(b)):
        x, y = a[eid], b[eid]
        if (x["description"] or "") != (y["description"] or ""):
            out.append(_diff("descriptions", eid, x["description"], y["description"]))
        if _alias_key(x["aliases"]) != _alias_key(y["aliases"]):
            out.append(_diff("aliases", eid, x["aliases"], y["aliases"]))
        if x.get("mention_count") != y.get("mention_count"):
            out.append(_diff("mention_count", eid, x.get("mention_count"), y.get("mention_count")))
    return out


def diff_registry(a: dict, b: dict) -> list[dict]:
    out = []
    for group, prefix in (("events", ""), ("dropped", "dropped:")):
        xa = {e["id"]: e for e in a.get(group, [])}
        xb = {e["id"]: e for e in b.get(group, [])}
        for eid in sorted(set(xa) | set(xb)):
            x, y = xa.get(eid), xb.get(eid)
            if x != y:
                fields = sorted(k for k in set(x or {}) | set(y or {}) if (x or {}).get(k) != (y or {}).get(k))
                out.append(_diff("registry", prefix + eid, x, y, fields=fields))
    for key in sorted((set(a) | set(b)) - {"events", "dropped"}):
        if a.get(key) != b.get(key):
            out.append(_diff("registry", f"meta:{key}", a.get(key), b.get(key)))
    return out


class _ReadOnlyDriver:
    """The driver build_registry() is handed: every session pinned to READ
    access (its auto-commit session.run would otherwise be a write-capable
    session), and close() left to diff_kg, which owns the real driver."""

    def __init__(self, driver):
        self._driver = driver

    def session(self, **kwargs):
        from neo4j import READ_ACCESS
        return self._driver.session(**{**kwargs, "default_access_mode": READ_ACCESS})

    def close(self) -> None:
        pass


def registry_from(driver) -> dict:
    """export_event_registry.build_registry() against `driver` (minus generated_at)."""
    # Importing it imports backfill_head_events, which load_dotenv()s .env into
    # os.environ; main() resolves both targets before this runs.
    import export_event_registry as eer
    registry = eer.build_registry(_ReadOnlyDriver(driver))
    return {k: v for k, v in registry.items() if k != "generated_at"}


def compare(driver_a, driver_b, with_registry: bool = True, registry_builder=None) -> tuple[list[dict], list[str]]:
    """(differences, errors) of target b against target a."""
    pa, pb = read_profile(driver_a), read_profile(driver_b)
    diffs = [d for section in COUNT_SECTIONS for d in diff_counts(section, pa[section], pb[section])]
    diffs += diff_entities(pa["entities"], pb["entities"])
    errors: list[str] = []
    if with_registry:
        build = registry_builder or registry_from
        registries = []
        for side, driver in (("a", driver_a), ("b", driver_b)):
            try:
                registries.append(build(driver))
            except Exception as e:  # noqa: BLE001  (a registry that cannot be built is not "equal")
                errors.append(f"registry on {side}: {type(e).__name__}: {e}")
        if not errors:
            diffs += diff_registry(*registries)
    return diffs, errors


ALLOW_FIELDS = ("section", "key", "reason", "delta", "max_abs_delta")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _entry_problem(entry) -> str | None:
    """Why an allow entry is invalid, or None (rules in the module docstring)."""
    if not isinstance(entry, dict):
        return "must be a mapping"
    unknown = sorted(set(entry) - set(ALLOW_FIELDS))
    if unknown:
        return f"has unknown fields {unknown}; allowed: {', '.join(ALLOW_FIELDS)}"
    if entry.get("section") not in SECTIONS:
        return f"needs section, one of {', '.join(SECTIONS)}"
    for name in ("key", "reason"):
        if not isinstance(entry.get(name), str) or not entry[name].strip():
            return f"needs {name} as a non-empty string"
    bounds = [name for name in ("delta", "max_abs_delta") if name in entry]
    if bounds and entry["section"] not in NUMERIC_SECTIONS:
        return f"delta/max_abs_delta only apply to {', '.join(NUMERIC_SECTIONS)}"
    if len(bounds) > 1:
        return "takes delta or max_abs_delta, not both"
    if "delta" in entry and not _is_int(entry["delta"]):
        return f"delta must be an integer, not {entry['delta']!r}"
    if "max_abs_delta" in entry and not (_is_int(entry["max_abs_delta"]) and entry["max_abs_delta"] >= 0):
        return f"max_abs_delta must be a non-negative integer, not {entry['max_abs_delta']!r}"
    return None


def load_allowlist(path) -> list[dict]:
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or set(doc) - {"version", "allow"} or doc.get("version") != 1
            or not isinstance(doc.get("allow", []), (list, type(None)))):  # `allow:` alone is empty
        raise ValueError(f"{path}: expected a mapping of version: 1 and an allow list, and nothing else")
    entries = doc.get("allow") or []
    for i, entry in enumerate(entries):
        problem = _entry_problem(entry)
        if problem:
            raise ValueError(f"{path}: allow[{i}] {problem}")
    return entries


def _matches(entry: dict, diff: dict) -> bool:
    if entry["section"] != diff["section"] or not fnmatch.fnmatchcase(diff["key"], entry["key"]):
        return False
    if "delta" in entry:
        return diff["delta"] == entry["delta"]
    if "max_abs_delta" in entry:
        return diff["delta"] is not None and abs(diff["delta"]) <= entry["max_abs_delta"]
    return True


def classify(diffs: list[dict], allow: list[dict]) -> tuple[list[dict], list[dict]]:
    """Each difference with `allowed_by` (the matching entry's reason or None),
    and the allow entries that matched nothing."""
    used, out = set(), []
    for diff in diffs:
        hit = next((i for i, entry in enumerate(allow) if _matches(entry, diff)), None)
        if hit is not None:
            used.add(hit)
        out.append({**diff, "allowed_by": allow[hit]["reason"] if hit is not None else None})
    return out, [entry for i, entry in enumerate(allow) if i not in used]


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return text if len(text) <= 60 else text[:57] + "…"


def print_report(report: dict, samples: int) -> None:
    print(f"KG diff — a={report['a']}  b={report['b']}")
    for section in SECTIONS:
        diffs = [d for d in report["differences"] if d["section"] == section]
        if not diffs:
            continue
        bad = sum(d["allowed_by"] is None for d in diffs)
        print(f"  {section:<15} {len(diffs)} differences ({bad} not allowed)")
        # unallowed first: they are what the operator has to explain
        for d in sorted(diffs, key=lambda d: d["allowed_by"] is not None)[:samples]:
            change = f"{d['a']} -> {d['b']} ({d['delta']:+d})" if d["delta"] is not None \
                else f"{_short(d['a'])} -> {_short(d['b'])}"
            if d.get("fields"):
                change += f" fields {d['fields']}"
            mark = f"[allowed: {d['allowed_by']}]" if d["allowed_by"] else "[NOT ALLOWED]"
            print(f"    {d['key']}: {change}  {mark}")
    for entry in report["unused_allowances"]:
        print(f"  unused allowance: {entry['section']} {entry['key']} ({entry['reason']})")
    for error in report["errors"]:
        print(f"  ERROR {error}")
    print(f"exit {report['exit_code']}: {_exit_reason(report)}")


def _exit_reason(report: dict) -> str:
    strict = report["fail_on_unused"]
    if report["exit_code"] == 0:
        return "every difference is allowed" + (" and every allowance is used" if strict else "")
    unallowed = sum(d["allowed_by"] is None for d in report["differences"])
    reason = f"{unallowed} differences not allowed, {len(report['errors'])} errors"
    return reason + (f", {len(report['unused_allowances'])} unused allowances" if strict else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", choices=("prod", "staging"), default="prod", help="reference target (default prod)")
    parser.add_argument("--b", choices=("prod", "staging"), default="staging", help="compared target (default staging)")
    parser.add_argument("--allow", type=Path, help="YAML list of allowed differences (format above)")
    parser.add_argument("--no-registry", action="store_true", help="skip the export_event_registry diff")
    parser.add_argument("--samples", type=int, default=10, help="differences printed per section")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--fail-on-unused", action="store_true",
                        help="exit 1 when an allow entry matched no difference (without it they are only listed)")
    args = parser.parse_args(argv)
    if args.a == args.b:
        parser.error("--a and --b must name different targets")
    allow = load_allowlist(args.allow) if args.allow else []

    drivers, names = {}, {}
    try:
        targets = {side: resolve_target(name) for side, name in (("a", args.a), ("b", args.b))}
        for side, target in targets.items():
            names[side] = f"{target.name} ({target.neo4j_uri})"
            drivers[side] = open_neo4j(target)
            drivers[side].verify_connectivity()  # fail fast instead of retrying a refused connection
        diffs, errors = compare(drivers["a"], drivers["b"], with_registry=not args.no_registry)
    except Exception as e:  # noqa: BLE001  (an unreadable target is never "equal")
        print(f"ERROR: cannot diff {args.a} vs {args.b}: {e}", file=sys.stderr)
        return 1
    finally:
        for driver in drivers.values():
            driver.close()

    classified, unused = classify(diffs, allow)
    failed = errors or any(d["allowed_by"] is None for d in classified) or (args.fail_on_unused and unused)
    report = {"a": names["a"], "b": names["b"], "exit_code": 1 if failed else 0,
              "fail_on_unused": args.fail_on_unused, "errors": errors,
              "differences": classified, "unused_allowances": unused}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print_report(report, args.samples)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

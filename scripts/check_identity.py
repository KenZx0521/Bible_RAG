#!/usr/bin/env python3
"""Three-store entity identity check: Neo4j vs PostgreSQL vs Qdrant (plan §3.6 H5).

Context (docs/records/2026-10-04_kg_data_layer_fix_plan.md §3.3): the entity
layer is projected into three stores by steps that ran at different times, so
the stores drifted even though their id sets agree. PG ``entities`` was loaded
by Step 3 before Step 7 wrote Person/Place/Group descriptions (all empty in
PG), Qdrant ``bible_entities`` was embedded by Step 8 before 10.1 aliases and
stores aliases as JSON strings, and the 10.x patches only wrote Neo4j. This
check makes that drift measurable until the compile-then-project loader (1D)
removes it structurally.

Neo4j is the reference (it is what retrieval reads). PG ``entities`` and the
Qdrant entity collection are compared against it on:
  * the entity_id set (both directions),
  * type (Neo4j: the single type label; PG: ``type``; Qdrant: payload ``type``),
  * canonical_name (exact, so whitespace drift counts),
  * aliases — must be a list in every store; lists compare as sets,
  * description (missing == empty string).

Read-only: Neo4j read transactions, a read-only PG session, Qdrant scroll.

Targets (``--target``) choose which stores NEO4J_URI / POSTGRES_DB /
QDRANT_ENTITY_COLLECTION resolve to; both directions are guarded, because
the staging flow (docs/build_database.md R1) exports staging values in the
operator's shell while .env keeps pointing at production:
  * ``staging`` reads the shell only, then the staging defaults
    (bolt://localhost:7688, bible_rag_staging, no Qdrant default because the
    staging collection is versioned bible_entities_vN). It refuses a store
    that resolves to production: the .env/default prod value, or any Neo4j
    URI landing on port 7687 (a URI without a port defaults to it).
  * ``prod`` is the .env value, else the prod default. A shell value that
    differs from it (a staging shell left open for R4), KG_TARGET=staging,
    Neo4j port 7688 or POSTGRES_DB=bible_rag_staging is refused instead of
    being read and reported as prod. The prod Qdrant collection is whatever
    .env names: R3 promotes by pointing it at bible_entities_vN.
Credentials come from the shell, then .env, for both targets. The Qdrant
port follows the scripts' convention: QDRANT_PORT, then QDRANT_HTTP_PORT.

``--fail-on`` picks the difference kinds that decide the exit code (default:
all). Batch 0 gates on ``--fail-on id`` because PG descriptions and Qdrant
string aliases differ by design until batch 1D; every kind is still reported.

Usage (from the project root):
    scripts/.venv/bin/python scripts/check_identity.py
    QDRANT_ENTITY_COLLECTION=bible_entities_v2 \\
        scripts/.venv/bin/python scripts/check_identity.py --target staging --fail-on id --json

Exit code: 0 the selected kinds agree in every store; 1 a selected kind
differs, a store was skipped (not compared is not "consistent"), or a store
could not be read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

TYPE_LABELS = ("Person", "Place", "Group", "Event", "Object", "Theme")
DIFF_KINDS = ("only_in_reference", "only_in_store", "type", "canonical_name",
              "aliases_not_list", "aliases", "description")

# --fail-on group -> the DIFF_KINDS it covers ("aliases" also covers Neo4j's own).
FAIL_ON = {
    "id": ("only_in_reference", "only_in_store"),
    "type": ("type",),
    "canonical": ("canonical_name",),
    "aliases": ("aliases_not_list", "aliases"),
    "description": ("description",),
}

# Keys that select WHICH store is read. Everything else is a credential.
_STORE_KEYS = ("NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION")
# Same production rule as kg_target: a Neo4j on 7687 (the driver default when a
# URI has no port) is production; 7688 is the staging container's bolt port.
_PROD_NEO4J_PORT = 7687
_STAGING_NEO4J_PORT = 7688
_STAGING_PG_DB = "bible_rag_staging"
_STORE_DEFAULTS: dict[str, dict[str, str | None]] = {
    "prod": {"NEO4J_URI": "bolt://localhost:7687", "POSTGRES_DB": "bible_rag",
             "QDRANT_ENTITY_COLLECTION": "bible_entities"},
    "staging": {"NEO4J_URI": "bolt://localhost:7688", "POSTGRES_DB": "bible_rag_staging",
                "QDRANT_ENTITY_COLLECTION": None},
}
# Same defaults as backfill_head_events.get_neo4j/get_pg and import_qdrant.
_CREDENTIAL_DEFAULTS = {
    "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "neo4j_password",
    "POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "bible", "POSTGRES_PASSWORD": "bible_password",
    "QDRANT_HOST": "localhost", "QDRANT_HTTP_PORT": "6333",
}


@dataclass(frozen=True)
class Target:
    name: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    qdrant_host: str
    qdrant_port: int
    qdrant_collection: str | None


def _read_dotenv() -> dict[str, str]:
    """.env as a dict WITHOUT touching os.environ (load_dotenv would make the
    prod NEO4J_URI look like a shell override and leak into staging)."""
    path = _PROJECT_ROOT / ".env"
    if not path.exists():
        return {}
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _endpoint(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    host = parsed.hostname or ""
    return ("localhost" if host in ("127.0.0.1", "::1") else host), parsed.port or _PROD_NEO4J_PORT


def _same_store(key: str, a: str, b: str) -> bool:
    return _endpoint(a) == _endpoint(b) if key == "NEO4J_URI" else a == b


def _staging_problems(values: Mapping[str, str | None], dotenv: Mapping[str, str]) -> list[str]:
    problems = []
    if _endpoint(values["NEO4J_URI"])[1] == _PROD_NEO4J_PORT:
        problems.append(f"staging NEO4J_URI {values['NEO4J_URI']} is the prod endpoint (port {_PROD_NEO4J_PORT})")
    for prod in ({k: dotenv.get(k) for k in _STORE_KEYS}, _STORE_DEFAULTS["prod"]):
        for key in _STORE_KEYS:
            if values[key] is not None and prod[key] and _same_store(key, values[key], prod[key]):
                problems.append(f"staging {key}={values[key]} is the prod store")
    return sorted(set(problems))


def _prod_problems(environ: Mapping[str, str], dotenv: Mapping[str, str],
                   values: Mapping[str, str | None]) -> list[str]:
    problems = []
    if environ.get("KG_TARGET") == "staging":
        problems.append("KG_TARGET=staging is exported: this shell is set up for staging")
    for key in _STORE_KEYS:
        prod, shell = dotenv.get(key) or _STORE_DEFAULTS["prod"][key], environ.get(key)
        if shell and not _same_store(key, shell, prod):
            problems.append(f"shell {key}={shell} differs from the prod value {prod} (.env)")
    if _endpoint(values["NEO4J_URI"])[1] == _STAGING_NEO4J_PORT:
        problems.append(f"NEO4J_URI {values['NEO4J_URI']} is the staging port {_STAGING_NEO4J_PORT}")
    if values["POSTGRES_DB"] == _STAGING_PG_DB:
        problems.append(f"POSTGRES_DB={_STAGING_PG_DB} is the staging database")
    return problems


def resolve_target(name: str, environ: Mapping[str, str] | None = None,
                   dotenv: Mapping[str, str] | None = None) -> Target:
    """Resolve store endpoints for prod or staging (see module docstring);
    ValueError when the result would read the other target's stores."""
    if name not in _STORE_DEFAULTS:
        raise ValueError(f"unknown target {name!r}; expected one of {sorted(_STORE_DEFAULTS)}")
    environ = os.environ if environ is None else environ
    dotenv = _read_dotenv() if dotenv is None else dotenv

    def setting(key: str) -> str | None:
        return environ.get(key) or dotenv.get(key)

    def cred(key: str) -> str:
        return setting(key) or _CREDENTIAL_DEFAULTS[key]

    def store(key: str) -> str | None:
        if name == "prod":
            return environ.get(key) or dotenv.get(key) or _STORE_DEFAULTS["prod"][key]
        return environ.get(key) or _STORE_DEFAULTS["staging"][key]

    values = {key: store(key) for key in _STORE_KEYS}
    problems = _staging_problems(values, dotenv) if name == "staging" else _prod_problems(environ, dotenv, values)
    if problems:
        hint = ("open a shell without the staging exports (docs/build_database.md R4)" if name == "prod"
                else "export the staging settings (docs/build_database.md R1)")
        raise ValueError(f"--target {name} refused: " + "; ".join(problems) + f"; {hint}")

    return Target(
        name=name,
        neo4j_uri=values["NEO4J_URI"],
        neo4j_user=cred("NEO4J_USER"),
        neo4j_password=cred("NEO4J_PASSWORD"),
        pg_host=cred("POSTGRES_HOST"),
        pg_port=int(cred("POSTGRES_PORT")),
        pg_db=values["POSTGRES_DB"],
        pg_user=cred("POSTGRES_USER"),
        pg_password=cred("POSTGRES_PASSWORD"),
        qdrant_host=cred("QDRANT_HOST"),
        # QDRANT_PORT first, like the scripts that write (F's convention)
        qdrant_port=int(setting("QDRANT_PORT") or cred("QDRANT_HTTP_PORT")),
        qdrant_collection=values["QDRANT_ENTITY_COLLECTION"],
    )


# ---------------------------------------------------------------------------
# Store readers (all read-only)
# ---------------------------------------------------------------------------

def open_neo4j(target: Target):
    from neo4j import GraphDatabase
    # The quality gate deliberately reads properties that later fix batches add
    # (source_region, tsk, curated); the server's "unknown property" notices for
    # them are expected, so they are switched off rather than logged per query.
    return GraphDatabase.driver(target.neo4j_uri, auth=(target.neo4j_user, target.neo4j_password),
                                notifications_min_severity="OFF")


def read_query(driver, cypher: str, **params) -> list[dict]:
    """Run one Cypher statement in a READ transaction (the server rejects writes)."""
    from neo4j import READ_ACCESS
    with driver.session(default_access_mode=READ_ACCESS) as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])


_NEO4J_ENTITIES = """
MATCH (e:Entity)
RETURN e.entity_id AS entity_id, [l IN labels(e) WHERE l IN $types] AS types,
       e.canonical_name AS canonical_name, e.aliases AS aliases, e.description AS description
"""


def type_of(labels: Iterable[str]) -> str | None:
    """The single type label; a node with zero or several is an H2 failure,
    so it stays visible as a joined label instead of a guessed one."""
    types = sorted(label for label in labels if label in TYPE_LABELS)
    return types[0] if len(types) == 1 else "|".join(types) or None


def records_from_neo4j_rows(rows: Iterable[Mapping]) -> dict[str, dict]:
    out = {}
    for r in rows:
        out[r["entity_id"]] = {
            "type": type_of(r["types"]),
            "canonical_name": r["canonical_name"],
            "aliases": r["aliases"],
            "description": r["description"],
        }
    return out


def records_from_payloads(rows: Iterable[Mapping]) -> dict[str, dict]:
    """PG rows and Qdrant payloads share field names; aliases are kept as stored."""
    return {
        r["entity_id"]: {
            "type": r.get("type"),
            "canonical_name": r.get("canonical_name"),
            "aliases": r.get("aliases"),
            "description": r.get("description"),
        }
        for r in rows
    }


def load_neo4j_records(target: Target) -> dict[str, dict]:
    driver = open_neo4j(target)
    try:
        return records_from_neo4j_rows(read_query(driver, _NEO4J_ENTITIES, types=list(TYPE_LABELS)))
    finally:
        driver.close()


def load_pg_records(target: Target) -> dict[str, dict]:
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(host=target.pg_host, port=target.pg_port, dbname=target.pg_db,
                            user=target.pg_user, password=target.pg_password)
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT entity_id, type, canonical_name, aliases, description FROM entities")
            return records_from_payloads(cur.fetchall())
    finally:
        conn.close()


def load_qdrant_records(target: Target) -> dict[str, dict]:
    from qdrant_client import QdrantClient
    # The scripts venv pins qdrant-client 1.17 against a 1.13 server; scroll is
    # wire-compatible, so skip the version warning instead of printing it per run.
    client = QdrantClient(host=target.qdrant_host, port=target.qdrant_port, check_compatibility=False)
    fields = ["entity_id", "type", "canonical_name", "aliases", "description"]
    payloads, offset = [], None
    while True:
        points, offset = client.scroll(target.qdrant_collection, limit=1000, offset=offset,
                                       with_payload=fields, with_vectors=False)
        payloads.extend(p.payload for p in points)
        if offset is None:
            return records_from_payloads(payloads)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _alias_key(aliases) -> tuple[str, ...]:
    return tuple(sorted(set(aliases)))


def compare(reference: Mapping[str, dict], other: Mapping[str, dict], sample_size: int = 5) -> dict:
    """Count and sample every difference of `other` against `reference`."""
    counts = dict.fromkeys(DIFF_KINDS, 0)
    samples: dict[str, list] = {k: [] for k in DIFF_KINDS}

    def hit(kind: str, sample) -> None:
        counts[kind] += 1
        if len(samples[kind]) < sample_size:
            samples[kind].append(sample)

    for eid in sorted(set(reference) - set(other)):
        hit("only_in_reference", eid)
    for eid in sorted(set(other) - set(reference)):
        hit("only_in_store", eid)

    for eid in sorted(set(reference) & set(other)):
        ref, cur = reference[eid], other[eid]
        for field in ("type", "canonical_name"):
            if ref[field] != cur[field]:
                hit(field, {"entity_id": eid, "reference": ref[field], "store": cur[field]})
        if (ref["description"] or "") != (cur["description"] or ""):
            hit("description", {"entity_id": eid, "reference": (ref["description"] or "")[:60],
                                "store": (cur["description"] or "")[:60]})
        if not isinstance(cur["aliases"], list):
            hit("aliases_not_list", {"entity_id": eid, "store": repr(cur["aliases"])[:60]})
        elif isinstance(ref["aliases"], list) and _alias_key(ref["aliases"]) != _alias_key(cur["aliases"]):
            hit("aliases", {"entity_id": eid, "reference": ref["aliases"], "store": cur["aliases"]})

    return {"counts": counts, "samples": samples}


def run(target: Target, sample_size: int = 5, reference: Mapping[str, dict] | None = None) -> dict:
    """Compare PG and Qdrant against Neo4j. `reference` skips re-reading Neo4j."""
    if reference is None:
        reference = load_neo4j_records(target)
    report = {
        "target": target.name,
        "neo4j_uri": target.neo4j_uri,
        "reference_count": len(reference),
        "reference_aliases_not_list": sum(1 for r in reference.values() if not isinstance(r["aliases"], list)),
        "stores": {},
    }
    pg = load_pg_records(target)
    report["stores"]["pg"] = {"store": f"postgres:{target.pg_db}.entities", "count": len(pg),
                              **compare(reference, pg, sample_size)}
    if target.qdrant_collection is None:
        report["stores"]["qdrant"] = {"skipped": "no entity collection for this target; "
                                                 "set QDRANT_ENTITY_COLLECTION=bible_entities_vN"}
    else:
        qd = load_qdrant_records(target)
        report["stores"]["qdrant"] = {"store": f"qdrant:{target.qdrant_collection}", "count": len(qd),
                                      **compare(reference, qd, sample_size)}
    return report


def has_differences(report: Mapping, fail_on: Iterable[str] = tuple(FAIL_ON)) -> bool:
    """True when a difference of a selected --fail-on group was found."""
    fail_on = set(fail_on)
    if "aliases" in fail_on and report.get("reference_aliases_not_list"):
        return True
    kinds = [kind for group in fail_on for kind in FAIL_ON[group]]
    return any(store["counts"][kind] for store in report["stores"].values() if "counts" in store
               for kind in kinds)


def skipped_stores(report: Mapping) -> list[str]:
    return [name for name, store in report["stores"].items() if "skipped" in store]


def _print_report(report: Mapping, fail_on: Iterable[str] = tuple(FAIL_ON)) -> None:
    counted = {kind for group in fail_on for kind in FAIL_ON[group]}
    print(f"Identity check — target {report['target']} ({report['neo4j_uri']}), "
          f"Neo4j entities: {report['reference_count']}; --fail-on {','.join(fail_on)}")
    if report["reference_aliases_not_list"]:
        print(f"  neo4j aliases not a list: {report['reference_aliases_not_list']}")
    for name, store in report["stores"].items():
        if "skipped" in store:
            print(f"  {name}: SKIPPED — {store['skipped']}")
            continue
        print(f"  {name} ({store['store']}, {store['count']} rows)")
        for kind in DIFF_KINDS:
            n = store["counts"][kind]
            line = f"    {kind:<18} {n:>6}" + ("" if kind in counted else "  (not in --fail-on)")
            if n:
                line += f"  e.g. {json.dumps(store['samples'][kind][:3], ensure_ascii=False)}"
            print(line)


def _fail_on(value: str) -> tuple[str, ...]:
    groups = tuple(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    unknown = sorted(set(groups) - set(FAIL_ON))
    if unknown or not groups:
        raise argparse.ArgumentTypeError(f"unknown kinds {unknown}; choose from {','.join(FAIL_ON)}")
    return groups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=sorted(_STORE_DEFAULTS), default="prod",
                        help="which stores to read (default prod)")
    parser.add_argument("--fail-on", type=_fail_on, default=tuple(FAIL_ON), metavar="KINDS",
                        help=f"comma-separated difference kinds that fail the run (default: {','.join(FAIL_ON)})")
    parser.add_argument("--samples", type=int, default=5, help="samples kept per difference kind")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    try:
        report = run(resolve_target(args.target), sample_size=args.samples)
    except Exception as e:  # noqa: BLE001  (an unreadable store is never "consistent")
        print(f"ERROR: cannot read {args.target}: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({**report, "fail_on": list(args.fail_on)}, ensure_ascii=False, indent=2))
    else:
        _print_report(report, args.fail_on)
    skipped = skipped_stores(report)
    if skipped:
        print(f"ERROR: {', '.join(skipped)} not compared; a skipped store cannot pass", file=sys.stderr)
        return 1
    return 1 if has_differences(report, args.fail_on) else 0


if __name__ == "__main__":
    sys.exit(main())

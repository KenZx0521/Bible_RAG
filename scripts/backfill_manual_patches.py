#!/usr/bin/env python3
"""Freeze ad-hoc manual graph edits into a replayable curated patch.

Context (docs/architecture_verification + 2026-07-08 live audit): the live
graph contains 106 MENTIONS edges with **no provenance at all** (text_span /
backfilled / curated / source / source_granularity all null) plus at least
two :Event nodes (受難週, 大使命) that exist in no JSONL artifact. They were
added by hand-typed Cypher during retrieval debugging (2026-05 EVENT_008/011,
2026-07 葉忒羅 coreference case) and would silently vanish on any full
rebuild. This script makes them reproducible:

1. ``--export`` — snapshot every no-provenance MENTIONS edge and the entity
   nodes it touches into ``config/curated/manual_graph_patches.jsonl``
   (git-tracked, unlike output/). Nodes are tagged ``origin=manual`` when
   absent from output/entities.jsonl, ``origin=extracted`` otherwise.
2. ``--apply`` — replay the snapshot: MERGE missing manual-origin nodes and
   missing edges (rebuild scenario), stamp provenance (``curated=true,
   source='manual_patch'``) onto matched unmarked edges (live scenario), and
   merge every node row's aliases into its node (order-preserving union,
   canonical name excluded). Other existing property values are never
   overwritten (coalesce only).
   Extracted-origin nodes are never created: if one is missing the run fails
   before writing, because a missing extracted id means the extraction
   re-minted or dropped it, and a MERGE would leave a zombie node (ID-7).
   Three stores stay in sync: Neo4j; PostgreSQL entities (manual rows
   upserted, extracted rows: aliases only); Qdrant bible_entities (manual
   rows re-embedded, extracted rows: aliases payload only). An extracted row
   missing from PG or Qdrant also fails before any store is written (unless
   that store is skipped with --skip-pg / --skip-qdrant).

``--dry-run`` works with both modes: ``--export`` prints what it would write,
``--apply`` prints the plan, including the aliases each node would gain, and
fails where --apply would fail before writing.

Rollback (only objects *created* by --apply carry ``created_from``):
  * edges:   MATCH ()-[m:MENTIONS {created_from:'manual_patch'}]->() DELETE m
  * nodes:   MATCH (e:Entity {created_from:'manual_patch'}) DETACH DELETE e
  * stamps and merged aliases: restore from output/backups/manual_patches_<ts>.jsonl.
    Each node line holds the aliases before the run in Neo4j (aliases_before),
    PG (pg) and Qdrant (qdrant: the raw payload value, legacy JSON string
    included); pg/qdrant are null when that store was skipped. Not backed up:
    the other PG columns of manual rows (upserted whole from the patch) and
    the vectors of re-embedded manual points.

Usage:
    uv run --project scripts python scripts/backfill_manual_patches.py --export [--dry-run]
    uv run --project scripts python scripts/backfill_manual_patches.py --apply --dry-run
    uv run --project scripts python scripts/backfill_manual_patches.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Container, Iterable, Mapping
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))

import kg_target  # noqa: E402
from backfill_head_events import get_neo4j, get_pg, get_qdrant, reembed_qdrant  # noqa: E402

DEFAULT_PATCH_FILE = _PROJECT_ROOT / "config" / "curated" / "manual_graph_patches.jsonl"
ENTITIES_JSONL = _PROJECT_ROOT / "output" / "entities.jsonl"
BACKUP_DIR = _PROJECT_ROOT / "output" / "backups"

# An edge is "manual" iff it carries none of the provenance fields written by
# any importer/backfill script (original import always sets text_span).
_NO_PROVENANCE_WHERE = """
    r.text_span IS NULL AND r.backfilled IS NULL AND r.curated IS NULL
    AND r.source IS NULL AND r.source_granularity IS NULL
"""

_EXPORT_EDGES_CYPHER = f"""
MATCH (p)-[r:MENTIONS]->(e:Entity)
WHERE {_NO_PROVENANCE_WHERE}
RETURN p.id AS pericope_id,
       [l IN labels(p) WHERE l <> 'Bible'][0] AS pericope_label,
       e.entity_id AS entity_id,
       e.canonical_name AS entity_name,
       properties(r) AS props
ORDER BY entity_id, pericope_id
"""

_EXPORT_NODES_CYPHER = f"""
MATCH (p)-[r:MENTIONS]->(e:Entity)
WHERE {_NO_PROVENANCE_WHERE}
WITH DISTINCT e
RETURN e.entity_id AS entity_id, labels(e) AS labels, properties(e) AS props
ORDER BY entity_id
"""


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _extracted_entity_ids() -> set[str] | None:
    """entity_ids present in output/entities.jsonl, or None if absent."""
    if not ENTITIES_JSONL.exists():
        return None
    ids: set[str] = set()
    with ENTITIES_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line)["entity_id"])
    return ids


def export_patches(session, out_path: Path, dry_run: bool = False) -> tuple[int, int]:
    edges = [dict(r) for r in session.run(_EXPORT_EDGES_CYPHER)]
    nodes = [dict(r) for r in session.run(_EXPORT_NODES_CYPHER)]
    if not edges:
        print("  Nothing to export — no unmarked manual edges in the graph.")
        return 0, 0

    odd = [e for e in edges if e["pericope_label"] != "Pericope"]
    if odd:
        raise SystemExit(f"unexpected non-Pericope mention sources: {odd[:5]}")

    known = _extracted_entity_ids()
    if known is None:
        print("  ⚠ output/entities.jsonl missing — node origin recorded as 'unknown'")

    records: list[dict] = [{
        "kind": "meta",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "criteria": "MENTIONS edges with no provenance fields (see script docstring)",
        "edge_count": len(edges),
        "node_count": len(nodes),
    }]
    for n in nodes:
        origin = "unknown" if known is None else (
            "extracted" if n["entity_id"] in known else "manual")
        records.append({
            "kind": "node",
            "entity_id": n["entity_id"],
            "labels": sorted(n["labels"]),
            "origin": origin,
            "props": n["props"],
        })
    for e in edges:
        records.append({
            "kind": "edge",
            "pericope_id": e["pericope_id"],
            "entity_id": e["entity_id"],
            "entity_name": e["entity_name"],
            "props": e["props"],
        })

    manual = [r for r in records if r["kind"] == "node" and r["origin"] == "manual"]
    manual_ids = [n["entity_id"] for n in manual] or "none"
    # The patch file is git-tracked curation: a dry run must not replace it.
    if dry_run:
        print(f"  Would export {len(edges)} edges / {len(nodes)} nodes → {out_path}")
        print(f"  Manual-origin nodes (absent from entities.jsonl): {manual_ids}")
        print("Dry run — nothing written.")
        return len(nodes), len(edges)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"  Exported {len(edges)} edges / {len(nodes)} nodes → {out_path}")
    print(f"  Manual-origin nodes (absent from entities.jsonl): {manual_ids}")
    return len(nodes), len(edges)


# ---------------------------------------------------------------------------
# Replay semantics (shared by --apply, --dry-run and offline simulation)
# ---------------------------------------------------------------------------

def _type_label(node: dict) -> str:
    return next(l for l in node["labels"] if l != "Entity")


def merge_aliases(current: Iterable[str] | None, additions: Iterable[str] | None,
                  canonical: str | None) -> list[str]:
    """Order-preserving union of ``current`` then ``additions``, minus the canonical name.

    Python twin of the apoc.coll.toSet merge in _MERGE_NODE_ALIASES_CYPHER
    (toSet keeps first occurrences; checked on the live APOC), so the PG and
    Qdrant copies and the offline projection get the same list in the same
    order as Neo4j.
    """
    drop = canonical or ""
    return [a for a in dict.fromkeys([*(current or []), *(additions or [])])
            if a is not None and a != drop]


def missing_extracted_ids(nodes: list[dict], present: Container[str]) -> list[str]:
    """Patch nodes that a replay may not create but that are absent.

    Only origin=manual nodes exist in no JSONL artifact, so only they may be
    created. Any other origin ('extracted', or 'unknown' when the export ran
    without entities.jsonl) comes from the extraction: its absence means the
    id was re-minted or the node dropped upstream, and creating it would
    leave a zombie node that carries only the hand-typed edges (ID-7).
    """
    return sorted(n["entity_id"] for n in nodes
                  if n["origin"] != "manual" and n["entity_id"] not in present)


def _missing_extracted_message(missing: list[str]) -> str:
    return (f"extracted patch nodes missing from the graph (re-minted or dropped "
            f"upstream — update the patch, do not recreate them): {missing}")


def overlay_nodes(graph: Mapping[str, dict], nodes: list[dict]) -> dict[str, dict]:
    """Project --apply's node writes onto an offline ``{entity_id: props}`` graph.

    Row-for-row twin of _MERGE_MANUAL_NODES_CYPHER + _MERGE_NODE_ALIASES_CYPHER,
    so a rebuild can be simulated from JSONL (scripts/tests/
    test_registry_rebuild_sim.py) and --dry-run can show the aliases each
    node would gain. Returns a new mapping; ``graph`` is not mutated.
    """
    missing = missing_extracted_ids(nodes, graph.keys())
    if missing:
        raise SystemExit(_missing_extracted_message(missing))

    out = dict(graph)
    for n in nodes:
        eid = n["entity_id"]
        if eid in out:
            props = dict(out[eid])
        else:
            props = {**n["props"], "created_from": "manual_patch"}
        if n["origin"] == "manual":
            if props.get("source") is None:
                props["source"] = "manual_patch"
            if props.get("extraction_method") is None:
                props["extraction_method"] = "curated"
        props["aliases"] = merge_aliases(props.get("aliases"), n["props"].get("aliases"),
                                         props.get("canonical_name"))
        out[eid] = props
    return out


def _as_alias_list(value) -> list[str]:
    """Aliases as a list; legacy Qdrant payloads hold a JSON string ("[]")."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return [value]
        return decoded if isinstance(decoded, list) else [value]
    return list(value)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

_NODE_STATUS_CYPHER = """
UNWIND $ids AS eid
OPTIONAL MATCH (e:Entity {entity_id: eid})
RETURN eid, e IS NOT NULL AS found,
       [l IN labels(e) WHERE l <> 'Entity'] AS labels,
       e.canonical_name AS canonical_name, e.aliases AS aliases
"""

# Manual-origin rows only (formatted per type label): these nodes exist in no
# JSONL artifact, so a rebuild must create them from the frozen props.
_MERGE_MANUAL_NODES_CYPHER = """
UNWIND $rows AS row
MERGE (e:Entity:{label} {{entity_id: row.entity_id}})
ON CREATE SET e += row.props, e.created_from = 'manual_patch'
SET e.source = coalesce(e.source, 'manual_patch'),
    e.extraction_method = coalesce(e.extraction_method, 'curated')
RETURN count(e) AS merged
"""

# Every row, outside any ON CREATE (EV-06): the extracted curated events
# (山上寶訓, both 保羅敘述歸主 events) get their registry triggers only from
# these aliases, and an ON CREATE-only replay dropped them on a full rebuild
# (event_registry 33 → 31 events). MATCH, not MERGE, so it can never create.
_MERGE_NODE_ALIASES_CYPHER = """
UNWIND $rows AS row
MATCH (e:Entity {entity_id: row.entity_id})
SET e.aliases = apoc.coll.toSet(
    [x IN coalesce(e.aliases, []) + row.aliases WHERE x <> coalesce(e.canonical_name, '')])
RETURN count(e) AS updated
"""


def load_patches(path: Path) -> tuple[list[dict], list[dict]]:
    if not path.exists():
        raise SystemExit(f"patch file not found: {path} (run --export first)")
    nodes, edges = [], []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["kind"] == "node":
                nodes.append(rec)
            elif rec["kind"] == "edge":
                edges.append(rec)
    if not edges:
        raise SystemExit(f"patch file has no edge records: {path}")
    return nodes, edges


def plan_apply(session, nodes: list[dict], edges: list[dict]) -> dict:
    """Classify what --apply would do; fail hard on unresolvable references.

    Read-only. Raises when an anchor pericope is missing, when an extracted
    node is absent (see missing_extracted_ids) or exists under another type
    label, or when an edge points at an entity neither in the graph nor
    creatable from the patch.
    """
    status = {
        r["eid"]: dict(r) for r in session.run(
            _NODE_STATUS_CYPHER, ids=[n["entity_id"] for n in nodes])
    }
    present = {eid for eid, s in status.items() if s["found"]}
    peri_status = {
        r["pid"]: r["found"] for r in session.run(
            "UNWIND $ids AS pid OPTIONAL MATCH (p:Pericope {id: pid}) "
            "RETURN pid, p.id IS NOT NULL AS found",
            ids=sorted({e["pericope_id"] for e in edges}))
    }
    missing_peri = sorted(pid for pid, ok in peri_status.items() if not ok)
    if missing_peri:
        raise SystemExit(
            f"anchor pericopes missing (import structure first): {missing_peri}")

    missing = missing_extracted_ids(nodes, present)
    if missing:
        raise SystemExit(_missing_extracted_message(missing))

    # The Entity-wide constraint would reject the MERGE anyway; failing here
    # keeps the run from stopping half-written.
    mislabelled = sorted(
        f"{n['entity_id']} (patch :{_type_label(n)}, graph {status[n['entity_id']]['labels']})"
        for n in nodes
        if n["entity_id"] in present
        and _type_label(n) not in (status[n["entity_id"]]["labels"] or []))
    if mislabelled:
        raise SystemExit(f"patch nodes exist under another type label: {mislabelled}")

    creatable = {n["entity_id"] for n in nodes if n["origin"] == "manual"}
    stuck = sorted({e["entity_id"] for e in edges} - creatable - present)
    if stuck:
        raise SystemExit(f"edge entities neither in graph nor in patch: {stuck}")

    edge_exists = {
        (r["pid"], r["eid"]): r["found"] for r in session.run(
            "UNWIND $rows AS row "
            "OPTIONAL MATCH (:Pericope {id: row.pid})-[m:MENTIONS]->"
            "(:Entity {entity_id: row.eid}) "
            "RETURN row.pid AS pid, row.eid AS eid, count(m) > 0 AS found",
            rows=[{"pid": e["pericope_id"], "eid": e["entity_id"]} for e in edges])
    }
    return {
        "nodes_to_create": [n for n in nodes if n["entity_id"] not in present],
        "nodes_existing": [n for n in nodes if n["entity_id"] in present],
        "edges_to_create": [e for e in edges
                            if not edge_exists[(e["pericope_id"], e["entity_id"])]],
        "edges_to_stamp": [e for e in edges
                           if edge_exists[(e["pericope_id"], e["entity_id"])]],
        "current": {eid: {"canonical_name": s["canonical_name"], "aliases": s["aliases"]}
                    for eid, s in status.items() if s["found"]},
    }


# ---------------------------------------------------------------------------
# PG / Qdrant preflight (read-only)
# ---------------------------------------------------------------------------

_PG_ALIASES_SQL = ("SELECT entity_id, canonical_name, aliases FROM entities "
                   "WHERE entity_id = ANY(%s)")


def _pg_aliases(conn, ids: list[str]) -> dict:
    """entity_id → aliases (as stored) for the PG rows that exist."""
    with conn.cursor() as cur:
        cur.execute(_PG_ALIASES_SQL, (ids,))
        return {eid: aliases for eid, _canonical, aliases in cur.fetchall()}


def _qdrant_aliases(client, ids: list[str]) -> dict:
    """entity_id → raw ``aliases`` payload for the Qdrant points that exist."""
    from embed_entities import COLLECTION_NAME, _entity_uuid

    points = client.retrieve(collection_name=COLLECTION_NAME,
                             ids=[_entity_uuid(eid) for eid in ids],
                             with_payload=True, with_vectors=False)
    return {(p.payload or {}).get("entity_id"): (p.payload or {}).get("aliases") for p in points}


def read_store_aliases(nodes: list[dict], *, skip_pg: bool, skip_qdrant: bool) -> dict:
    """Aliases every patch node has in PG and Qdrant now; ``None`` for a skipped store.

    Runs before any write, --dry-run included: an extracted row missing from
    PG or Qdrant used to surface only in the sync after Neo4j (and PG) had
    been written. The result also goes into the backup for rollback.
    """
    ids = [n["entity_id"] for n in nodes]
    found: dict[str, dict | None] = {"pg": None, "qdrant": None}
    if not skip_pg:
        conn = get_pg()
        try:
            found["pg"] = _pg_aliases(conn, ids)
        finally:
            conn.close()
    if not skip_qdrant:
        client = get_qdrant()
        try:
            found["qdrant"] = _qdrant_aliases(client, ids)
        finally:
            client.close()

    extracted = {n["entity_id"] for n in nodes if n["origin"] != "manual"}
    missing = {store: sorted(extracted - set(rows)) for store, rows in found.items()
               if rows is not None and extracted - set(rows)}
    if missing:
        raise SystemExit(f"extracted patch nodes missing from {missing} (Step 3 / Step 8 "
                         f"ran against another target, or the id was re-minted) — "
                         f"nothing written to any store")
    for store, rows in found.items():
        print(f"  {store}: " + ("skipped" if rows is None else
                                f"{len(rows)}/{len(ids)} patch nodes present, "
                                f"all {len(extracted)} extracted ones included"))
    return found


def _store_backup(rows: dict | None, eid: str) -> dict | None:
    if rows is None:
        return None  # store skipped: this run does not write it
    return {"existed": eid in rows, "aliases_before": rows.get(eid)}


def backup_current(session, nodes: list[dict], edges: list[dict], stores: dict) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"manual_patches_{ts}.jsonl"
    node_rows = session.run(_NODE_STATUS_CYPHER, ids=[n["entity_id"] for n in nodes])
    edge_rows = session.run(
        "UNWIND $rows AS row "
        "OPTIONAL MATCH (p:Pericope {id: row.pid})-[m:MENTIONS]->"
        "(e:Entity {entity_id: row.eid}) "
        "RETURN row.pid AS pericope_id, row.eid AS entity_id, "
        "       m IS NOT NULL AS existed, properties(m) AS props_before",
        rows=[{"pid": e["pericope_id"], "eid": e["entity_id"]} for e in edges])
    with path.open("w", encoding="utf-8") as fh:
        for r in node_rows:
            fh.write(json.dumps({"kind": "node", "entity_id": r["eid"],
                                 "existed": r["found"], "aliases_before": r["aliases"],
                                 "pg": _store_backup(stores["pg"], r["eid"]),
                                 "qdrant": _store_backup(stores["qdrant"], r["eid"])},
                                ensure_ascii=False) + "\n")
        for r in edge_rows:
            fh.write(json.dumps({"kind": "edge", **dict(r)}, ensure_ascii=False) + "\n")
    return path


def apply_nodes(session, nodes: list[dict]) -> None:
    manual_by_label: dict[str, list[dict]] = {}
    for n in nodes:
        if n["origin"] == "manual":
            manual_by_label.setdefault(_type_label(n), []).append(n)

    for label, group in sorted(manual_by_label.items()):
        rec = session.run(_MERGE_MANUAL_NODES_CYPHER.format(label=label), rows=group).single()
        print(f"  Neo4j manual-origin nodes [{label}]: {rec['merged']} merged")

    rows = [{"entity_id": n["entity_id"], "aliases": list(n["props"].get("aliases") or [])}
            for n in nodes]
    rec = session.run(_MERGE_NODE_ALIASES_CYPHER, rows=rows).single()
    if rec["updated"] != len(rows):
        raise SystemExit(
            f"alias merge matched {rec['updated']}/{len(rows)} nodes — the graph "
            f"changed since planning, or entity_id is not unique")
    print(f"  Neo4j aliases merged into {rec['updated']} nodes")


def apply_edges(session, edges: list[dict]) -> None:
    rec = session.run(
        "UNWIND $rows AS row "
        "MATCH (p:Pericope {id: row.pericope_id}) "
        "MATCH (e:Entity {entity_id: row.entity_id}) "
        "MERGE (p)-[m:MENTIONS]->(e) "
        "ON CREATE SET m += row.props, m.created_from = 'manual_patch' "
        "SET m.curated = coalesce(m.curated, true), "
        "    m.source = coalesce(m.source, 'manual_patch') "
        "RETURN count(*) AS written",
        rows=edges,
    ).single()
    skipped = len(edges) - rec["written"]
    print(f"  Neo4j edges: {rec['written']}/{len(edges)} merged+stamped"
          + (f" — {skipped} SKIPPED (missing endpoints!)" if skipped else ""))


def _pg_merge_extracted_aliases(cur, nodes: list[dict]) -> None:
    """Merge patch aliases into existing PG rows; touch no other column."""
    if not nodes:
        return
    ids = [n["entity_id"] for n in nodes]
    # Re-checked under a row lock: read_store_aliases ran before the Neo4j writes.
    cur.execute(_PG_ALIASES_SQL + " FOR UPDATE", (ids,))
    current = {eid: (canonical, aliases) for eid, canonical, aliases in cur.fetchall()}
    missing = sorted(set(ids) - set(current))
    if missing:
        raise SystemExit(f"PG entities rows missing for extracted patch nodes "
                         f"(nothing written to PG): {missing}")
    for n in nodes:
        canonical, aliases = current[n["entity_id"]]
        merged = merge_aliases(_as_alias_list(aliases), n["props"].get("aliases"), canonical)
        cur.execute(
            "UPDATE entities SET aliases = %s::jsonb WHERE entity_id = %s",
            (json.dumps(merged, ensure_ascii=False), n["entity_id"]),
        )


def sync_pg(conn, nodes: list[dict]) -> None:
    """Mirror the patch nodes into PG ``entities`` in one transaction.

    Manual rows are upserted whole: the patch is their only source. Extracted
    rows get their aliases merged and nothing else — description and
    mention_count belong to the extraction (and Step 7), and the 2026-07
    snapshot in the patch must not overwrite them through ON CONFLICT.
    """
    manual = [n for n in nodes if n["origin"] == "manual"]
    extracted = [n for n in nodes if n["origin"] != "manual"]
    try:
        with conn.cursor() as cur:
            _pg_merge_extracted_aliases(cur, extracted)
            for n in manual:
                p = n["props"]
                cur.execute(
                    """
                    INSERT INTO entities (entity_id, type, canonical_name, aliases,
                                          description, extraction_method, mention_count)
                    VALUES (%s, %s, %s, %s::jsonb, %s, 'curated', %s)
                    ON CONFLICT (entity_id) DO UPDATE
                        SET canonical_name = EXCLUDED.canonical_name,
                            aliases = EXCLUDED.aliases,
                            description = EXCLUDED.description,
                            mention_count = EXCLUDED.mention_count
                    """,
                    (n["entity_id"],
                     _type_label(n),
                     p.get("canonical_name"),
                     json.dumps(p.get("aliases") or [], ensure_ascii=False),
                     p.get("description"),
                     p.get("mention_count", 0)),
                )
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    print(f"  PG: {len(manual)} manual-origin entities upserted, "
          f"{len(extracted)} extracted entities alias-merged")


def sync_qdrant_aliases(client, nodes: list[dict]) -> None:
    """Merge patch aliases into the Qdrant payload of extracted nodes.

    Payload ``aliases`` only — no re-embed, so the stored description and
    vector stay those of Step 8. Manual nodes are re-embedded separately.
    """
    from embed_entities import COLLECTION_NAME, _entity_uuid

    extracted = [n for n in nodes if n["origin"] != "manual"]
    if not extracted:
        return
    points = client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[_entity_uuid(n["entity_id"]) for n in extracted],
        with_payload=True, with_vectors=False)
    by_id = {(p.payload or {}).get("entity_id"): p for p in points}
    missing = sorted(n["entity_id"] for n in extracted if n["entity_id"] not in by_id)
    if missing:
        raise SystemExit(f"Qdrant points missing for extracted patch nodes "
                         f"(nothing written to Qdrant): {missing}")
    for n in extracted:
        point = by_id[n["entity_id"]]
        merged = merge_aliases(_as_alias_list(point.payload.get("aliases")),
                               n["props"].get("aliases"),
                               point.payload.get("canonical_name"))
        client.set_payload(collection_name=COLLECTION_NAME,
                           payload={"aliases": merged}, points=[point.id], wait=True)
    print(f"  Qdrant: aliases merged into {len(extracted)} extracted entity payloads")


def smoke_test(session) -> None:
    rec = session.run(
        f"MATCH (p)-[r:MENTIONS]->(:Entity) WHERE {_NO_PROVENANCE_WHERE} "
        f"RETURN count(r) AS left").single()
    print(f"\nSmoke test: unmarked manual edges remaining = {rec['left']} "
          f"({'✓ all stamped' if rec['left'] == 0 else '✗ expected 0'})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_dry_run(plan: dict, nodes: list[dict]) -> None:
    for n in plan["nodes_to_create"]:
        print(f"  [node+] {n['entity_id']} ({n['origin']})")
    projected = overlay_nodes(plan["current"], nodes)
    for n in nodes:
        eid = n["entity_id"]
        before = (plan["current"].get(eid) or {}).get("aliases") or []
        gained = [a for a in projected[eid]["aliases"] if a not in before]
        if gained:
            print(f"  [aliases+] {eid}: {gained}")
    by_ent: dict[str, int] = {}
    for e in plan["edges_to_create"]:
        by_ent[e["entity_name"]] = by_ent.get(e["entity_name"], 0) + 1
    for name, cnt in sorted(by_ent.items(), key=lambda kv: -kv[1]):
        print(f"  [edge+] {name}: {cnt}")
    print("Dry run — nothing written.")


def run_apply(driver, patch_file: Path, args) -> None:
    nodes, edges = load_patches(patch_file)
    with driver.session() as session:
        print(f"Planning apply of {len(nodes)} nodes / {len(edges)} edges "
              f"from {patch_file.name} ...")
        plan = plan_apply(session, nodes, edges)
        print(f"  nodes: {len(plan['nodes_to_create'])} to create, "
              f"{len(plan['nodes_existing'])} already present (aliases merged into all)")
        print(f"  edges: {len(plan['edges_to_create'])} to create, "
              f"{len(plan['edges_to_stamp'])} to stamp provenance on")
        stores = read_store_aliases(nodes, skip_pg=args.skip_pg, skip_qdrant=args.skip_qdrant)

        if args.dry_run:
            _print_dry_run(plan, nodes)
            return

        backup = backup_current(session, nodes, edges, stores)
        print(f"  Backup written: {backup}")
        apply_nodes(session, nodes)
        apply_edges(session, edges)

    if args.skip_pg:
        print("  PG sync skipped")
    else:
        conn = get_pg()
        try:
            sync_pg(conn, nodes)
        finally:
            conn.close()

    if args.skip_qdrant:
        print("  Qdrant sync skipped")
    else:
        manual_ids = [n["entity_id"] for n in nodes if n["origin"] == "manual"]
        if manual_ids:
            reembed_qdrant(manual_ids)
        client = get_qdrant()
        try:
            sync_qdrant_aliases(client, nodes)
        finally:
            client.close()

    with driver.session() as session:
        smoke_test(session)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--export", action="store_true",
                      help="snapshot unmarked manual edges/nodes from live graph")
    mode.add_argument("--apply", action="store_true",
                      help="replay the snapshot (MERGE + stamp provenance + merge aliases)")
    parser.add_argument("--patch-file", type=Path, default=DEFAULT_PATCH_FILE)
    parser.add_argument("--dry-run", action="store_true",
                        help="report only; write neither the patch file nor any store")
    parser.add_argument("--skip-pg", action="store_true")
    parser.add_argument("--skip-qdrant", action="store_true",
                        help="skip Qdrant (manual-node re-embed and extracted-node alias payloads)")
    args = parser.parse_args()

    # Every store in every mode, dry runs and --skip-* included: a staging
    # shell that exported only some of its settings is the mistake this guard
    # catches, and a dry run planned against production would mislead too.
    kg_target.assert_target("neo4j", "postgres", "qdrant")
    driver = get_neo4j()
    try:
        if args.export:
            with driver.session() as session:
                export_patches(session, args.patch_file, dry_run=args.dry_run)
        else:
            run_apply(driver, args.patch_file, args)
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

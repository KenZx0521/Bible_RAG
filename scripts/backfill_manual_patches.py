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
2. ``--apply`` — replay the snapshot: MERGE missing nodes/edges (rebuild
   scenario) and stamp provenance (``curated=true, source='manual_patch'``)
   onto matched unmarked edges (live scenario). Existing property values are
   never overwritten (coalesce only). Three stores stay in sync for manual
   nodes: Neo4j, PostgreSQL entities, Qdrant bible_entities (re-embed).

Rollback (only objects *created* by --apply carry ``created_from``):
  * edges:  MATCH ()-[m:MENTIONS {created_from:'manual_patch'}]->() DELETE m
  * nodes:  MATCH (e:Entity {created_from:'manual_patch'}) DETACH DELETE e
  * stamps: restore from output/backups/manual_patches_<ts>.jsonl

Usage:
    uv run --project scripts python scripts/backfill_manual_patches.py --export
    uv run --project scripts python scripts/backfill_manual_patches.py --apply --dry-run
    uv run --project scripts python scripts/backfill_manual_patches.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))

from backfill_head_events import get_neo4j, get_pg, reembed_qdrant  # noqa: E402

DEFAULT_PATCH_FILE = _PROJECT_ROOT / "config" / "curated" / "manual_graph_patches.jsonl"
ENTITIES_JSONL = _PROJECT_ROOT / "output" / "entities.jsonl"

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


def export_patches(session, out_path: Path) -> tuple[int, int]:
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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manual = [r for r in records if r["kind"] == "node" and r["origin"] == "manual"]
    print(f"  Exported {len(edges)} edges / {len(nodes)} nodes → {out_path}")
    print(f"  Manual-origin nodes (absent from entities.jsonl): "
          f"{[n['entity_id'] for n in manual] or 'none'}")
    return len(nodes), len(edges)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

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
    """Classify what --apply would do; fail hard on unresolvable references."""
    node_status = {
        r["eid"]: r["found"] for r in session.run(
            "UNWIND $ids AS eid OPTIONAL MATCH (e:Entity {entity_id: eid}) "
            "RETURN eid, e.entity_id IS NOT NULL AS found",
            ids=[n["entity_id"] for n in nodes])
    }
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

    creatable = {n["entity_id"] for n in nodes}
    stuck = sorted({e["entity_id"] for e in edges}
                   - creatable - {i for i, ok in node_status.items() if ok})
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
        "nodes_to_create": [n for n in nodes if not node_status[n["entity_id"]]],
        "nodes_existing": [n for n in nodes if node_status[n["entity_id"]]],
        "edges_to_create": [e for e in edges
                            if not edge_exists[(e["pericope_id"], e["entity_id"])]],
        "edges_to_stamp": [e for e in edges
                           if edge_exists[(e["pericope_id"], e["entity_id"])]],
    }


def backup_current(session, edges: list[dict]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = _PROJECT_ROOT / "output" / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"manual_patches_{ts}.jsonl"
    rows = session.run(
        "UNWIND $rows AS row "
        "OPTIONAL MATCH (p:Pericope {id: row.pid})-[m:MENTIONS]->"
        "(e:Entity {entity_id: row.eid}) "
        "RETURN row.pid AS pericope_id, row.eid AS entity_id, "
        "       m IS NOT NULL AS existed, properties(m) AS props_before",
        rows=[{"pid": e["pericope_id"], "eid": e["entity_id"]} for e in edges])
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    return path


def apply_nodes(session, nodes: list[dict]) -> None:
    by_label: dict[str, list[dict]] = {}
    for n in nodes:
        label = next(l for l in n["labels"] if l != "Entity")
        by_label.setdefault(label, []).append(n)

    for label, group in sorted(by_label.items()):
        rec = session.run(
            f"UNWIND $rows AS row "
            f"MERGE (e:Entity:{label} {{entity_id: row.entity_id}}) "
            f"ON CREATE SET e += row.props, e.created_from = 'manual_patch' "
            f"WITH e, row WHERE row.origin = 'manual' "
            f"SET e.source = coalesce(e.source, 'manual_patch'), "
            f"    e.extraction_method = coalesce(e.extraction_method, 'curated') "
            f"RETURN count(e) AS stamped",
            rows=group,
        ).single()
        print(f"  Neo4j nodes [{label}]: {len(group)} merged "
              f"({rec['stamped']} manual-origin stamped)")


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


def sync_pg(conn, manual_nodes: list[dict]) -> None:
    with conn.cursor() as cur:
        for n in manual_nodes:
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
                 next(l for l in n["labels"] if l != "Entity"),
                 p.get("canonical_name"),
                 json.dumps(p.get("aliases") or [], ensure_ascii=False),
                 p.get("description"),
                 p.get("mention_count", 0)),
            )
    conn.commit()
    print(f"  PG: {len(manual_nodes)} manual-origin entities upserted")


def smoke_test(session) -> None:
    rec = session.run(
        f"MATCH (p)-[r:MENTIONS]->(:Entity) WHERE {_NO_PROVENANCE_WHERE} "
        f"RETURN count(r) AS left").single()
    print(f"\nSmoke test: unmarked manual edges remaining = {rec['left']} "
          f"({'✓ all stamped' if rec['left'] == 0 else '✗ expected 0'})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_apply(driver, patch_file: Path, args) -> None:
    nodes, edges = load_patches(patch_file)
    with driver.session() as session:
        print(f"Planning apply of {len(nodes)} nodes / {len(edges)} edges "
              f"from {patch_file.name} ...")
        plan = plan_apply(session, nodes, edges)
        print(f"  nodes: {len(plan['nodes_to_create'])} to create, "
              f"{len(plan['nodes_existing'])} already present")
        print(f"  edges: {len(plan['edges_to_create'])} to create, "
              f"{len(plan['edges_to_stamp'])} to stamp provenance on")

        if args.dry_run:
            for n in plan["nodes_to_create"]:
                print(f"  [node+] {n['entity_id']} ({n['origin']})")
            by_ent: dict[str, int] = {}
            for e in plan["edges_to_create"]:
                by_ent[e["entity_name"]] = by_ent.get(e["entity_name"], 0) + 1
            for name, cnt in sorted(by_ent.items(), key=lambda kv: -kv[1]):
                print(f"  [edge+] {name}: {cnt}")
            print("Dry run — nothing written.")
            return

        backup = backup_current(session, edges)
        print(f"  Backup written: {backup}")
        apply_nodes(session, nodes)
        apply_edges(session, edges)

    manual_nodes = [n for n in nodes if n["origin"] == "manual"]
    if args.skip_pg or not manual_nodes:
        print("  PG sync skipped" if args.skip_pg else "  PG: no manual nodes to sync")
    else:
        conn = get_pg()
        try:
            sync_pg(conn, manual_nodes)
        finally:
            conn.close()

    if args.skip_qdrant or not manual_nodes:
        print("  Qdrant re-embed skipped" if args.skip_qdrant
              else "  Qdrant: no manual nodes to re-embed")
    else:
        reembed_qdrant([n["entity_id"] for n in manual_nodes])

    with driver.session() as session:
        smoke_test(session)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--export", action="store_true",
                      help="snapshot unmarked manual edges/nodes from live graph")
    mode.add_argument("--apply", action="store_true",
                      help="replay the snapshot (MERGE + stamp provenance)")
    parser.add_argument("--patch-file", type=Path, default=DEFAULT_PATCH_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-pg", action="store_true")
    parser.add_argument("--skip-qdrant", action="store_true",
                        help="skip the BGE re-embed step for manual nodes")
    args = parser.parse_args()

    driver = get_neo4j()
    try:
        if args.export:
            with driver.session() as session:
                export_patches(session, args.patch_file)
        else:
            run_apply(driver, args.patch_file, args)
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

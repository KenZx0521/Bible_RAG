#!/usr/bin/env python3
"""Cleanup noise entities in the knowledge graph (P0 repair).

Actions (all back up affected data to output/backups/ before writing):

  dan             Remove MENTIONS edges to place:dan whose source text uses
                  「但」 as a conjunction (但我/但你...) or as a substring of
                  another name (撒但/拿但業/底但/亞比但/米但). Keeps only
                  sources where 「但」 is genuinely the place name (從但到
                  別是巴, 金牛犢安在但, 支派地業列表...).

  generic-events  DETACH DELETE Event nodes whose canonical_name is a generic
                  noun (日子/長子/結局...) — artifacts of pericope_miner
                  defaulting every unmatched title to EVENT. Also removes the
                  corresponding Qdrant points and Postgres rows.

  yehehua         Fix group:yehehua (耶和華, degree ~2.5k) mis-typed as Group:
                  relabel it in Neo4j to the label its override in
                  config/curated/entity_overrides.yaml gives (Person, D9),
                  sync type in Postgres + Qdrant. The file is read and
                  validated before any store is touched.

Usage:
    uv run python cleanup_noise_entities.py [--dry-run] [--actions dan,generic-events,yehehua]

Under KG_TARGET=staging (scripts/tools/staging.env) the sync is strict:
  - before Neo4j is touched, PostgreSQL and Qdrant must answer and hold the
    tables (entities, entity_mentions) and the entity collection it writes;
  - a failed connection or write stops the run instead of warning;
  - PostgreSQL and Qdrant are synced to target ids, not only to what Neo4j still
    holds: generic-events also deletes the generic Event ids PG or Qdrant still
    have, yehehua re-syncs its id even when Neo4j is already relabeled. Both are
    no-ops where already done, so a rerun finishes a sync that failed midway.
Production keeps warning, skipping the sync and deciding from Neo4j as before.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

import kg_target
from check_identity import TYPE_LABELS
# Shared with the offline Step 6.05, which must see the graph as 10.2 leaves it.
# Also re-exported: test_registry_rebuild_sim.py and the archived docs/records
# simulators import these names from this module.
from entity_extraction.geo_rules import compute_dan_keep_sources
from entity_extraction.geo_rules import is_geo_context as _is_geo_context  # noqa: F401
from entity_extraction.stoplists import GENERIC_EVENT_STOPLIST
# group:yehehua's type (D9); 6.05 types entities.jsonl through the same file.
from entity_extraction.entity_overrides import OVERRIDES_PATH, load_overrides

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BACKUP_DIR = ROOT / "output" / "backups"

# Actions that also sync PostgreSQL and the Qdrant entity collection, and the
# PostgreSQL tables they write.
SYNCING_ACTIONS = {"generic-events", "yehehua"}
SYNC_TABLES = ("entities", "entity_mentions")

def get_neo4j():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def _sync_failed(store: str, error: Exception, strict: bool) -> None:
    """Production keeps the historical warn-and-skip; staging must not.

    A skipped sync leaves the three stores disagreeing, and on staging nobody
    redoes it by hand: the rebuild is judged by those stores.
    """
    if strict:
        raise SystemExit(
            f"  ✗ {store} sync failed under KG_TARGET=staging: {error}\n"
            "    Fix it and rerun the same --actions: staging syncs PostgreSQL and "
            "Qdrant to the target ids even where Neo4j is already done."
        ) from error


def _entity_collection() -> str:
    return os.getenv("QDRANT_ENTITY_COLLECTION", "bible_entities")


def get_qdrant(strict: bool = False):
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            # QDRANT_PORT, when set, wins over QDRANT_HTTP_PORT (the name .env and compose use).
            port=int(os.getenv("QDRANT_PORT") or os.getenv("QDRANT_HTTP_PORT", "6333")),
        )
        client.get_collections()
        return client
    except Exception as e:  # noqa: BLE001
        _sync_failed("Qdrant", e, strict)
        print(f"  ⚠ Qdrant unavailable ({e}) — skip Qdrant sync, redo manually later")
        return None


def get_postgres(strict: bool = False):
    try:
        import psycopg2
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "bible_rag"),
            # Fallbacks match docker-compose.yml like every other script; the old
            # postgres/'' failed to connect without .env and the except below then
            # skipped the PG sync silently.
            user=os.getenv("POSTGRES_USER", "bible"),
            password=os.getenv("POSTGRES_PASSWORD", "bible_password"),
        )
    except Exception as e:  # noqa: BLE001
        _sync_failed("Postgres", e, strict)
        print(f"  ⚠ Postgres unavailable ({e}) — skip PG sync, redo manually later")
        return None


def check_sync_stores() -> None:
    """Staging: prove PG and Qdrant can take the sync before Neo4j is touched.

    The actions write Neo4j first and sync afterwards, so failing only at sync
    time would leave Neo4j cleaned and the other two stores not. Answering is
    not enough: a missing collection or table fails the sync just the same.
    """
    collection = _entity_collection()
    qdrant = get_qdrant(strict=True)
    try:
        has_collection = qdrant.collection_exists(collection)
    finally:
        qdrant.close()
    if not has_collection:
        raise SystemExit(f"  ✗ Qdrant has no collection {collection} to sync (Step 8a builds it)")

    pg = get_postgres(strict=True)
    try:
        with pg.cursor() as cur:
            missing = []
            for table in SYNC_TABLES:
                cur.execute("SELECT to_regclass(%s)", (table,))
                if cur.fetchone()[0] is None:
                    missing.append(table)
    finally:
        pg.close()
    if missing:
        raise SystemExit(f"  ✗ Postgres {os.getenv('POSTGRES_DB')} has no table "
                         f"{', '.join(missing)} to sync (scripts/db/schema.sql creates them)")


def entity_uuid(entity_id: str) -> str:
    """Mirror embed_entities.py point-id derivation."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"entity:{entity_id}"))


def backup_path(name: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return BACKUP_DIR / f"{name}_{stamp}.jsonl"


# ---------------------------------------------------------------- dan ----

def action_dan(driver, dry_run: bool) -> None:
    print("\n[dan] Filtering non-geographic MENTIONS on place:dan")
    mentions_path = ROOT / "output" / "entity_mentions.jsonl"
    keep = compute_dan_keep_sources(mentions_path)
    print(f"  Geo-verified sources to keep: {len(keep)}")

    with driver.session() as session:
        rows = session.run(
            "MATCH (s)-[r:MENTIONS]->(e:Entity {entity_id: 'place:dan'}) "
            "RETURN s.id AS source_id, labels(s) AS source_labels, properties(r) AS props"
        ).data()
    to_delete = [r for r in rows if r["source_id"] not in keep]
    print(f"  Current edges: {len(rows)} | keep: {len(rows) - len(to_delete)} | delete: {len(to_delete)}")

    if dry_run:
        return
    path = backup_path("dan_mentions")
    with path.open("w", encoding="utf-8") as f:
        for r in to_delete:
            f.write(json.dumps({"entity_id": "place:dan", **r}, ensure_ascii=False, default=str) + "\n")
    print(f"  Backup: {path}")

    with driver.session() as session:
        record = session.run(
            "MATCH (s)-[r:MENTIONS]->(e:Entity {entity_id: 'place:dan'}) "
            "WHERE NOT s.id IN $keep DELETE r RETURN count(*) AS deleted",
            keep=list(keep),
        ).single()
        deleted = record["deleted"] if record else 0
        session.run(
            "MATCH (e:Entity {entity_id: 'place:dan'}) "
            "SET e.noise_filtered = true, e.mention_count = $kept",
            kept=len(rows) - len(to_delete),
        )
    print(f"  ✓ Deleted {deleted} noise edges; mention_count reset to {len(rows) - len(to_delete)}")


# ------------------------------------------------------- generic events ----

def _generic_event_ids_in_sync_stores() -> set[str]:
    """Staging: generic Event ids PostgreSQL or Qdrant still hold.

    Neo4j is cleaned first, so after a sync that failed midway a rerun finds
    nothing there; these are the ids that run left behind.
    """
    from qdrant_client import models

    collection, ids, offset = _entity_collection(), set(), None
    generic_events = models.Filter(must=[
        models.FieldCondition(key="type", match=models.MatchValue(value="Event")),
        models.FieldCondition(key="canonical_name",
                              match=models.MatchAny(any=GENERIC_EVENT_STOPLIST)),
    ])
    qdrant = get_qdrant(strict=True)
    try:
        while True:
            points, offset = qdrant.scroll(collection_name=collection, scroll_filter=generic_events,
                                           limit=256, offset=offset, with_payload=["entity_id"])
            ids |= {p.payload["entity_id"] for p in points}
            if offset is None:
                break
    finally:
        qdrant.close()

    pg = get_postgres(strict=True)
    try:
        with pg.cursor() as cur:
            cur.execute("SELECT entity_id FROM entities "
                        "WHERE type = 'Event' AND canonical_name = ANY(%s)",
                        (GENERIC_EVENT_STOPLIST,))
            ids |= {row[0] for row in cur.fetchall()}
    finally:
        pg.close()
    return ids


def action_generic_events(driver, dry_run: bool, strict: bool = False) -> None:
    print("\n[generic-events] Deleting generic-noun Event nodes")
    with driver.session() as session:
        nodes = session.run(
            "MATCH (e:Event) WHERE e.canonical_name IN $stop "
            "OPTIONAL MATCH (e)-[r]-(other) "
            "WITH e, collect({rel_type: type(r), rel_props: properties(r), "
            "     other_id: coalesce(other.entity_id, other.id), outgoing: startNode(r) = e}) AS rels "
            "RETURN e.entity_id AS entity_id, e.canonical_name AS name, "
            "       e.mention_count AS mc, properties(e) AS props, rels",
            stop=GENERIC_EVENT_STOPLIST,
        ).data()
    ids = [n["entity_id"] for n in nodes]
    # Staging syncs the target ids, not just Neo4j's: an interrupted run has
    # already deleted its nodes there. A dry run stays off PG and Qdrant.
    leftover = sorted(_generic_event_ids_in_sync_stores() - set(ids)) if strict and not dry_run else []
    if not nodes and not leftover:
        print("  Nothing matched")
        return
    for n in nodes:
        print(f"  {n['entity_id']} ({n['name']}, mc={n['mc']}, edges={len([r for r in n['rels'] if r['rel_type']])})")
    print(f"  Total: {len(nodes)} Event nodes")
    if leftover:
        print(f"  Gone from Neo4j, still in PostgreSQL/Qdrant: {', '.join(leftover)}")

    if dry_run:
        return
    if nodes:
        path = backup_path("generic_events")
        with path.open("w", encoding="utf-8") as f:
            for n in nodes:
                f.write(json.dumps(n, ensure_ascii=False, default=str) + "\n")
        print(f"  Backup: {path}")

        with driver.session() as session:
            record = session.run(
                "MATCH (e:Event) WHERE e.entity_id IN $ids DETACH DELETE e RETURN count(*) AS deleted",
                ids=ids,
            ).single()
        print(f"  ✓ Neo4j: deleted {record['deleted'] if record else 0} nodes (with all edges)")
    _sync_generic_event_deletes(ids + leftover, strict)


def _sync_generic_event_deletes(ids: list[str], strict: bool) -> None:
    """Delete ``ids`` from Qdrant, then PostgreSQL; absent ids are no-ops."""
    qdrant = get_qdrant(strict)
    if qdrant:
        collection = _entity_collection()
        try:
            qdrant.delete(collection_name=collection,
                          points_selector=[entity_uuid(i) for i in ids], wait=True)
            print(f"  ✓ Qdrant: deleted {len(ids)} points from {collection}")
        except Exception as e:  # noqa: BLE001
            _sync_failed("Qdrant", e, strict)
            print(f"  ⚠ Qdrant delete failed: {e}")
        finally:
            qdrant.close()

    pg = get_postgres(strict)
    if pg:
        try:
            with pg.cursor() as cur:
                cur.execute("DELETE FROM entity_mentions WHERE entity_id = ANY(%s)", (ids,))
                mentions_deleted = cur.rowcount
                cur.execute("DELETE FROM entities WHERE entity_id = ANY(%s)", (ids,))
                entities_deleted = cur.rowcount
            pg.commit()
            print(f"  ✓ Postgres: deleted {entities_deleted} entities, {mentions_deleted} mention rows")
        except Exception as e:  # noqa: BLE001
            pg.rollback()
            _sync_failed("Postgres", e, strict)
            print(f"  ⚠ Postgres delete failed: {e}")
        finally:
            pg.close()


# --------------------------------------------------------------- yehehua ----

YEHEHUA_ID = "group:yehehua"


def yehehua_label(path: Path) -> str | None:
    """group:yehehua's label in the overrides file (D9); None when it has none.

    Read before any store is touched: a malformed file stops the run here.
    """
    try:
        override = load_overrides(path).get(YEHEHUA_ID)
    except ValueError as e:
        raise SystemExit(f"  ✗ {e}") from e
    return override["label"] if override else None


def action_yehehua(driver, dry_run: bool, label: str | None, strict: bool = False) -> None:
    """Give group:yehehua the type ``label`` in Neo4j, then sync PG and Qdrant."""
    if label is None:
        print(f"\n[yehehua] {YEHEHUA_ID} has no override in {OVERRIDES_PATH.name} — skip")
        return
    if label not in TYPE_LABELS:  # interpolated into the Cypher and SQL below
        raise ValueError(f"{YEHEHUA_ID}: label {label!r} is not one of {list(TYPE_LABELS)}")
    print(f"\n[yehehua] Relabeling {YEHEHUA_ID} → {label} ({OVERRIDES_PATH.name})")
    with driver.session() as session:
        row = session.run(
            f"MATCH (e:Entity {{entity_id: '{YEHEHUA_ID}'}}) RETURN labels(e) AS labels"
        ).single()
    if not row:
        print(f"  {YEHEHUA_ID} not found — skip")
        return
    print(f"  Current labels: {row['labels']}")
    stale = [t for t in row["labels"] if t in TYPE_LABELS and t != label]
    relabeled = label in row["labels"] and not stale
    if relabeled and not strict:
        print("  Already relabeled — skip")
        return
    if relabeled:
        # Staging: an interrupted run may have relabeled Neo4j only. Re-syncing
        # the one target id is a no-op where it already landed.
        print("  Already relabeled in Neo4j — re-syncing PostgreSQL and Qdrant")
    if dry_run:
        return

    if not relabeled:
        remove = f" REMOVE e:{':'.join(stale)}" if stale else ""
        with driver.session() as session:
            session.run(f"MATCH (e:Entity {{entity_id: '{YEHEHUA_ID}'}}){remove} SET e:{label}")
        print(f"  ✓ Neo4j: labels now [{label}, Entity] (entity_id unchanged)")
    _sync_yehehua_type(label, strict)


def _sync_yehehua_type(label: str, strict: bool) -> None:
    """Set group:yehehua's type to ``label`` in PostgreSQL and Qdrant."""
    pg = get_postgres(strict)
    if pg:
        try:
            with pg.cursor() as cur:
                cur.execute(f"UPDATE entities SET type = '{label}' WHERE entity_id = '{YEHEHUA_ID}'")
                updated = cur.rowcount
            pg.commit()
            print(f"  ✓ Postgres: {updated} row updated (type={label})")
        except Exception as e:  # noqa: BLE001
            pg.rollback()
            _sync_failed("Postgres", e, strict)
            print(f"  ⚠ Postgres update failed: {e}")
        finally:
            pg.close()

    qdrant = get_qdrant(strict)
    if qdrant:
        collection = _entity_collection()
        points = [entity_uuid(YEHEHUA_ID)]
        if strict:
            # An id list fails on a point the collection lacks (404); a filter
            # selector makes that a no-op, as the target-id sync needs.
            from qdrant_client import models
            points = models.Filter(must=[models.HasIdCondition(has_id=points)])
        try:
            qdrant.set_payload(collection_name=collection, payload={"type": label},
                               points=points, wait=True)
            print(f"  ✓ Qdrant: payload.type={label} in {collection}")
        except Exception as e:  # noqa: BLE001
            _sync_failed("Qdrant", e, strict)
            print(f"  ⚠ Qdrant payload update failed: {e}")
        finally:
            qdrant.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--actions", type=str, default="dan,generic-events,yehehua")
    args = parser.parse_args()
    actions = {a.strip() for a in args.actions.split(",") if a.strip()}
    syncing = bool(actions & SYNCING_ACTIONS)
    yehehua = yehehua_label(OVERRIDES_PATH) if "yehehua" in actions else None

    stores = ("neo4j", "postgres", "qdrant") if syncing else ("neo4j",)
    strict = kg_target.assert_target(*stores) == "staging"
    if strict and syncing and not args.dry_run:
        check_sync_stores()

    driver = get_neo4j()
    try:
        if "dan" in actions:
            action_dan(driver, args.dry_run)
        if "generic-events" in actions:
            action_generic_events(driver, args.dry_run, strict)
        if "yehehua" in actions:
            action_yehehua(driver, args.dry_run, yehehua, strict)
    finally:
        driver.close()
    print("\nDone" + (" (dry-run, nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
                  relabel to Person in Neo4j, sync type in Postgres + Qdrant.

Usage:
    uv run python cleanup_noise_entities.py [--dry-run] [--actions dan,generic-events,yehehua]
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

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BACKUP_DIR = ROOT / "output" / "backups"

# --- place:dan geo classification (same rules validated on live data) ---
PUNCT = set("，。；：、「」？！ \n\t^$（）－")
GEO_PREV = {"從", "到", "往", "至", "在"}
NAMING_PREV = {"叫", "為"}
LIST_OK_PREV = {"和", "與", "同"} | PUNCT

# Generic-noun Event nodes: pericope-title artifacts, not biblical events.
# Kept: 饑荒/瘟疫/洪水/地震/節期/洗禮/登基... (real event semantics).
GENERIC_EVENT_STOPLIST = [
    "日子", "長子", "結局", "問候", "吩咐", "工程", "大會", "建築",
    "大事", "醜事", "使用", "艱難", "爭論", "坐席", "生日", "探子",
    "兒子", "時候", "事情", "話", "早晨", "晚上", "夜間", "明天",
]


def get_neo4j():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4j_password")),
    )


def get_qdrant():
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_HTTP_PORT", "6333")),
        )
        client.get_collections()
        return client
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Qdrant unavailable ({e}) — skip Qdrant sync, redo manually later")
        return None


def get_postgres():
    try:
        import psycopg2
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB", "bible_rag"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ Postgres unavailable ({e}) — skip PG sync, redo manually later")
        return None


def entity_uuid(entity_id: str) -> str:
    """Mirror embed_entities.py point-id derivation."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"entity:{entity_id}"))


def backup_path(name: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return BACKUP_DIR / f"{name}_{stamp}.jsonl"


# ---------------------------------------------------------------- dan ----

def _is_geo_context(ctx: str) -> bool:
    if "別是巴" in ctx:
        return True
    i = ctx.find("但")
    while i >= 0:
        p = ctx[i - 1] if i > 0 else "^"
        n = ctx[i + 1] if i + 1 < len(ctx) else "$"
        if p in GEO_PREV and n != "以":
            return True
        if p in NAMING_PREV and (n in PUNCT or n == "$"):
            return True
        if p in LIST_OK_PREV and n == "、":
            return True
        if p == "、" and (n in PUNCT or n == "$"):
            return True
        i = ctx.find("但", i + 1)
    return False


def compute_dan_keep_sources(mentions_path: Path) -> set[str]:
    keep: set[str] = set()
    with mentions_path.open("r", encoding="utf-8") as f:
        for line in f:
            if '"place:dan"' not in line:
                continue
            rec = json.loads(line)
            if rec.get("entity_id") != "place:dan":
                continue
            if _is_geo_context(rec.get("context", "")):
                keep.add(rec["source_id"].split(":v:")[0])
    return keep


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

def action_generic_events(driver, dry_run: bool) -> None:
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
    if not nodes:
        print("  Nothing matched")
        return
    for n in nodes:
        print(f"  {n['entity_id']} ({n['name']}, mc={n['mc']}, edges={len([r for r in n['rels'] if r['rel_type']])})")
    print(f"  Total: {len(nodes)} Event nodes")

    if dry_run:
        return
    path = backup_path("generic_events")
    with path.open("w", encoding="utf-8") as f:
        for n in nodes:
            f.write(json.dumps(n, ensure_ascii=False, default=str) + "\n")
    print(f"  Backup: {path}")

    ids = [n["entity_id"] for n in nodes]
    with driver.session() as session:
        record = session.run(
            "MATCH (e:Event) WHERE e.entity_id IN $ids DETACH DELETE e RETURN count(*) AS deleted",
            ids=ids,
        ).single()
    print(f"  ✓ Neo4j: deleted {record['deleted'] if record else 0} nodes (with all edges)")

    qdrant = get_qdrant()
    if qdrant:
        collection = os.getenv("QDRANT_ENTITY_COLLECTION", "bible_entities")
        try:
            qdrant.delete(collection_name=collection,
                          points_selector=[entity_uuid(i) for i in ids], wait=True)
            print(f"  ✓ Qdrant: deleted {len(ids)} points from {collection}")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Qdrant delete failed: {e}")
        finally:
            qdrant.close()

    pg = get_postgres()
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
            print(f"  ⚠ Postgres delete failed: {e}")
        finally:
            pg.close()


# --------------------------------------------------------------- yehehua ----

def action_yehehua(driver, dry_run: bool) -> None:
    print("\n[yehehua] Relabeling group:yehehua Group → Person")
    with driver.session() as session:
        row = session.run(
            "MATCH (e:Entity {entity_id: 'group:yehehua'}) RETURN labels(e) AS labels"
        ).single()
    if not row:
        print("  group:yehehua not found — skip")
        return
    print(f"  Current labels: {row['labels']}")
    if "Person" in row["labels"] and "Group" not in row["labels"]:
        print("  Already relabeled — skip")
        return
    if dry_run:
        return

    with driver.session() as session:
        session.run(
            "MATCH (e:Entity {entity_id: 'group:yehehua'}) REMOVE e:Group SET e:Person"
        )
    print("  ✓ Neo4j: labels now [Person, Entity] (entity_id unchanged)")

    pg = get_postgres()
    if pg:
        try:
            with pg.cursor() as cur:
                cur.execute("UPDATE entities SET type = 'Person' WHERE entity_id = 'group:yehehua'")
                updated = cur.rowcount
            pg.commit()
            print(f"  ✓ Postgres: {updated} row updated (type=Person)")
        except Exception as e:  # noqa: BLE001
            pg.rollback()
            print(f"  ⚠ Postgres update failed: {e}")
        finally:
            pg.close()

    qdrant = get_qdrant()
    if qdrant:
        collection = os.getenv("QDRANT_ENTITY_COLLECTION", "bible_entities")
        try:
            qdrant.set_payload(collection_name=collection, payload={"type": "Person"},
                               points=[entity_uuid("group:yehehua")], wait=True)
            print(f"  ✓ Qdrant: payload.type=Person in {collection}")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Qdrant payload update failed: {e}")
        finally:
            qdrant.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--actions", type=str, default="dan,generic-events,yehehua")
    args = parser.parse_args()
    actions = {a.strip() for a in args.actions.split(",") if a.strip()}

    driver = get_neo4j()
    try:
        if "dan" in actions:
            action_dan(driver, args.dry_run)
        if "generic-events" in actions:
            action_generic_events(driver, args.dry_run)
        if "yehehua" in actions:
            action_yehehua(driver, args.dry_run)
    finally:
        driver.close()
    print("\nDone" + (" (dry-run, nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

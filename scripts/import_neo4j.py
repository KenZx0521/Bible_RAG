#!/usr/bin/env python3
"""
Import data into Neo4j graph database.

Usage:
    python scripts/import_neo4j.py [--output-dir OUTPUT_DIR] [--batch-size BATCH_SIZE]
"""

import json
import os
import argparse
from pathlib import Path
from typing import Generator

from neo4j import GraphDatabase
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_neo4j_driver():
    """Create and return a Neo4j driver."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j_password")
    return GraphDatabase.driver(uri, auth=(user, password))


def read_jsonl(filepath: Path) -> Generator[dict, None, None]:
    """Read JSONL file and yield records."""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def clear_database(driver):
    """Clear all nodes and relationships."""
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("  ✓ Database cleared")


def create_constraints(driver):
    """Create uniqueness constraints and indexes."""
    constraints = [
        # Bible hierarchy
        ("Book", "id"),
        ("Chapter", "id"),
        ("Pericope", "id"),
        ("Chunk", "id"),
        # Entity types
        ("Person", "entity_id"),
        ("Place", "entity_id"),
        ("Group", "entity_id"),
        ("Event", "entity_id"),
        ("Object", "entity_id"),
        ("Theme", "entity_id"),
    ]
    
    with driver.session() as session:
        for label, prop in constraints:
            try:
                session.run(
                    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
                )
            except Exception:
                # Fallback for older Neo4j versions
                try:
                    session.run(
                        f"CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE"
                    )
                except Exception:
                    pass
    
    print(f"  ✓ Created {len(constraints)} constraints")


def import_nodes(driver, filepath: Path, batch_size: int = 500) -> int:
    """Import nodes from neo4j_nodes.jsonl."""
    total = 0
    batch = []
    
    for record in read_jsonl(filepath):
        labels = record.get("labels", [])
        properties = record.get("properties", {})
        
        # Combine labels into a single label for query
        label_str = ":".join(labels)
        
        batch.append({
            "labels": label_str,
            "props": properties,
        })
        
        if len(batch) >= batch_size:
            _insert_node_batch(driver, batch)
            total += len(batch)
            print(f"  Imported {total} nodes...")
            batch = []
    
    if batch:
        _insert_node_batch(driver, batch)
        total += len(batch)
    
    return total


def _insert_node_batch(driver, batch: list):
    """Insert a batch of nodes."""
    with driver.session() as session:
        for item in batch:
            labels = item["labels"]
            props = item["props"]
            # Use MERGE to avoid duplicates
            query = f"MERGE (n:{labels} {{id: $id}}) SET n += $props"
            session.run(query, id=props.get("id"), props=props)


def import_relationships(driver, filepath: Path, batch_size: int = 1000) -> int:
    """Import relationships from neo4j_relationships.jsonl."""
    total = 0
    batch = []
    
    for record in read_jsonl(filepath):
        start_id = record.get("start")
        end_id = record.get("end")
        rel_type = record.get("type")
        properties = record.get("properties", {})
        
        if not all([start_id, end_id, rel_type]):
            continue
        
        batch.append({
            "start": start_id,
            "end": end_id,
            "type": rel_type,
            "props": properties,
        })
        
        if len(batch) >= batch_size:
            _insert_relationship_batch(driver, batch)
            total += len(batch)
            print(f"  Imported {total} relationships...")
            batch = []
    
    if batch:
        _insert_relationship_batch(driver, batch)
        total += len(batch)
    
    return total


def _insert_relationship_batch(driver, batch: list):
    """Insert a batch of relationships."""
    with driver.session() as session:
        for item in batch:
            query = f"""
            MATCH (a {{id: $start_id}})
            MATCH (b {{id: $end_id}})
            MERGE (a)-[r:{item['type']}]->(b)
            SET r += $props
            """
            session.run(
                query,
                start_id=item["start"],
                end_id=item["end"],
                props=item["props"],
            )


def import_entities(driver, filepath: Path, batch_size: int = 500) -> int:
    """Import entity nodes from entities.jsonl."""
    total = 0
    batch = []
    
    for record in read_jsonl(filepath):
        entity_id = record.get("entity_id")
        entity_type = record.get("type")
        
        if not entity_id or not entity_type:
            continue
        
        batch.append({
            "entity_id": entity_id,
            "type": entity_type,
            "canonical_name": record.get("canonical_name", ""),
            "description": record.get("description", ""),
            "mention_count": record.get("mention_count", 0),
            "aliases": json.dumps(record.get("aliases", [])),
        })
        
        if len(batch) >= batch_size:
            _insert_entity_batch(driver, batch)
            total += len(batch)
            print(f"  Imported {total} entity nodes...")
            batch = []
    
    if batch:
        _insert_entity_batch(driver, batch)
        total += len(batch)
    
    return total


def _insert_entity_batch(driver, batch: list):
    """Insert a batch of entity nodes."""
    with driver.session() as session:
        for item in batch:
            entity_type = item["type"]
            query = f"""
            MERGE (n:Entity:{entity_type} {{entity_id: $entity_id}})
            SET n.canonical_name = $canonical_name,
                n.description = $description,
                n.mention_count = $mention_count,
                n.aliases = $aliases
            """
            session.run(
                query,
                entity_id=item["entity_id"],
                canonical_name=item["canonical_name"],
                description=item["description"],
                mention_count=item["mention_count"],
                aliases=item["aliases"],
            )


def import_entity_mentions(driver, filepath: Path, batch_size: int = 2000) -> int:
    """Import MENTIONS relationships from entity_mentions.jsonl."""
    total = 0
    batch = []
    
    for record in read_jsonl(filepath):
        entity_id = record.get("entity_id")
        source_id = record.get("source_id")
        
        if not entity_id or not source_id:
            continue
        
        batch.append({
            "entity_id": entity_id,
            "source_id": source_id,
            "text_span": record.get("text_span", ""),
            "start_pos": record.get("start_pos"),
            "end_pos": record.get("end_pos"),
        })
        
        if len(batch) >= batch_size:
            _insert_mention_batch(driver, batch)
            total += len(batch)
            print(f"  Imported {total} MENTIONS relationships...")
            batch = []
    
    if batch:
        _insert_mention_batch(driver, batch)
        total += len(batch)
    
    return total


def _insert_mention_batch(driver, batch: list):
    """Insert a batch of MENTIONS relationships."""
    with driver.session() as session:
        for item in batch:
            query = """
            MATCH (e:Entity {entity_id: $entity_id})
            MATCH (s {id: $source_id})
            MERGE (s)-[r:MENTIONS]->(e)
            ON CREATE SET r.text_span = $text_span,
                         r.start_pos = $start_pos,
                         r.end_pos = $end_pos
            """
            session.run(
                query,
                entity_id=item["entity_id"],
                source_id=item["source_id"],
                text_span=item["text_span"],
                start_pos=item["start_pos"],
                end_pos=item["end_pos"],
            )


def get_stats(driver) -> dict:
    """Get database statistics."""
    with driver.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
        
        # Get node counts by label
        label_result = session.run("""
            CALL db.labels() YIELD label
            CALL apoc.cypher.run('MATCH (n:`' + label + '`) RETURN count(n) as count', {}) YIELD value
            RETURN label, value.count as count
            ORDER BY count DESC
        """)
        
        labels = {}
        try:
            for record in label_result:
                labels[record["label"]] = record["count"]
        except Exception:
            # APOC might not be available
            pass
    
    return {
        "nodes": node_count,
        "relationships": rel_count,
        "labels": labels,
    }


def main():
    parser = argparse.ArgumentParser(description="Import data into Neo4j")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory containing JSONL files (default: output)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for import operations (default: 500)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear database before import",
    )
    parser.add_argument(
        "--skip-mentions",
        action="store_true",
        help="Skip importing entity mentions (large dataset)",
    )
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    
    print("=" * 60)
    print("Neo4j Import")
    print("=" * 60)
    
    # Connect to Neo4j
    print("\nConnecting to Neo4j...")
    try:
        driver = get_neo4j_driver()
        # Test connection
        with driver.session() as session:
            session.run("RETURN 1")
        print("✓ Connected successfully")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return
    
    try:
        # Clear database
        if not args.no_clear:
            print("\nClearing database...")
            clear_database(driver)
        
        # Create constraints
        print("\nCreating constraints...")
        create_constraints(driver)
        
        results = {}
        
        # Import nodes
        nodes_file = output_dir / "neo4j_nodes.jsonl"
        if nodes_file.exists():
            print("\nImporting nodes...")
            count = import_nodes(driver, nodes_file, args.batch_size)
            results["nodes"] = count
            print(f"✓ Imported {count:,} nodes")
        
        # Import relationships
        rels_file = output_dir / "neo4j_relationships.jsonl"
        if rels_file.exists():
            print("\nImporting relationships...")
            count = import_relationships(driver, rels_file, args.batch_size)
            results["relationships"] = count
            print(f"✓ Imported {count:,} relationships")
        
        # Import entities
        entities_file = output_dir / "entities.jsonl"
        if entities_file.exists():
            print("\nImporting entity nodes...")
            count = import_entities(driver, entities_file, args.batch_size)
            results["entities"] = count
            print(f"✓ Imported {count:,} entity nodes")
        
        # Import entity mentions
        if not args.skip_mentions:
            mentions_file = output_dir / "entity_mentions.jsonl"
            if mentions_file.exists():
                print("\nImporting MENTIONS relationships...")
                count = import_entity_mentions(driver, mentions_file, args.batch_size * 2)
                results["mentions"] = count
                print(f"✓ Imported {count:,} MENTIONS relationships")
        else:
            print("\n⚠ Skipping entity mentions import")
        
        # Get stats
        print("\nGetting database statistics...")
        stats = get_stats(driver)
        
        # Summary
        print("\n" + "=" * 60)
        print("Import Summary")
        print("=" * 60)
        for key, value in results.items():
            print(f"  {key}: {value:,}")
        print("\nDatabase Stats:")
        print(f"  Total nodes: {stats['nodes']:,}")
        print(f"  Total relationships: {stats['relationships']:,}")
        if stats["labels"]:
            print("\n  Nodes by label:")
            for label, count in list(stats["labels"].items())[:10]:
                print(f"    {label}: {count:,}")
        print("=" * 60)
        
    finally:
        driver.close()
        print("\n✓ Connection closed")


if __name__ == "__main__":
    main()

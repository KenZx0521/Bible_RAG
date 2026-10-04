"""Read-only access helpers for the 1D planning simulations.

Neo4j: READ_ACCESS sessions + execute_read only (server rejects writes).
PG: set_session(readonly=True). Qdrant: scroll only.
Nothing here writes to any store.
"""
from __future__ import annotations

import os  # archived evidence script: roots are parameters, see docs/records/2026-10-04_kg_fix/README.md
BIBLE_RAG_ROOT = os.environ.get("BIBLE_RAG_ROOT", "/home/kenzx0521/Bible_RAG")
import json
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(BIBLE_RAG_ROOT)
OUT = ROOT / "output"
ENV = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
HERE = Path(__file__).resolve().parent


def neo4j(target: str = "prod"):
    from neo4j import GraphDatabase
    uri = "bolt://localhost:7687" if target == "prod" else "bolt://localhost:7688"
    return GraphDatabase.driver(uri, auth=(ENV.get("NEO4J_USER", "neo4j"),
                                           ENV.get("NEO4J_PASSWORD", "neo4j_password")),
                                notifications_min_severity="OFF")


def read(driver, cypher: str, **params) -> list[dict]:
    from neo4j import READ_ACCESS
    with driver.session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(cypher, **params)])


def pg(target: str = "prod"):
    import psycopg2
    db = "bible_rag" if target == "prod" else "bible_rag_staging"
    conn = psycopg2.connect(host=ENV.get("POSTGRES_HOST", "localhost"), port=ENV.get("POSTGRES_PORT", "5432"),
                            dbname=db, user=ENV.get("POSTGRES_USER", "bible"),
                            password=ENV.get("POSTGRES_PASSWORD", "bible_password"))
    conn.set_session(readonly=True)
    return conn


def pg_rows(target: str, sql: str, params=()):
    import psycopg2.extras
    conn = pg(target)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def jsonl(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def dump(name: str, obj) -> Path:
    p = HERE / name
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p

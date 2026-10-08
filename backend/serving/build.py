"""Which build to serve: ``rag_meta.serving`` for RAG_ENV, or RAG_BUILD_ID (design §7.6).

The backend resolves the build once, at startup, and keeps it: a promote takes
effect with the next restart, so a running backend never switches builds midway.
``rag_meta.builds`` gives the build's PG schema, Qdrant collection, contract
directory, KG flag and point count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serving.contracts import resolve_dir

SCHEMA_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
SERVING_SQL = "SELECT build_id FROM rag_meta.serving WHERE env = $1"
BUILD_SQL = ("SELECT build_id, pg_schema, qdrant_collection, contracts_dir, kg_enabled, points "
             "FROM rag_meta.builds WHERE build_id = $1")


class BuildSelectionError(RuntimeError):
    """No build can be resolved for this backend."""


@dataclass(frozen=True)
class Build:
    build_id: str
    pg_schema: str
    qdrant_collection: str
    contracts_dir: Path
    kg_enabled: bool
    points: int


async def _build_id(conn: Any, env: str, build_id: str | None) -> str:
    if build_id:
        return build_id
    row = await conn.fetchrow(SERVING_SQL, env)
    if row is None:
        raise BuildSelectionError(f"rag_meta.serving has no row for env={env}")
    return row["build_id"]


async def _lookup(conn: Any, env: str, build_id: str | None) -> Any:
    try:
        chosen = await _build_id(conn, env, build_id)
        row = await conn.fetchrow(BUILD_SQL, chosen)
    except BuildSelectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — any driver failure means no build
        raise BuildSelectionError(f"rag_meta unreadable: {exc!r}") from exc
    if row is None:
        raise BuildSelectionError(f"build {chosen} is not in rag_meta.builds")
    return row


async def resolve(conn: Any, env: str, build_id: str | None,
                  contracts_root: str | None) -> Build:
    """The build ``env`` serves (or ``build_id``), from one connection to the database."""
    row = await _lookup(conn, env, build_id)
    if not SCHEMA_RE.fullmatch(row["pg_schema"] or ""):
        raise BuildSelectionError(f"{row['pg_schema']!r} is not a schema name")
    return Build(row["build_id"], row["pg_schema"], row["qdrant_collection"],
                 resolve_dir(row["contracts_dir"], contracts_root), bool(row["kg_enabled"]),
                 int(row["points"]))

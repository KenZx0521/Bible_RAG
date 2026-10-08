"""Startup: resolve the build, open its stores, and shake hands (design §7.8).

Checks, each a handshake mismatch when it fails: the build resolves
(rag_meta.serving for RAG_ENV, equal to RAG_BUILD_ID when that is set); the
schema's build_info names it; its Qdrant collection exists with
``rag_meta.builds.points`` points; its contract directory's manifest names it
and every file hashes to the manifest (and agrees with the build row); it is not
a KG build (no Neo4j driver exists in this backend); the encoder probes equal
the contract fingerprint.

Any mismatch: /api/v1/health answers 503 with the list, no data is served, and
with STRICT_BUILD_CHECK (the default) startup fails. A build that passes still
fails startup when an event-registry anchor is missing from its passages.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from config import settings
from database import postgres, qdrant_db
from ragcommon import routing
from serving import build as build_mod
from serving import context
from serving import contracts as contracts_mod
from serving import handshake as hs
from utils.retrieval import event_registry

logger = logging.getLogger(__name__)


class StartupError(RuntimeError):
    """The backend must not start."""


async def _resolve() -> build_mod.Build:
    try:
        async with postgres.connect_meta() as conn:
            return await build_mod.resolve(conn, settings.rag_env, settings.rag_build_id,
                                           settings.contracts_root)
    except build_mod.BuildSelectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — unreachable PG is a mismatch, reported
        raise build_mod.BuildSelectionError(f"postgres unreachable: {exc!r}") from exc


async def _pg_problems(build: build_mod.Build) -> list[str]:
    try:
        return hs.check_pg(build, await postgres.build_info_ids())
    except Exception as exc:  # noqa: BLE001
        return [f"postgres: {build.pg_schema}.build_info unreadable: {exc!r}"]


def _qdrant_problems(build: build_mod.Build) -> list[str]:
    try:
        exists = qdrant_db.collection_exists()
        return hs.check_qdrant(build, exists, qdrant_db.count() if exists else None)
    except Exception as exc:  # noqa: BLE001
        return [f"qdrant: {build.qdrant_collection} unreadable: {exc!r}"]


def _contract_problems(build: build_mod.Build, found: contracts_mod.Contracts,
                       fingerprints: Mapping[str, Any]) -> list[str]:
    problems = list(found.mismatches) + hs.check_kg(build, found.manifest)
    if found.manifest:
        problems += hs.check_manifest(build, found.manifest)
    if "encoder_fingerprint.json" in found.files:
        problems += hs.check_encoders(found.json("encoder_fingerprint.json"), fingerprints)
    return problems


async def _activate(build: build_mod.Build, found: contracts_mod.Contracts) -> context.Active:
    lexicon = routing.parse_lexicon(found.json("routing_lexicon.json"))
    registry = event_registry.parse_registry(found.json("event_registry.json"))
    missing = await postgres.missing_passages(event_registry.anchor_passages(registry))
    if missing:
        raise StartupError(f"event registry anchors missing from {build.pg_schema}.passages: "
                           f"{missing}")
    return context.make_active(build, lexicon, registry)


async def start(fingerprints: Mapping[str, Any]) -> tuple[context.Active | None, hs.Handshake]:
    strict = settings.strict_build_check
    try:
        build = await _resolve()
    except build_mod.BuildSelectionError as exc:
        return None, hs.Handshake(None, (f"build: {exc}",), strict)
    await postgres.init_pool(build.pg_schema)
    qdrant_db.init_client(build.qdrant_collection)
    found = contracts_mod.verify(build.contracts_dir, build.build_id)
    problems = [*await _pg_problems(build), *_qdrant_problems(build),
                *_contract_problems(build, found, fingerprints)]
    if problems:
        return None, hs.Handshake(build.build_id, tuple(problems), strict)
    return await _activate(build, found), hs.Handshake(build.build_id, (), strict)


async def run(fingerprints: Mapping[str, Any]) -> hs.Handshake:
    """Start, install the result, and refuse to go on when strict and not ok."""
    active, handshake = await start(fingerprints)
    context.install(active, handshake)
    if handshake.ok:
        logger.info("Serving build %s", handshake.build_id)
        return handshake
    logger.error("Build handshake failed: %s", "; ".join(handshake.mismatches))
    if handshake.strict:
        raise StartupError("build handshake failed: " + "; ".join(handshake.mismatches))
    return handshake


async def stop() -> None:
    context.reset()
    await postgres.close_pool()
    qdrant_db.close_client()

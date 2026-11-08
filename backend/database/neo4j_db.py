"""Neo4j access: the only backend module that imports the driver.

Neo4j holds the graph of a KG build (``ragdata kg-project``), and it is never required: every failure
here reaches the caller as ``Skipped``, and the caller goes on without the graph. So a call is short:
0.3 s to connect, 0.4 s to get a connection, 0.8 s for the whole query, no retries (the driver's
managed transactions retry for 30 s). The driver is built on first use, so a build without a graph
never builds one. Only the templates of ``database.cypher`` can be sent, by name.

A connection or authentication error means Neo4j stays off for 30 s (no network until then; 30 s
also stays clear of the server's rate limit on wrong passwords). One timeout skips only its question;
two in a row count as Neo4j being down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from neo4j import READ_ACCESS, AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import (AuthError, ConnectionAcquisitionTimeoutError, DriverError, Neo4jError,
                              ServiceUnavailable, SessionExpired)

from config import settings
from database import cypher

logger = logging.getLogger(__name__)

POOL_SIZE, CONNECT_S, ACQUIRE_S, QUERY_S = 8, 0.3, 0.4, 0.8
SKIP_S = 30.0
TIMEOUTS_TO_SKIP = 2
# why a question went without the graph
SKIPPING, TIMEOUT, UNAVAILABLE, AUTH, ERROR, NOT_CONFIGURED = (
    "skipping", "timeout", "unavailable", "auth", "error", "not_configured")

_driver: Optional[AsyncDriver] = None
_skip_until = 0.0
_timeouts = 0


class Skipped(RuntimeError):
    """Neo4j was not read; ``reason`` is what the trace records. Never carries the driver's message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NotConfigured(Skipped):
    """NEO4J_URI, NEO4J_USER or NEO4J_PASSWORD is not set; none has a default."""

    def __init__(self, message: str = "set NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD") -> None:
        super().__init__(NOT_CONFIGURED)
        self.args = (message,)


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        if not (settings.neo4j_uri and settings.neo4j_user and settings.neo4j_password):
            raise NotConfigured()
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password),
            max_connection_pool_size=POOL_SIZE, connection_timeout=CONNECT_S,
            connection_acquisition_timeout=ACQUIRE_S, max_transaction_retry_time=0,
            telemetry_disabled=True)
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None


def _now() -> float:
    return time.monotonic()


def reset() -> None:
    """Forget the failures seen so far (a new process starts this way; tests need it)."""
    global _skip_until, _timeouts
    _skip_until, _timeouts = 0.0, 0


def _skip_for_now() -> None:
    global _skip_until, _timeouts
    _skip_until, _timeouts = _now() + SKIP_S, 0


def _note_timeout() -> None:
    global _timeouts
    _timeouts += 1
    if _timeouts >= TIMEOUTS_TO_SKIP:
        _skip_for_now()


def _template(name: str, params: dict[str, Any]) -> str:
    query = cypher.TEMPLATES.get(name)
    if query is None:
        raise ValueError(f"no Cypher template named {name[:40]!r}")
    if "$b" in query and "b" not in params:
        raise ValueError(f"template {name} needs the build id (b)")
    return query


async def _read(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async with get_driver().session(default_access_mode=READ_ACCESS) as session:
        result = await session.run(query, params)
        return [dict(record) async for record in result]


def _is_auth(exc: Neo4jError) -> bool:
    return isinstance(exc, AuthError) or ".Security." in str(exc.code or "")


async def read(name: str, **params: Any) -> list[dict[str, Any]]:
    """Template ``name``: one read-only auto-commit query within ``QUERY_S``, or ``Skipped``."""
    global _timeouts
    query = _template(name, params)
    if _now() < _skip_until:
        raise Skipped(SKIPPING)
    try:
        rows = await asyncio.wait_for(_read(query, params), QUERY_S)
    except (TimeoutError, ConnectionAcquisitionTimeoutError) as exc:
        _note_timeout()
        raise Skipped(TIMEOUT) from exc
    except (ServiceUnavailable, SessionExpired, OSError) as exc:
        _skip_for_now()
        raise Skipped(UNAVAILABLE) from exc
    except Neo4jError as exc:
        if _is_auth(exc):
            _skip_for_now()
            raise Skipped(AUTH) from exc
        logger.warning("Cypher template %s failed: %s", name, type(exc).__name__)
        raise Skipped(ERROR) from exc
    except DriverError as exc:
        logger.warning("Cypher template %s failed: %s", name, type(exc).__name__)
        raise Skipped(ERROR) from exc
    _timeouts = 0
    return rows


@dataclass
class Reads:
    """``read`` on one build, counting the queries that went out (a skip sends none)."""

    build_id: str
    n: int = 0

    async def __call__(self, name: str, **params: Any) -> list[dict[str, Any]]:
        self.n += 1
        try:
            return await read(name, b=self.build_id, **params)
        except Skipped as exc:
            if exc.reason == SKIPPING:
                self.n -= 1
            raise


async def build_info(build_id: str) -> dict[str, Any] | None:
    """What ``(:BuildInfo)`` says of the build; None when it is not there."""
    rows = await read("build_info", b=build_id)
    return dict(rows[0]["info"]) if rows else None


async def server_version() -> str | None:
    """The server's version, or None when it does not say or cannot be reached."""
    try:
        rows = await read("server_version")
    except Skipped:
        return None
    return rows[0]["version"] if rows else None

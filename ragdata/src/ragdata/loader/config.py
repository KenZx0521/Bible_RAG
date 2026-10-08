"""Where the loader connects: POSTGRES_* and QDRANT_* from the environment or an env file.

Secrets stay in the environment (or the repository's ``.env``); nothing here has a
default password. A missing setting raises instead of falling back to a default
server, so a loader never writes somewhere it was not told to (G61).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PG_KEYS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
QDRANT_KEYS = ("QDRANT_HOST", "QDRANT_HTTP_PORT", "QDRANT_GRPC_PORT")


class ConfigError(ValueError):
    """A connection setting is missing or malformed."""


@dataclass(frozen=True)
class PgSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str = ""

    def __repr__(self) -> str:      # never print the password
        return f"PgSettings({self.user}@{self.host}:{self.port}/{self.dbname})"


@dataclass(frozen=True)
class QdrantSettings:
    host: str
    http_port: int
    grpc_port: int


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines of an env file (comments, blanks and ``export`` allowed)."""
    found = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"{path}: unreadable: {exc}") from None
    for line in lines:
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found[key.strip()] = value.strip().strip("'\"")
    return found


def _need(env: Mapping[str, str], keys: tuple[str, ...]) -> list[str]:
    missing = [k for k in keys if not env.get(k)]
    if missing:
        raise ConfigError(f"missing settings {missing}")
    return [env[k] for k in keys]


def _port(value: str, key: str) -> int:
    if not value.isdigit():
        raise ConfigError(f"{key} is not a port: {value!r}")
    return int(value)


def pg_settings(env: Mapping[str, str]) -> PgSettings:
    host, port, db, user = _need(env, PG_KEYS[:4])
    return PgSettings(host, _port(port, "POSTGRES_PORT"), db, user,
                      env.get("POSTGRES_PASSWORD", ""))


def qdrant_settings(env: Mapping[str, str]) -> QdrantSettings:
    host, http, grpc = _need(env, QDRANT_KEYS)
    return QdrantSettings(host, _port(http, "QDRANT_HTTP_PORT"), _port(grpc, "QDRANT_GRPC_PORT"))

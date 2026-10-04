"""
Guard: a staging KG rebuild must never write to production.

The staging flow (docs/build_database.md, staging section) points the
pipeline at a separate Neo4j (port 7688), PostgreSQL database and Qdrant
entity collection purely through environment variables. Every script also
calls load_dotenv(), so a variable the operator forgot to export silently
falls back to .env's production value — and import_neo4j.py clears the whole
graph, import_postgres.py truncates its tables, embed_entities.py --recreate
drops the collection.

Scripts that write call ``assert_target(<stores they touch>)`` before
connecting. With ``KG_TARGET=staging`` every requested setting must be set and
must differ from production; otherwise the script exits before any write.
With ``KG_TARGET`` unset (or ``prod``) behaviour is unchanged.

Writers whose store has no staging copy at all (the passage collections
bible_embeddings*, shared with production and outside a staging rebuild) call
``refuse_under_staging(reason)`` instead: under staging they cannot run.

scripts/tools/staging.env sets every variable checked here. Before a staging
rebuild, check the shell with

    scripts/.venv/bin/python scripts/kg_target.py --require-staging neo4j postgres qdrant

which, unlike assert_target, also refuses a shell without KG_TARGET (exit 1)
and prints the endpoints the scripts will write to (exit 0).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

TARGETS = ("prod", "staging")
_PROD_NEO4J_PORT = 7687

# store -> (environment variable, predicate "this value is production")
_PRODUCTION = {
    "neo4j": ("NEO4J_URI", lambda v: (urlparse(v).port or _PROD_NEO4J_PORT) == _PROD_NEO4J_PORT),
    "postgres": ("POSTGRES_DB", lambda v: v == "bible_rag"),
    "qdrant": ("QDRANT_ENTITY_COLLECTION", lambda v: v == "bible_entities"),
}

# Whatever .env names is production too: R3 promotes the entity collection by
# pointing .env at bible_entities_vN, after which the names above miss it.
DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _dotenv() -> dict[str, str]:
    if not DOTENV_PATH.is_file():
        return {}
    return {k: v for k, v in dotenv_values(DOTENV_PATH).items() if v is not None}


def _dotenv_production() -> dict[str, str]:
    return {k: v for k, v in _dotenv().items() if v}


def is_production(store: str, value: str) -> bool:
    """Whether ``value`` of ``store``'s setting names the production store:
    the fixed production names, or whatever the repo .env sets."""
    name, is_named_production = _PRODUCTION[store]
    return is_named_production(value) or value == _dotenv_production().get(name)


def _active_target() -> str:
    target = os.getenv("KG_TARGET", "prod") or "prod"
    if target not in TARGETS:
        raise SystemExit(f"KG_TARGET={target!r}: expected one of {TARGETS}")
    return target


def assert_target(*stores: str) -> str:
    """Return the active target; exit if a staging run would reach production.

    ``stores`` names the databases the calling script writes to
    (``neo4j``, ``postgres``, ``qdrant``).
    """
    unknown = sorted(set(stores) - set(_PRODUCTION))
    if unknown:
        raise ValueError(f"unknown stores {unknown}; expected {sorted(_PRODUCTION)}")

    target = _active_target()
    if target == "prod":
        return target

    problems = []
    for store in stores:
        name, _ = _PRODUCTION[store]
        value = os.getenv(name, "")
        if not value:
            problems.append(f"{name} is not set (would fall back to .env production)")
        elif is_production(store, value):
            problems.append(f"{name}={value} is the production {store}")
    if problems:
        raise SystemExit(
            "KG_TARGET=staging refused before connecting:\n  " + "\n  ".join(problems)
            + "\nSource scripts/tools/staging.env (docs/build_database.md, staging section)."
        )
    return target


def refuse_under_staging(reason: str) -> None:
    """Exit under ``KG_TARGET=staging``; a no-op otherwise.

    For writers whose store has no staging copy: no environment variable can
    point them anywhere but production, so a staging run must stop there.
    """
    if _active_target() == "staging":
        raise SystemExit(
            f"KG_TARGET=staging refused before connecting: {reason}"
            "\nThis step is not part of a staging rebuild (docs/build_database.md, staging section)."
        )


def _endpoint(store: str) -> str:
    """Where the scripts connect for ``store``: after load_dotenv() the shell
    wins over .env, and each script falls back to the same defaults."""
    dotenv = _dotenv()

    def setting(name: str, default: str = "") -> str:
        return os.environ.get(name, dotenv.get(name, default))

    if store == "neo4j":
        return setting("NEO4J_URI", "bolt://localhost:7687")
    if store == "postgres":
        return (f"{setting('POSTGRES_HOST', 'localhost')}:{setting('POSTGRES_PORT', '5432')}"
                f"/{setting('POSTGRES_DB', 'bible_rag')}")
    port = setting("QDRANT_PORT") or setting("QDRANT_HTTP_PORT", "6333")
    return (f"{setting('QDRANT_HOST', 'localhost')}:{port}"
            f"/{setting('QDRANT_ENTITY_COLLECTION', 'bible_entities')}")


def require_staging(*stores: str) -> dict[str, str]:
    """assert_target for an operator's shell: an unset KG_TARGET is refused too.

    assert_target lets a shell without KG_TARGET through (production is the
    default there), so it cannot tell whether staging.env was sourced. Returns
    store -> endpoint the scripts will write to.
    """
    if assert_target(*stores) != "staging":
        raise SystemExit(
            "KG_TARGET is not staging: scripts run from this shell write production "
            "and none of them would refuse.\n"
            "Run: source scripts/tools/staging.env (docs/build_database.md, staging section)."
        )
    return {store: _endpoint(store) for store in stores}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-flight check for a staging KG rebuild: exit 1 unless this "
                    "shell targets staging and every named store is isolated from production.")
    parser.add_argument("--require-staging", nargs="+", required=True, metavar="STORE",
                        choices=sorted(_PRODUCTION), help="stores to check: %(choices)s")
    args = parser.parse_args(argv)
    endpoints = require_staging(*args.require_staging)
    print("KG_TARGET=staging; writes go to:")
    for store, endpoint in endpoints.items():
        print(f"  {store:<9} {endpoint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""kg_target: a staging rebuild must never write to production.

import_neo4j clears the whole graph, import_postgres truncates its tables and
embed_entities --recreate drops the collection. With KG_TARGET=staging, any
connection setting that still resolves to production (left unset, so .env's
production value leaks in, or set by mistake) must stop the script before it
connects.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import kg_target

ROOT = Path(__file__).resolve().parents[2]
STAGING_ENV = ROOT / "scripts" / "tools" / "staging.env"
STAGING_COMPOSE = ROOT / "docker-compose.staging.yml"

STAGING = {
    "KG_TARGET": "staging",
    "NEO4J_URI": "bolt://localhost:7688",
    "POSTGRES_DB": "bible_rag_staging",
    "QDRANT_ENTITY_COLLECTION": "bible_entities_v2",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in ("KG_TARGET", "NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION"):
        monkeypatch.delenv(name, raising=False)
    # Hermetic: no repo .env unless a test writes this one.
    monkeypatch.setattr(kg_target, "DOTENV_PATH", tmp_path / ".env")

    def set_env(values):
        for name, value in values.items():
            monkeypatch.setenv(name, value)
    return set_env


def test_unset_target_keeps_legacy_behaviour(env):
    env({"NEO4J_URI": "bolt://localhost:7687"})
    assert kg_target.assert_target("neo4j", "postgres", "qdrant") == "prod"


def test_staging_with_every_setting_isolated_passes(env):
    env(STAGING)
    assert kg_target.assert_target("neo4j", "postgres", "qdrant") == "staging"


@pytest.mark.parametrize("name, prod_value", [
    ("NEO4J_URI", "bolt://localhost:7687"),
    ("NEO4J_URI", "bolt://localhost"),           # no port = default 7687
    ("NEO4J_URI", "neo4j://localhost:7687"),
    ("POSTGRES_DB", "bible_rag"),
    ("QDRANT_ENTITY_COLLECTION", "bible_entities"),
])
def test_staging_refuses_any_production_setting(env, name, prod_value):
    env({**STAGING, name: prod_value})
    with pytest.raises(SystemExit) as exc:
        kg_target.assert_target("neo4j", "postgres", "qdrant")
    assert name in str(exc.value)


@pytest.mark.parametrize("name", ["NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION"])
def test_staging_refuses_a_missing_setting(env, name):
    env({k: v for k, v in STAGING.items() if k != name})
    with pytest.raises(SystemExit) as exc:
        kg_target.assert_target("neo4j", "postgres", "qdrant")
    assert name in str(exc.value)


def test_only_the_requested_stores_are_checked(env):
    """A Neo4j-only script must not fail on an unrelated Qdrant setting."""
    env({**STAGING, "QDRANT_ENTITY_COLLECTION": "bible_entities"})
    assert kg_target.assert_target("neo4j") == "staging"


def test_staging_refuses_the_collection_dotenv_promoted(env):
    """R3 promotes by pointing .env at bible_entities_vN: from then on that name
    is production, and a staging.env nobody bumped must not recreate it."""
    kg_target.DOTENV_PATH.write_text("QDRANT_ENTITY_COLLECTION=bible_entities_v2\n", encoding="utf-8")
    env(STAGING)

    with pytest.raises(SystemExit) as exc:
        kg_target.assert_target("qdrant")

    assert "QDRANT_ENTITY_COLLECTION=bible_entities_v2 is the production qdrant" in str(exc.value)


def test_staging_passes_once_bumped_past_the_promoted_collection(env):
    kg_target.DOTENV_PATH.write_text("QDRANT_ENTITY_COLLECTION=bible_entities_v2\n", encoding="utf-8")
    env({**STAGING, "QDRANT_ENTITY_COLLECTION": "bible_entities_v3"})

    assert kg_target.assert_target("neo4j", "postgres", "qdrant") == "staging"


def test_dotenv_production_values_do_not_touch_prod_runs(env):
    kg_target.DOTENV_PATH.write_text("QDRANT_ENTITY_COLLECTION=bible_entities_v2\n", encoding="utf-8")
    env({"QDRANT_ENTITY_COLLECTION": "bible_entities_v2"})

    assert kg_target.assert_target("qdrant") == "prod"


def test_unknown_target_is_rejected(env):
    env({**STAGING, "KG_TARGET": "stagin"})
    with pytest.raises(SystemExit, match="KG_TARGET"):
        kg_target.assert_target("neo4j")


def test_unknown_store_is_a_programming_error(env):
    with pytest.raises(ValueError):
        kg_target.assert_target("redis")


# --- refuse_under_staging: writers whose store has no staging copy -----------

PASSAGE_REASON = "recreates the shared passage collection bible_embeddings"


@pytest.mark.parametrize("target", [None, "", "prod"])
def test_refuse_under_staging_is_a_no_op_outside_staging(env, target):
    if target is not None:
        env({"KG_TARGET": target})
    assert kg_target.refuse_under_staging(PASSAGE_REASON) is None


def test_refuse_under_staging_exits_even_with_isolated_settings(env):
    """No setting can make it safe: the passage collections are shared with prod."""
    env(STAGING)
    with pytest.raises(SystemExit) as exc:
        kg_target.refuse_under_staging(PASSAGE_REASON)
    assert "KG_TARGET=staging" in str(exc.value)
    assert PASSAGE_REASON in str(exc.value)


def test_refuse_under_staging_rejects_an_unknown_target(env):
    env({"KG_TARGET": "stagin"})
    with pytest.raises(SystemExit, match="KG_TARGET"):
        kg_target.refuse_under_staging(PASSAGE_REASON)


# --- scripts/tools/staging.env: one set of staging values ---------------------

PRODUCTION_SHELL = {  # a shell that already holds .env's production values
    "NEO4J_URI": "bolt://localhost:7687",
    "POSTGRES_DB": "bible_rag",
    "QDRANT_ENTITY_COLLECTION": "bible_entities",
}


def _sourced(environ):
    """Exported environment of a bash that sourced staging.env, starting from ``environ``.

    ``env`` runs as a child process, so only exported variables come back, and
    cwd=/ shows the file does not depend on where it is sourced from.
    """
    out = subprocess.run(
        ["bash", "-c", 'source "$1" && env -0', "bash", str(STAGING_ENV)],
        env={"PATH": os.environ["PATH"], **environ},
        cwd="/", capture_output=True, check=True,
    ).stdout.decode()
    return dict(item.split("=", 1) for item in out.split("\0") if item)


def _compose():
    return yaml.safe_load(STAGING_COMPOSE.read_text(encoding="utf-8"))["services"]


def _compose_default(expression, name):
    """Default of ``${name:-default}`` inside a compose value."""
    match = re.search(r"\$\{" + name + r":-([^}]*)\}", expression)
    assert match, f"{name} default not found in {expression!r}"
    return match.group(1)


@pytest.mark.parametrize("shell", [{}, PRODUCTION_SHELL], ids=["clean-shell", "production-shell"])
def test_sourcing_staging_env_passes_the_guard_for_every_store(env, shell):
    sourced = _sourced(shell)

    assert sourced["KG_TARGET"] == "staging"
    assert sourced["NEO4J_URI"] == "bolt://localhost:7688"
    assert sourced["POSTGRES_DB"] == "bible_rag_staging"
    assert re.fullmatch(r"bible_entities_v\d+", sourced["QDRANT_ENTITY_COLLECTION"])
    env({k: sourced[k] for k in ("KG_TARGET", *PRODUCTION_SHELL)})
    assert kg_target.assert_target("neo4j", "postgres", "qdrant") == "staging"


def test_staging_env_leaves_passage_collections_alone():
    """Step 4/4.1 refuse staging anyway; setting these would only suggest otherwise."""
    sourced = _sourced({})
    assert "QDRANT_COLLECTION" not in sourced
    assert "QDRANT_HYBRID_COLLECTION" not in sourced


def test_staging_env_neo4j_credentials_follow_neo4j_staging_auth():
    """Unset: compose's NEO4J_AUTH defaults. Exported: kept, as compose would use them."""
    auth = _compose()["neo4j-staging"]["environment"]["NEO4J_AUTH"]

    defaults = _sourced({})
    exported = _sourced({"NEO4J_USER": "kay", "NEO4J_PASSWORD": "s3cret"})

    assert defaults["NEO4J_USER"] == _compose_default(auth, "NEO4J_USER")
    assert defaults["NEO4J_PASSWORD"] == _compose_default(auth, "NEO4J_PASSWORD")
    assert (exported["NEO4J_USER"], exported["NEO4J_PASSWORD"]) == ("kay", "s3cret")


def test_staging_env_bolt_port_is_the_one_neo4j_staging_publishes():
    ports = _compose()["neo4j-staging"]["ports"]
    bolt = next(p for p in ports if p.endswith(":7687"))

    assert _sourced({})["NEO4J_URI"].endswith(":" + _compose_default(bolt, "NEO4J_STAGING_BOLT_PORT"))


def test_staging_env_stays_in_the_syntax_compose_env_file_parses():
    """backend-staging reads this file as an env_file: plain `export KEY=value` only."""
    lines = [line for line in STAGING_ENV.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]

    assert lines
    for line in lines:
        assert re.fullmatch(r"export [A-Z_][A-Z0-9_]*=\S+", line), line


def test_backend_staging_reads_the_same_values_as_the_scripts():
    """One file, so the backend cannot drift from the scripts (e.g. a bumped vN)."""
    backend = _compose()["backend-staging"]
    env_files = [f if isinstance(f, str) else f["path"] for f in backend["env_file"]]
    environment = backend["environment"]

    # Later env_files win, so staging.env must come after .env.
    assert env_files.index("scripts/tools/staging.env") > env_files.index(".env")
    # `environment` would override the env_file; only container-network hosts may.
    for name in ("KG_TARGET", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION",
                 "STAGING_POSTGRES_DB", "STAGING_QDRANT_ENTITY_COLLECTION"):
        assert name not in environment
    assert environment["NEO4J_URI"] == "bolt://neo4j-staging:7687"


# --- python scripts/kg_target.py --require-staging: the operator's pre-flight --
#
# assert_target passes a shell without KG_TARGET (production is the default),
# which is exactly the shell a staging rebuild must not run in. The CLI refuses
# that too, so it can be rerun on its own in a fresh terminal.

KG_TARGET_SCRIPT = ROOT / "scripts" / "kg_target.py"
ALL_STORES = ["neo4j", "postgres", "qdrant"]


def _require(*stores):
    return kg_target.main(["--require-staging", *stores])


@pytest.mark.parametrize("target", [None, "", "prod"])
def test_require_staging_refuses_a_shell_that_is_not_staging(env, target):
    env({k: v for k, v in STAGING.items() if k != "KG_TARGET"})
    if target is not None:
        env({"KG_TARGET": target})

    with pytest.raises(SystemExit) as exc:
        _require(*ALL_STORES)

    assert exc.value.code != 0
    assert "source scripts/tools/staging.env" in str(exc.value)


@pytest.mark.parametrize("name", ["NEO4J_URI", "POSTGRES_DB", "QDRANT_ENTITY_COLLECTION"])
def test_require_staging_still_refuses_production_settings(env, name):
    env({**STAGING, name: PRODUCTION_SHELL[name]})

    with pytest.raises(SystemExit) as exc:
        _require(*ALL_STORES)

    assert f"{name}={PRODUCTION_SHELL[name]}" in str(exc.value)


@pytest.mark.parametrize("qdrant_port, expected_port", [({"QDRANT_PORT": "16333"}, "16333"),
                                                         ({}, "26333")])
def test_require_staging_prints_the_resolved_endpoints(env, monkeypatch, capsys,
                                                       qdrant_port, expected_port):
    """As load_dotenv() leaves them for the scripts: the shell wins over .env,
    .env fills the rest, and QDRANT_PORT wins over QDRANT_HTTP_PORT."""
    kg_target.DOTENV_PATH.write_text(
        "NEO4J_URI=bolt://localhost:7687\nPOSTGRES_DB=bible_rag\nPOSTGRES_HOST=pg-from-dotenv\n"
        "QDRANT_ENTITY_COLLECTION=bible_entities\nQDRANT_HTTP_PORT=26333\n", encoding="utf-8")
    for name in ("POSTGRES_HOST", "POSTGRES_PORT", "QDRANT_HOST", "QDRANT_PORT", "QDRANT_HTTP_PORT"):
        monkeypatch.delenv(name, raising=False)
    env({**STAGING, "POSTGRES_PORT": "15432", "QDRANT_HOST": "qdrant-host", **qdrant_port})

    assert _require(*ALL_STORES) == 0

    out = capsys.readouterr().out
    assert re.search(r"neo4j\s+bolt://localhost:7688$", out, re.M)
    assert re.search(r"postgres\s+pg-from-dotenv:15432/bible_rag_staging$", out, re.M)
    assert re.search(rf"qdrant\s+qdrant-host:{expected_port}/bible_entities_v2$", out, re.M)


def test_require_staging_checks_only_the_named_stores(env, capsys):
    env({**STAGING, "QDRANT_ENTITY_COLLECTION": "bible_entities"})

    assert _require("neo4j") == 0
    assert "qdrant" not in capsys.readouterr().out


def test_require_staging_rejects_an_unknown_store(env):
    env(STAGING)
    with pytest.raises(SystemExit) as exc:
        _require("redis")
    assert exc.value.code == 2   # argparse usage error


def _run_cli(environ):
    return subprocess.run(
        [sys.executable, str(KG_TARGET_SCRIPT), "--require-staging", *ALL_STORES],
        env={"PATH": os.environ["PATH"], **environ}, cwd="/", capture_output=True, text=True)


def test_cli_exit_codes_as_a_script():
    """The runbook calls the file directly: exit 1 outside staging, 0 inside."""
    refused = _run_cli({})
    # A collection name no .env will have been promoted to.
    passed = _run_cli({**STAGING, "QDRANT_ENTITY_COLLECTION": "bible_entities_v9999"})

    assert refused.returncode == 1
    assert "source scripts/tools/staging.env" in refused.stderr
    assert passed.returncode == 0, passed.stderr
    assert "bolt://localhost:7688" in passed.stdout
    assert "bible_rag_staging" in passed.stdout and "bible_entities_v9999" in passed.stdout

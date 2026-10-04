"""KG_TARGET=staging: every write script refuses before it connects.

Each writer's connection points are replaced by a recorder that stops the run
at the first call. A refused run must reach none of them; a run with isolated
staging settings (or without KG_TARGET) must reach one, which shows the
recorders sit where the script really connects.

Split from test_db_env.py (see test_db_env_contract.py). As there, the scripts
are imported at collection time, so their import-time load_dotenv() never runs
inside a monkeypatched test.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

import backfill_aliases
import backfill_event_relations
import backfill_verse_mentions
import cleanup_noise_entities
import embed_entities
import import_postgres
import import_qdrant
import import_qdrant_hybrid
import import_relations_neo4j
import import_tsk_crossrefs
# staging_target is a pytest fixture: importing it is what makes it available here.
from _db_env_helpers import _Stop, staging_target  # noqa: F401

# The staging_target fixture sets _db_env_helpers.STAGING_TARGET; these are the
# production values each of its store settings must differ from.
PRODUCTION_SETTING = {  # store -> (variable, production value)
    "neo4j": ("NEO4J_URI", "bolt://localhost:7687"),
    "postgres": ("POSTGRES_DB", "bible_rag"),
    "qdrant": ("QDRANT_ENTITY_COLLECTION", "bible_entities"),
}


@dataclass(frozen=True)
class Writer:
    module: ModuleType
    stores: tuple[str, ...]
    connections: tuple[tuple[object, str], ...]   # (owner, attribute) the script connects through
    argv: Callable[[Path], list[str]] = lambda tmp: []  # creates the inputs main() needs
    stubs: tuple[tuple[object, str, object], ...] = ()


def _file(path: Path, text: str = "") -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def _output_dir_with(files: dict[str, str]) -> Callable[[Path], list[str]]:
    def argv(tmp: Path) -> list[str]:
        for name, text in files.items():
            _file(tmp / name, text)
        return ["--output-dir", str(tmp)]
    return argv


_CLEANUP_CONNECTIONS = tuple((cleanup_noise_entities, name)
                             for name in ("get_neo4j", "get_qdrant", "get_postgres"))

WRITERS = {
    "import_postgres": Writer(
        import_postgres, ("postgres",), ((import_postgres, "get_db_connection"),),
        argv=lambda tmp: ["--output-dir", str(tmp)]),
    "embed_entities": Writer(
        embed_entities, ("neo4j", "qdrant"),
        ((embed_entities, "QdrantClient"), (embed_entities.GraphDatabase, "driver"))),
    "import_tsk_crossrefs": Writer(
        import_tsk_crossrefs, ("neo4j",), ((import_tsk_crossrefs, "get_driver"),),
        argv=lambda tmp: [_file(tmp / "cross_references.txt", "From\tTo\tVotes\n")],
        stubs=((import_tsk_crossrefs, "build_verse_map", lambda path: {}),)),
    "import_relations_neo4j": Writer(
        import_relations_neo4j, ("neo4j",), ((import_relations_neo4j.GraphDatabase, "driver"),),
        argv=lambda tmp: [_file(tmp / "relations.jsonl", '{"relation": "FATHER_OF"}\n')]),
    "backfill_aliases": Writer(
        backfill_aliases, ("neo4j",), ((backfill_aliases, "get_driver"),)),
    "backfill_event_relations": Writer(
        backfill_event_relations, ("neo4j",), ((backfill_event_relations, "get_driver"),),
        argv=lambda tmp: ["--input", _file(tmp / "relations_unclassified.jsonl")]),
    "backfill_verse_mentions": Writer(
        backfill_verse_mentions, ("neo4j",), ((backfill_verse_mentions, "get_driver"),),
        argv=_output_dir_with({"entity_mentions.jsonl": '{"source_type": "verse", '
                               '"source_id": "gen_1:v:1", "entity_id": "person:x"}\n'})),
    # Only the dan action stays inside Neo4j; the others also sync PG and Qdrant.
    "cleanup_noise_entities[dan]": Writer(
        cleanup_noise_entities, ("neo4j",), _CLEANUP_CONNECTIONS,
        argv=lambda tmp: ["--actions", "dan"]),
    "cleanup_noise_entities[all]": Writer(
        cleanup_noise_entities, ("neo4j", "postgres", "qdrant"), _CLEANUP_CONNECTIONS),
}

# Step 4/4.1 write the passage collections, which staging shares with production.
PASSAGE_WRITERS = {
    "import_qdrant": Writer(
        import_qdrant, (), ((import_qdrant, "get_qdrant_client"), (import_qdrant, "QdrantClient")),
        argv=_output_dir_with({"embeddings.jsonl": ""})),
    "import_qdrant_hybrid": Writer(
        import_qdrant_hybrid, (),
        ((import_qdrant_hybrid, "get_qdrant_client"), (import_qdrant_hybrid, "QdrantClient")),
        argv=_output_dir_with({"embeddings.jsonl": "", "sparse_vectors.jsonl": ""})),
}


def _run_main(writer: Writer, monkeypatch, tmp_path, reached: list) -> None:
    def recorder(name):
        def connect(*args, **kwargs):
            reached.append(name)
            raise _Stop
        return connect

    for owner, attr in writer.connections:
        monkeypatch.setattr(owner, attr, recorder(attr))
    for owner, attr, value in writer.stubs:
        monkeypatch.setattr(owner, attr, value)
    monkeypatch.setattr(sys, "argv", [f"{writer.module.__name__}.py", *writer.argv(tmp_path)])
    try:
        writer.module.main()
    except (_Stop, SystemExit) as exc:  # importers exit 1 on a failed connection
        if isinstance(exc, SystemExit) and (exc.code != 1 or not reached):
            raise


GUARD_CASES = [(name, store) for name, writer in WRITERS.items() for store in writer.stores]


@pytest.mark.parametrize("name, store", GUARD_CASES)
def test_staging_refuses_a_missing_setting_before_connecting(name, store, staging_target,
                                                             monkeypatch, tmp_path):
    variable, _ = PRODUCTION_SETTING[store]
    monkeypatch.delenv(variable)
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert "KG_TARGET=staging refused" in str(exc.value)
    assert variable in str(exc.value)
    assert reached == []


@pytest.mark.parametrize("name, store", GUARD_CASES)
def test_staging_refuses_a_production_setting_before_connecting(name, store, staging_target,
                                                                monkeypatch, tmp_path):
    variable, production = PRODUCTION_SETTING[store]
    monkeypatch.setenv(variable, production)
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert f"{variable}={production}" in str(exc.value)
    assert reached == []


def test_a_neo4j_only_run_does_not_need_the_sync_settings(staging_target, monkeypatch, tmp_path):
    for variable, _ in (PRODUCTION_SETTING["postgres"], PRODUCTION_SETTING["qdrant"]):
        monkeypatch.delenv(variable)
    reached = []

    _run_main(WRITERS["cleanup_noise_entities[dan]"], monkeypatch, tmp_path, reached)

    assert reached == ["get_neo4j"]


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_isolated_staging_settings_reach_the_connection(name, staging_target, monkeypatch, tmp_path):
    reached = []

    _run_main(WRITERS[name], monkeypatch, tmp_path, reached)

    assert len(reached) == 1


@pytest.mark.parametrize("name", sorted({**WRITERS, **PASSAGE_WRITERS}))
def test_unset_target_connects_as_before(name, monkeypatch, tmp_path):
    monkeypatch.delenv("KG_TARGET", raising=False)
    reached = []

    _run_main({**WRITERS, **PASSAGE_WRITERS}[name], monkeypatch, tmp_path, reached)

    assert len(reached) == 1


@pytest.mark.parametrize("name", sorted(PASSAGE_WRITERS))
def test_passage_collection_writers_refuse_any_staging_run(name, staging_target, monkeypatch, tmp_path):
    """No setting makes them safe: bible_embeddings* has no staging copy."""
    reached = []

    with pytest.raises(SystemExit) as exc:
        _run_main(PASSAGE_WRITERS[name], monkeypatch, tmp_path, reached)

    assert "KG_TARGET=staging refused" in str(exc.value)
    assert reached == []

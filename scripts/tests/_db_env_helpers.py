"""Pieces shared by the DB env tests, split from test_db_env.py.

test_db_env_contract.py, test_staging_write_guards.py and test_cleanup_sync.py
import from here, and test_import_relations.py takes write_relations_clean.
staging_target is a pytest fixture: a test module gets it by importing it.
"""

import hashlib
import json
from pathlib import Path

import pytest

import kg_target

PP_VERSION = "pp-000000000000"
ONE_ROW = {"head_id": "person:a", "relation": "FATHER_OF", "tail_id": "person:b",
           "source": "llm", "pp_version": PP_VERSION}


def write_relations_clean(directory: Path, rows: list[dict] | None = None,
                          pp_version: str = PP_VERSION) -> Path:
    """A relations_clean.jsonl and the report 6.05 writes beside it; the jsonl's path.

    Lines are serialised as 6.05 writes them, and the report's output.sha256 and
    rows match the bytes, so the file passes 6.1's input contract unless a test
    edits one of the two afterwards. rows defaults to the single ONE_ROW.
    """
    rows = [ONE_ROW] if rows is None else rows
    data = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                   for row in rows).encode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "relations_clean.jsonl"
    path.write_bytes(data)
    report = {"format": "relations_postprocess_report/v1", "pp_version": pp_version,
              "output": {"path": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                         "rows": len(rows)}}
    (directory / "relations_clean.report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


class _Stop(Exception):
    """Raised by a fake client once its constructor arguments are captured."""


class _FakeQdrant:
    def get_collections(self):
        return None


STAGING_TARGET = {
    "KG_TARGET": "staging",
    "NEO4J_URI": "bolt://localhost:7688",
    "POSTGRES_DB": "bible_rag_staging",
    "QDRANT_ENTITY_COLLECTION": "bible_entities_v2",
}


@pytest.fixture
def staging_target(monkeypatch, tmp_path):
    for key, value in STAGING_TARGET.items():
        monkeypatch.setenv(key, value)
    # kg_target also treats the repo .env's values as production; keep the
    # outcome independent of which collection .env has been promoted to.
    monkeypatch.setattr(kg_target, "DOTENV_PATH", tmp_path / "no.env")

"""Write the backend's test build: the ragdata mini release, as the loader would load it.

The mini release (ragdata/tests/mini_release.py: five books, six chapters, every
special case of design §2.23 — a merged unit, an omitted slot, a mid-verse heading,
a superscription, a speaker, a chunked passage) goes through ``ragdata.loader.load``
with a recording PG and an in-memory Qdrant, and the result is written to
``backend/tests/fixtures/mini_build/``:

- ``pg.sql``: the build schema and ``rag_meta`` exactly as the loader writes them
  (DDL, COPY data, keys, indexes) plus the ``rag_meta.builds`` row, for ``psql``;
- ``points.jsonl``: the Qdrant points (id, vector, payload);
- ``contracts/{build_id}/``: the contract files and their manifest;
- ``build.json``: build id, PG schema, collection, point count and vector width.

``rag_meta.builds.contracts_dir`` is written as ``/contracts/{build_id}``, the path the
backend container sees (it re-roots it under ``CONTRACTS_ROOT``).

Run it with the ragdata environment (scripts/.venv), from the repository root:

    PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \\
        scripts/.venv/bin/python backend/tests/fixtures/make_mini_build.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for extra in (REPO / "packages", REPO / "ragdata" / "src", REPO / "ragdata" / "tests"):
    sys.path.insert(0, str(extra))

from qdrant_client import QdrantClient  # noqa: E402

import mini_loaded  # noqa: E402
from fake_pg import FakePg  # noqa: E402
from ragdata.loader import load as loader  # noqa: E402
from ragdata.loader import sql  # noqa: E402
from ragdata.loader.qdrant import QdrantDb  # noqa: E402

OUT = Path(__file__).resolve().parent / "mini_build"
CONTAINER_CONTRACTS = "/contracts"


class RecordingPg(FakePg):
    """FakePg that keeps the plan and the builds row it was asked to apply."""

    def apply(self, plan, build, during):
        self.plan, self.build = plan, dict(build)
        super().apply(plan, build, during)


def literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return literal(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"


def builds_insert(build: dict) -> str:
    cols = ", ".join(sql.ident(c) for c in sql.BUILD_COLUMNS)
    values = ", ".join(literal(build[c]) for c in sql.BUILD_COLUMNS)
    return f'INSERT INTO "{sql.META}"."builds" ({cols}) VALUES ({values})'


def pg_script(plan, build: dict) -> str:
    lines = ["\\set ON_ERROR_STOP on", "BEGIN;", f"CREATE SCHEMA {sql.ident(plan.schema)};"]
    lines += [f"{statement};" for statement in plan.create]
    for step in plan.copies:
        lines += [f"{step.sql};", step.data + "\\."]
    lines += [f"{statement};" for statement in (*plan.finish, *sql.META_DDL)]
    lines += [f"{builds_insert(build)};", "COMMIT;"]
    return "\n".join(lines) + "\n"


def points_jsonl(qdrant: QdrantDb, collection: str) -> str:
    points = sorted(qdrant.points(collection), key=lambda p: p.payload["record_id"])
    return "".join(json.dumps({"id": p.id, "vector": [float(x) for x in p.vector],
                               "payload": p.payload}, ensure_ascii=False, sort_keys=True) + "\n"
                   for p in points)


def write(root: Path) -> dict:
    pg = RecordingPg()
    loaded = mini_loaded.load(root)
    # load again into the recording PG: same release, fresh targets
    qdrant = QdrantDb(QdrantClient(location=":memory:"))
    report = loader.load(loaded.release, pg, qdrant, root / "contracts2")
    build_id = report["build_id"]
    build = {**pg.build, "contracts_dir": f"{CONTAINER_CONTRACTS}/{build_id}"}
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "contracts").mkdir(parents=True)
    (OUT / "pg.sql").write_text(pg_script(pg.plan, build), encoding="utf-8")
    (OUT / "points.jsonl").write_text(points_jsonl(qdrant, report["qdrant_collection"]),
                                      encoding="utf-8")
    target = OUT / "contracts" / build_id
    shutil.copytree(Path(report["contracts_dir"]), target)
    for path in [target, *target.iterdir()]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    meta = {"build_id": build_id, "pg_schema": report["pg_schema"],
            "qdrant_collection": report["qdrant_collection"], "points": report["points"],
            "dim": len(qdrant.points(report["qdrant_collection"])[0].vector)}
    (OUT / "build.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(json.dumps(write(Path(tmp))))

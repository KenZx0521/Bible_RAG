"""S13: load a release into a slot nothing serves (design §7.1–7.3, §7.5).

The only input is a verified release (``release.read_release``). Before anything
is written: the records pass G-SCHEMA again, the vectors attachment is read and
checked row by row against the embedding records (record id, text sha, row sha),
and the targets are checked: the build must not be serving, not be registered in
``rag_meta.builds``, and its PG schema ``b{build_id}``, Qdrant collection
``passages__{build_id}`` and ``contracts/{build_id}/`` must not exist. Nothing is
ever cleared to make room.

Then one PG transaction creates the schema, copies every table, adds keys,
indexes and ANALYZE, registers the build in ``rag_meta.builds``, and, before it
commits, creates and fills the Qdrant collection (counting its points) and writes
the contract files. A failure rolls PG back (and drops the schema it created); a
collection or contract directory already written is named in the error, for
the operator: the loader deletes nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ragdata import paths
from ragdata.gates.schema import check_schema
from ragdata.loader import sql
from ragdata.loader.contracts_emit import MANIFEST, write_contracts
from ragdata.loader.plan import CopyStep, LoaderError, PgPlan, Point
from ragdata.loader.tables import BUILD_INFO, TABLES
from ragdata.release.assemble import Release
from ragdata.release.contracts import encode
from ragdata.store import StoreError, attach, vectors
from ragdata.store.cas import sha256_bytes
from ragdata.store.vectors import VectorSet, row_sha

RECORD_LAYERS = ("text", "struct", "emb", "kg0", "events", "route")
CONTRACTS_SCHEMA = "ragdata.contracts_manifest.v1"
Files = Mapping[str, Sequence[Mapping[str, Any]]]


class LoadError(LoaderError):
    """The release cannot be loaded, or a target is taken."""


@dataclass(frozen=True)
class Targets:
    build_id: str
    schema: str
    collection: str
    contracts_dir: Path


def targets(build_id: str, contracts_root: Path = paths.CONTRACTS) -> Targets:
    """``b{build_id}`` with what an unquoted identifier cannot hold removed."""
    schema = "b" + re.sub(r"[^a-z0-9_]", "", build_id.lower())
    return Targets(build_id, schema, f"passages__{build_id}", Path(contracts_root) / build_id)


def record_files(release: Release) -> dict[str, tuple[dict[str, Any], ...]]:
    return {name: rows for layer in RECORD_LAYERS
            for name, rows in release.layers[layer].rows.items()}


def gate_snapshot(files: Files) -> None:
    result, _ = check_schema(files, RECORD_LAYERS)
    if not result.passed:
        raise LoadError(f"G-SCHEMA fails on the release's records: {list(result.details[:5])}")


@dataclass(frozen=True)
class Vectors:
    found: VectorSet
    file_shas: Mapping[str, str]


def _misaligned(found: VectorSet, records: Sequence[Mapping[str, Any]]) -> str | None:
    if found.matrix.shape[0] != len(records) or len(found.index) != len(records):
        return f"{found.matrix.shape[0]} rows for {len(records)} records"
    for i, (row, record) in enumerate(zip(found.index, records)):
        if (row["record_id"], row["text_sha"], row["row"]) != \
                (record["record_id"], record["text_sha"], i):
            return f"row {i} is {row['record_id']}, the records have {record['record_id']}"
        if row["vec_sha"] != row_sha(found.matrix[i]):
            return f"row {i} ({row['record_id']}) does not hash to its vec_sha"
    return None


def read_vectors(release: Release, files: Files) -> Vectors:
    try:
        meta, contents = attach.read_attachment(release.layers["emb"].path, vectors.NAME)
        found = vectors.decode_vectors(contents)
    except StoreError as exc:
        raise LoadError(f"vectors of {release.layers['emb'].version}: {exc}") from None
    bad = _misaligned(found, files["embedding_records.jsonl"])
    if bad:
        raise LoadError(f"vectors of {release.layers['emb'].version}: {bad}")
    return Vectors(found, dict(meta.file_shas))


def refuse_taken(t: Targets, pg: Any, qdrant: Any) -> None:
    serving = pg.serving()
    taken = [f"serving ({env})" for env, build in sorted(serving.items()) if build == t.build_id]
    taken += ["registered in rag_meta.builds"] if pg.build_row(t.build_id) else []
    taken += [f"PG schema {t.schema} exists"] if pg.schema_exists(t.schema) else []
    taken += [f"Qdrant collection {t.collection} exists"] if qdrant.exists(t.collection) else []
    taken += [f"{t.contracts_dir} exists"] if t.contracts_dir.exists() else []
    if taken:
        raise LoadError(f"refusing to load {t.build_id}: {'; '.join(taken)}")


def _build_info(release: Release, vec: Vectors) -> dict[str, Any]:
    return {"build_id": release.build_id, "release_sha": release.release_sha,
            "kg_enabled": bool(release.doc["kg_enabled"]), "release": dict(release.doc),
            "vectors": {"layer": release.layers["emb"].version, "files": dict(vec.file_shas)}}


def plan_pg(t: Targets, files: Files, release: Release, vec: Vectors) -> PgPlan:
    rows = {table.name: table.rows(files) for table in TABLES}
    rows[BUILD_INFO.name] = [_build_info(release, vec)]
    every = (*TABLES, BUILD_INFO)
    copies = tuple(CopyStep(tb.name, sql.copy_sql(t.schema, tb), sql.copy_data(tb, rows[tb.name]),
                            len(rows[tb.name])) for tb in every)
    finish = (*(sql.add_fk(t.schema, tb, key) for tb in every for key in tb.fks),
              *(sql.create_index(t.schema, tb, cols) for tb in every for cols in tb.indexes),
              *(f"ANALYZE {sql.qualified(t.schema, tb.name)}" for tb in every))
    return PgPlan(t.schema, tuple(sql.create_table(t.schema, tb) for tb in every), copies, finish)


def qdrant_points(files: Files, matrix: np.ndarray, build_id: str) -> list[Point]:
    return [Point(r["point_id"], matrix[i], {**r["payload"], "build_id": build_id})
            for i, r in enumerate(files["embedding_records.jsonl"])]


def contracts_manifest(release: Release, t: Targets, points: int, vec: Vectors) -> bytes:
    return encode({"schema": CONTRACTS_SCHEMA, "build_id": release.build_id,
                   "release_sha": release.release_sha, "kg_enabled": release.doc["kg_enabled"],
                   "layers": {k: v for k, v in release.doc["layers"].items() if v},
                   "pg_schema": t.schema, "qdrant_collection": t.collection, "points": points,
                   "files": dict(release.doc["contracts"]),
                   "vectors": {"layer": release.layers["emb"].version,
                               "files": dict(vec.file_shas)}})


def build_row(release: Release, t: Targets, points: int) -> dict[str, Any]:
    return {"build_id": release.build_id, "release_sha": release.release_sha,
            "manifest_sha": sha256_bytes(release.data), "pg_schema": t.schema,
            "qdrant_collection": t.collection, "contracts_dir": str(t.contracts_dir),
            "kg_enabled": bool(release.doc["kg_enabled"]), "points": points,
            "manifest": dict(release.doc)}


def _fill(t: Targets, qdrant: Any, points: list[Point], dim: int,
          contracts: Mapping[str, bytes]) -> None:
    qdrant.create(t.collection, dim)
    qdrant.upsert(t.collection, points)
    found = qdrant.count(t.collection)
    if found != len(points):
        raise LoadError(f"{t.collection} holds {found} points, expected {len(points)}")
    write_contracts(t.contracts_dir, contracts)


def _left_behind(t: Targets, qdrant: Any) -> list[str]:
    left = [f"Qdrant collection {t.collection}"] if qdrant.exists(t.collection) else []
    return left + ([str(t.contracts_dir)] if t.contracts_dir.exists() else [])


def load(release: Release, pg: Any, qdrant: Any,
         contracts_root: Path = paths.CONTRACTS) -> dict[str, Any]:
    """Write ``release`` to PG, Qdrant and the contract directory; return what was written."""
    t = targets(release.build_id, contracts_root)
    files = record_files(release)
    gate_snapshot(files)
    vec = read_vectors(release, files)
    refuse_taken(t, pg, qdrant)
    plan = plan_pg(t, files, release, vec)
    points = qdrant_points(files, vec.found.matrix, release.build_id)
    contracts = {**release.contracts, MANIFEST: contracts_manifest(release, t, len(points), vec)}
    try:
        pg.apply(plan, build_row(release, t, len(points)),
                 lambda: _fill(t, qdrant, points, int(vec.found.matrix.shape[1]), contracts))
    except Exception as exc:
        left = _left_behind(t, qdrant)
        raise LoadError(f"load of {t.build_id} failed, PG rolled back: {exc}"
                        + (f"; left behind for the operator: {left}" if left else "")) from exc
    return {"build_id": t.build_id, "pg_schema": t.schema, "qdrant_collection": t.collection,
            "contracts_dir": str(t.contracts_dir), "points": len(points),
            "rows": {step.table: step.rows for step in plan.copies}}

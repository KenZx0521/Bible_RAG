"""``ragdata unload BUILD_ID``: remove what ``load`` wrote for one build, and nothing else.

A loaded build owns four things, each named after its build id (``load.targets``): the
PG schema ``b{build_id}``, its ``rag_meta.builds`` row, the Qdrant collection
``passages__{build_id}`` and ``contracts/{build_id}/``. Unload deletes exactly those:

- only for a build id of the release grammar (``b{YYYYMMDD}_{8 hex}``), so the legacy
  build, the public schema and the legacy collections can never be named;
- never for a build ``rag_meta.serving`` points at (checked under a row lock in the same
  transaction; the serving table's foreign key refuses the delete as well);
- not at all when the builds row records another schema, collection or contract
  directory than the build id's own.

One PG transaction drops the schema and deletes the row; before it commits, the
collection and then the contract directory are deleted (a failure there rolls PG back).
A piece that is already gone is skipped, so running unload again finishes one that was
interrupted. The release file in ``releases/`` is the store's, not the build's: unload
leaves it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from ragcommon import ids
from ragdata import paths
from ragdata.loader.load import Targets, targets
from ragdata.loader.plan import LoaderError

OWNED = ("pg_schema", "builds_row", "qdrant_collection", "contracts_dir")


class UnloadError(LoaderError):
    """The build cannot be unloaded: not a release build, serving, or not what it claims."""


def owned_targets(build_id: str, contracts_root: Path = paths.CONTRACTS) -> Targets:
    """The targets of a release build id; anything else is refused."""
    if not ids.is_valid(build_id, "build") or ids.parse(build_id).text == "legacy":
        raise UnloadError(f"{build_id!r} is not a release build id (b<YYYYMMDD>_<8 hex>)")
    return targets(build_id, contracts_root)


def _check_row(t: Targets, row: Mapping[str, Any] | None) -> None:
    if row is None:
        return
    want = {"pg_schema": t.schema, "qdrant_collection": t.collection,
            "contracts_dir": str(t.contracts_dir)}
    wrong = [f"{k} is {row.get(k)!r}, not {v!r}" for k, v in want.items() if row.get(k) != v]
    if wrong:
        raise UnloadError(f"rag_meta.builds names other targets for {t.build_id}: "
                          f"{'; '.join(wrong)}; nothing was deleted")


def _refuse_serving(t: Targets, pg: Any) -> None:
    envs = sorted(env for env, build in pg.serving().items() if build == t.build_id)
    if envs:
        raise UnloadError(f"{t.build_id} is serving {envs}; promote another build first")


def _outside_pg(t: Targets, qdrant: Any) -> None:
    if qdrant.exists(t.collection):
        qdrant.delete(t.collection)
    if t.contracts_dir.exists():
        shutil.rmtree(t.contracts_dir)


def unload(build_id: str, pg: Any, qdrant: Any,
           contracts_root: Path = paths.CONTRACTS) -> dict[str, Any]:
    """Delete the build's four targets; return which were there (``removed``) and not."""
    t = owned_targets(build_id, contracts_root)
    row = pg.build_row(build_id)
    _check_row(t, row)
    _refuse_serving(t, pg)
    present = {"pg_schema": pg.schema_exists(t.schema), "builds_row": row is not None,
               "qdrant_collection": qdrant.exists(t.collection),
               "contracts_dir": t.contracts_dir.exists()}
    try:
        pg.drop_build(t.schema, build_id, lambda: _outside_pg(t, qdrant))
    except LoaderError as exc:
        raise UnloadError(f"unload of {build_id} stopped, PG rolled back: {exc}") from exc
    return {"build_id": build_id, "pg_schema": t.schema, "qdrant_collection": t.collection,
            "contracts_dir": str(t.contracts_dir),
            "removed": [k for k in OWNED if present[k]],
            "absent": [k for k in OWNED if not present[k]]}

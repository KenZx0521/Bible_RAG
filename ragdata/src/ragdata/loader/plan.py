"""What the loader hands the database adapters: the PG plan and the Qdrant points.

Kept apart from ``pg`` and ``qdrant`` so the planning and checking modules never
import a database driver (G-IMPORT): only those two adapters do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


class LoaderError(RuntimeError):
    """A load or a projection read cannot proceed (bad release, taken target, database)."""


@dataclass(frozen=True)
class CopyStep:
    table: str
    sql: str
    data: str
    rows: int


@dataclass(frozen=True)
class PgPlan:
    schema: str
    create: tuple[str, ...]            # CREATE TABLE …
    copies: tuple[CopyStep, ...]
    finish: tuple[str, ...]            # foreign keys, indexes, ANALYZE


@dataclass(frozen=True)
class Point:
    id: str
    vector: np.ndarray
    payload: Mapping[str, Any]

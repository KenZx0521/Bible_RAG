"""Comparing two encodings of the same records (G-DET for vectors, design §4, §6).

GPU encoding need not be bit for bit reproducible, so two runs agree when every
row pair has cosine >= 0.99999 and, for 200 rows sampled with a fixed seed used
as queries, each run's top-20 neighbours (by dot product, over its own rows) are
the same set.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

DET_COS = 0.99999
TOP_K = 20
QUERIES = 200
SEED = 0
MAX_LISTED = 20


def rowwise_cos(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a64, b64 = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    norms = np.linalg.norm(a64, axis=1) * np.linalg.norm(b64, axis=1)
    return np.einsum("ij,ij->i", a64, b64) / np.where(norms == 0, 1.0, norms)


def topk_sets(matrix: np.ndarray, queries: np.ndarray, k: int) -> list[frozenset[int]]:
    scores = np.asarray(queries, dtype=np.float32) @ np.asarray(matrix, dtype=np.float32).T
    k = min(k, matrix.shape[0])
    top = np.argpartition(-scores, k - 1, axis=1)[:, :k]
    return [frozenset(int(i) for i in row) for row in top]


def query_rows(n: int, queries: int = QUERIES, seed: int = SEED) -> np.ndarray:
    return np.sort(np.random.default_rng(seed).choice(n, size=min(n, queries), replace=False))


def compare_runs(ids_a: Sequence[str], a: np.ndarray, ids_b: Sequence[str], b: np.ndarray,
                 cos_min: float = DET_COS, k: int = TOP_K, queries: int = QUERIES
                 ) -> tuple[dict[str, Any], list[str]]:
    """Observed figures and violations for run ``a`` against run ``b``."""
    if list(ids_a) != list(ids_b) or a.shape != b.shape:
        return ({"rows": [len(ids_a), len(ids_b)]},
                [f"the runs encode other records: {len(ids_a)} rows {a.shape} vs "
                 f"{len(ids_b)} rows {b.shape}"])
    cos = rowwise_cos(a, b)
    low = np.flatnonzero(cos < cos_min)
    violations = [f"{ids_a[i]}: cos {cos[i]:.7f} < {cos_min}" for i in low[:MAX_LISTED]]
    rows = query_rows(len(ids_a), queries)
    differ = [int(r) for r, x, y in zip(rows, topk_sets(a, a[rows], k), topk_sets(b, b[rows], k))
              if x != y]
    violations += [f"{ids_a[r]}: top-{k} neighbours differ between the runs"
                   for r in differ[:MAX_LISTED]]
    observed = {"rows": len(ids_a), "min_cos": float(cos.min()) if cos.size else None,
                "below_cos": int(low.size), "queries": int(rows.size), "topk_differ": len(differ)}
    return observed, violations

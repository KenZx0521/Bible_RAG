"""The emb vectors attachment: ``vectors.npy`` and ``vector_index.jsonl`` (design §2.16).

``vectors.npy`` is an ``(records, dim)`` little-endian float32 array, one row per
embedding record in file order. ``vector_index.jsonl`` names each row:
``{record_id, row, text_sha, vec_sha}``, where ``vec_sha`` is the sha256 of the
row's float32 bytes.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any, Mapping, Sequence

import numpy as np

from ragdata.store.jsonl import StoreError, decode_jsonl, encode_jsonl

NAME = "vectors"
VECTORS = "vectors.npy"
INDEX = "vector_index.jsonl"
DTYPE = np.dtype("<f4")


def row_sha(row: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(row, dtype=DTYPE).tobytes()).hexdigest()


def as_matrix(vectors: np.ndarray, rows: int) -> np.ndarray:
    """``vectors`` as a C-ordered float32 matrix of ``rows`` rows; raise otherwise."""
    matrix = np.ascontiguousarray(vectors, dtype=DTYPE)
    if matrix.ndim != 2 or matrix.shape[0] != rows or matrix.shape[1] == 0:
        raise StoreError(f"vectors of shape {np.shape(vectors)} are not one row for each "
                         f"of {rows} records")
    return matrix


def encode_vectors(records: Sequence[tuple[str, str]], vectors: np.ndarray) -> dict[str, bytes]:
    """The attachment files for ``(record_id, text_sha)`` rows and their vectors."""
    matrix = as_matrix(vectors, len(records))
    buf = io.BytesIO()
    np.save(buf, matrix, allow_pickle=False)
    index = [{"record_id": rid, "row": i, "text_sha": sha, "vec_sha": row_sha(matrix[i])}
             for i, (rid, sha) in enumerate(records)]
    return {VECTORS: buf.getvalue(), INDEX: encode_jsonl(index)}


def decode_vectors(files: Mapping[str, bytes]) -> tuple[np.ndarray, tuple[dict[str, Any], ...]]:
    """The matrix and the index rows of an attachment (consistency is G-EMB's to check)."""
    if set(files) != {VECTORS, INDEX}:
        raise StoreError(f"a vectors attachment holds {VECTORS} and {INDEX}, not {sorted(files)}")
    try:
        matrix = np.load(io.BytesIO(files[VECTORS]), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise StoreError(f"{VECTORS}: not a numpy array: {exc}") from None
    if matrix.dtype != DTYPE or matrix.ndim != 2:
        raise StoreError(f"{VECTORS}: expected a 2-d float32 array, got {matrix.dtype} "
                         f"{matrix.shape}")
    return matrix, decode_jsonl(files[INDEX], INDEX)

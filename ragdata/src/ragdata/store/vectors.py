"""The emb vectors attachment (design §2.16, §6): ``vectors.npy``, ``vector_index.jsonl``
and ``probe_vectors.json``.

``vectors.npy`` is an ``(records, dim)`` little-endian float32 array, one row per
embedding record in file order. ``vector_index.jsonl`` names each row:
``{record_id, row, text_sha, vec_sha}``, where ``vec_sha`` is the sha256 of the
row's float32 bytes. ``probe_vectors.json`` holds the encodings of
``ragcommon.encoder``'s BGE-M3 probes rounded to 1e-6 and kept as integers
(``probe_vectors_e6``), with their sha (``probe_vectors_sha``); G-ENC compares
another environment's probe vectors with them by cosine. Like the rows they
differ in their last digits from one device to another, which is why they are
kept here and not in the layer (whose version must not depend on the device).
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ragdata.store.jsonl import StoreError, decode_jsonl, encode_jsonl

NAME = "vectors"
VECTORS = "vectors.npy"
INDEX = "vector_index.jsonl"
PROBES = "probe_vectors.json"
PROBES_SCHEMA = "ragdata.probe_vectors.v1"
DTYPE = np.dtype("<f4")
SCALE = 1e6


@dataclass(frozen=True)
class VectorSet:
    """A decoded attachment; the arrays are read-only."""

    matrix: np.ndarray                   # (records, dim) float32
    index: tuple[dict[str, Any], ...]    # vector_index.jsonl rows
    probes: np.ndarray                   # (probes, dim) float64: probe_vectors_e6 / 1e6
    probes_sha: str                      # probe_vectors_sha


def row_sha(row: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(row, dtype=DTYPE).tobytes()).hexdigest()


def probe_ints(vectors: np.ndarray) -> list[list[int]]:
    """Probe vectors rounded to 1e-6, as integers."""
    return np.rint(np.asarray(vectors, dtype=np.float64) * SCALE).astype(np.int64).tolist()


def ints_sha(ints: Sequence[Sequence[int]]) -> str:
    return hashlib.sha256(json.dumps(ints, separators=(",", ":")).encode()).hexdigest()


def as_matrix(vectors: np.ndarray, rows: int) -> np.ndarray:
    """``vectors`` as a C-ordered float32 matrix of ``rows`` rows; raise otherwise."""
    matrix = np.ascontiguousarray(vectors, dtype=DTYPE)
    if matrix.ndim != 2 or matrix.shape[0] != rows or matrix.shape[1] == 0:
        raise StoreError(f"vectors of shape {np.shape(vectors)} are not one row for each "
                         f"of {rows} records")
    return matrix


def _probe_bytes(probes: np.ndarray) -> bytes:
    p = np.asarray(probes, dtype=np.float64)
    if p.ndim != 2 or 0 in p.shape or not np.isfinite(p).all():
        raise StoreError(f"probe vectors of shape {p.shape} are not a finite, non-empty matrix")
    ints = probe_ints(p)
    doc = {"schema": PROBES_SCHEMA, "probe_vectors_e6": ints, "probe_vectors_sha": ints_sha(ints)}
    return (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode()


def encode_vectors(records: Sequence[tuple[str, str]], vectors: np.ndarray,
                   probes: np.ndarray) -> dict[str, bytes]:
    """The attachment files for ``(record_id, text_sha)`` rows, their vectors, and the
    encoder's probe vectors."""
    matrix = as_matrix(vectors, len(records))
    buf = io.BytesIO()
    np.save(buf, matrix, allow_pickle=False)
    index = [{"record_id": rid, "row": i, "text_sha": sha, "vec_sha": row_sha(matrix[i])}
             for i, (rid, sha) in enumerate(records)]
    return {VECTORS: buf.getvalue(), INDEX: encode_jsonl(index), PROBES: _probe_bytes(probes)}


def _frozen(array: np.ndarray) -> np.ndarray:
    array.flags.writeable = False
    return array


def _decode_matrix(data: bytes) -> np.ndarray:
    try:
        matrix = np.load(io.BytesIO(data), allow_pickle=False)
    except (ValueError, OSError, EOFError) as exc:
        raise StoreError(f"{VECTORS}: not a numpy array: {exc}") from None
    if matrix.dtype != DTYPE or matrix.ndim != 2:
        raise StoreError(f"{VECTORS}: expected a 2-d float32 array, got {matrix.dtype} "
                         f"{matrix.shape}")
    return _frozen(matrix)


def _decode_probes(data: bytes) -> tuple[np.ndarray, str]:
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise StoreError(f"{PROBES}: not JSON: {exc}") from None
    keys = {"schema", "probe_vectors_e6", "probe_vectors_sha"}
    if not isinstance(doc, dict) or set(doc) != keys or doc["schema"] != PROBES_SCHEMA:
        raise StoreError(f"{PROBES}: expected {sorted(keys)} of {PROBES_SCHEMA}")
    ints = doc["probe_vectors_e6"]
    try:
        array = np.asarray(ints)
    except ValueError:            # ragged rows
        array = np.zeros(0)
    if array.ndim != 2 or array.dtype.kind != "i" or 0 in array.shape:
        raise StoreError(f"{PROBES}: probe_vectors_e6 is not a matrix of integers")
    if doc["probe_vectors_sha"] != ints_sha(ints):
        raise StoreError(f"{PROBES}: probe_vectors_sha is not the sha of probe_vectors_e6")
    return _frozen(array / SCALE), doc["probe_vectors_sha"]


def decode_vectors(files: Mapping[str, bytes]) -> VectorSet:
    """The matrix, index rows and probe vectors of an attachment (whether the index and
    the probes fit the layer is for G-EMB and G-ENC to check)."""
    if set(files) != {VECTORS, INDEX, PROBES}:
        raise StoreError(f"a vectors attachment holds {VECTORS}, {INDEX} and {PROBES}, "
                         f"not {sorted(files)}")
    probes, probes_sha = _decode_probes(files[PROBES])
    return VectorSet(_decode_matrix(files[VECTORS]), decode_jsonl(files[INDEX], INDEX),
                     probes, probes_sha)

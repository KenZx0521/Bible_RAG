"""``encoder_fingerprint.json`` (design §2.16, §6): what encoded the emb layer.

- ``bge_m3``: model, revision and encode settings; the pinned tokenizer's
  fingerprint (tokenizer.json sha, probe input_ids sha, <unk> count, pair
  template); the vectors of ``ragcommon.encoder``'s probes rounded to 1e-6, kept
  as integers (``probe_vectors_e6``), and their sha. Other environments compare
  their probe vectors with these by cosine (G-ENC).
- ``reranker``: model, revision and the pinned tokenizer's fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from ragcommon import encoder as pins
from ragdata.stages.s06_emb.encoder import Encoder, encode_texts

SCHEMA = "ragdata.encoder_fingerprint.v1"
SCALE = 1e6


def probe_ints(vectors: np.ndarray) -> list[list[int]]:
    return np.rint(np.asarray(vectors, dtype=np.float64) * SCALE).astype(np.int64).tolist()


def ints_sha(ints: Sequence[Sequence[int]]) -> str:
    return hashlib.sha256(json.dumps(ints, separators=(",", ":")).encode()).hexdigest()


def probe_section(enc: Encoder) -> dict[str, Any]:
    ints = probe_ints(encode_texts(enc, pins.BGE_M3.probes))
    return {"probes": len(pins.BGE_M3.probes), "probe_vectors_e6": ints,
            "probe_vectors_sha": ints_sha(ints)}


def encoder_fingerprint(enc: Encoder) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "bge_m3": {**enc.model, **enc.tokenizers[pins.BGE_M3.name], **probe_section(enc)},
        "reranker": {"model": pins.RERANKER.repo_id, "revision": pins.RERANKER.revision,
                     **enc.tokenizers[pins.RERANKER.name]},
    }


def encode(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")

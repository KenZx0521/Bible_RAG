"""A stand-in S7 encoder for the mini snapshot: hash vectors, mini token counts, pinned ids.

``vector(text)`` is a deterministic unit vector, so the same text always gets the
same row (the legacy-compatibility check relies on it) and different texts differ.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

import numpy as np

import mini_build
from ragcommon import encoder
from ragdata.stages.s06_emb.encoder import Encoder
from ragdata.stages.s06_emb.records import TokenStats

DIM = 8


def vector(text: str, dim: int = DIM) -> np.ndarray:
    raw = np.frombuffer(hashlib.sha256(text.encode("utf-8")).digest()[:dim], dtype=np.uint8)
    v = raw.astype(np.float64) - 127.5
    return (v / np.linalg.norm(v)).astype(np.float32)


def embed(texts: Sequence[str]) -> np.ndarray:
    return np.stack([vector(t) for t in texts]) if texts else np.zeros((0, DIM), np.float32)


def tokenizer_fp(spec: encoder.EncoderSpec) -> dict:
    return {"tokenizer_sha": spec.tokenizer_sha256, "probe_ids_sha": spec.probe_ids_sha,
            "unk_count": 3, "pair_template_ok": True}


def make(embed_fn=embed, dim: int = DIM, max_seq_length: int = 8192, **model) -> Encoder:
    return Encoder(
        embed=embed_fn,
        stats=TokenStats(lambda t: (mini_build.count_tokens(t), mini_build.count_unk(t))),
        model={"model": encoder.BGE_M3.repo_id, "revision": encoder.BGE_M3.revision,
               "dim": dim, "max_seq_length": max_seq_length, "normalize": True,
               "batch_size": 32, **model},
        tokenizers={encoder.BGE_M3.name: tokenizer_fp(encoder.BGE_M3),
                    encoder.RERANKER.name: tokenizer_fp(encoder.RERANKER)},
        runtime={"device": "cpu", "stand_in": True},
    )

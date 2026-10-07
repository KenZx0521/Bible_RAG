"""``encoder_fingerprint.json`` (design §2.16, §6): what encoded the emb layer.

It holds only what every machine running the pinned encoder computes alike:

- ``bge_m3``: model, revision and encode settings; the pinned tokenizer's
  fingerprint (tokenizer.json sha, probe input_ids sha, <unk> count, pair
  template); the number of probes;
- ``reranker``: model, revision and the pinned tokenizer's fingerprint.

The probe vectors themselves (``probe_vectors``) differ in their last digits from
one GPU, or the CPU, to another, and so would their sha at any rounding. They
go with the rows into the ``vectors`` attachment (``store.vectors``), which does
not enter the layer version: rebuilding elsewhere gives the same ``emb@``
(design §6, C-N13), and G-ENC compares the stored probes by cosine.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import numpy as np

from ragcommon import encoder as pins
from ragdata.stages.s06_emb.encoder import Encoder, encode_texts

SCHEMA = "ragdata.encoder_fingerprint.v2"


def probe_vectors(enc: Encoder) -> np.ndarray:
    """``ragcommon.encoder``'s BGE-M3 probes encoded by ``enc``."""
    return encode_texts(enc, pins.BGE_M3.probes)


def encoder_fingerprint(enc: Encoder) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "bge_m3": {**enc.model, **enc.tokenizers[pins.BGE_M3.name],
                   "probes": len(pins.BGE_M3.probes)},
        "reranker": {"model": pins.RERANKER.repo_id, "revision": pins.RERANKER.revision,
                     **enc.tokenizers[pins.RERANKER.name]},
    }


def encode(doc: Mapping[str, Any]) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")

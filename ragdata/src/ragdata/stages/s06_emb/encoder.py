"""S7 encoder: the pinned BGE-M3 with the pinned tokenizer, as the old build encoded.

Settings are those of scripts/generate_embeddings.py and scripts/embeddings/
embedder.py: ``SentenceTransformer("BAAI/bge-m3")`` (max_seq_length 8192 from
the snapshot, CLS pooling), ``normalize_embeddings=True``, batch size 32. The
model loads offline (``local_files_only``) from the snapshot ``refs/main`` must
name; its tokenizer is replaced by ``ragcommon.encoder``'s pinned tokenizer.json,
as the backend's embedder does (G28). The reranker contributes only its pinned
tokenizer fingerprint: S7 does not rerank. Any failure raises StageError.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ragcommon import encoder as pins
from ragdata import paths
from ragdata.stages.errors import StageError
from ragdata.stages.s06_emb.records import TokenStats

BATCH_SIZE = 32
NORM_TOLERANCE = 1e-3
RERANKER_TOKENIZER = paths.RERANKER_TOKENIZER


@dataclass(frozen=True)
class Encoder:
    embed: Callable[[Sequence[str]], np.ndarray]   # texts -> (n, dim) unit rows
    stats: TokenStats
    model: Mapping[str, Any]        # model, revision, dim, max_seq_length, normalize, batch_size
    tokenizers: Mapping[str, Mapping[str, Any]]    # ragcommon.encoder fingerprints by name
    runtime: Mapping[str, Any]      # device and library versions (not part of the layer)


def _pinned_tokenizers(tokenizer: Path | None, reranker: Path) -> tuple[Any, dict, dict]:
    try:
        m3, m3_fp = pins.load_pinned(pins.BGE_M3, tokenizer)
        _, rr_fp = pins.load_pinned(pins.RERANKER, reranker)
        pins.pinned_tokenizer_file(pins.BGE_M3, pins.hub_cache_dir())   # refs/main is the pin
    except (pins.EncoderContractError, OSError) as exc:
        raise StageError(f"pinned tokenizer: {exc}") from exc
    return m3, m3_fp, rr_fp


def _model(device: str | None) -> tuple[Any, dict[str, Any]]:
    import sentence_transformers
    import torch
    import transformers

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        model = sentence_transformers.SentenceTransformer(pins.BGE_M3.repo_id, device=device,
                                                          local_files_only=True)
    except OSError as exc:
        raise StageError(f"{pins.BGE_M3.repo_id}: cannot load offline: {exc}") from exc
    runtime = {"device": device, "torch": torch.__version__,
               "transformers": transformers.__version__,
               "sentence_transformers": sentence_transformers.__version__}
    return model, runtime


def load_encoder(tokenizer: Path | None = None, reranker_tokenizer: Path = RERANKER_TOKENIZER,
                 device: str | None = None, batch_size: int = BATCH_SIZE) -> Encoder:
    """The pinned BGE-M3 (``tokenizer``: its tokenizer.json, None for the HF cache)."""
    m3, m3_fp, rr_fp = _pinned_tokenizers(tokenizer, Path(reranker_tokenizer))
    model, runtime = _model(device)
    model.tokenizer = m3
    unk = m3.unk_token_id

    def stats(text: str) -> tuple[int, int]:
        ids = m3(text, add_special_tokens=False)["input_ids"]
        return len(ids), ids.count(unk)

    def embed(texts: Sequence[str]) -> np.ndarray:
        return model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False)

    info = {"model": pins.BGE_M3.repo_id, "revision": pins.BGE_M3.revision,
            "dim": model.get_sentence_embedding_dimension(),
            "max_seq_length": model.max_seq_length, "normalize": True, "batch_size": batch_size}
    return Encoder(embed, TokenStats(stats), info,
                   {pins.BGE_M3.name: m3_fp, pins.RERANKER.name: rr_fp}, runtime)


def encode_texts(enc: Encoder, texts: Sequence[str]) -> np.ndarray:
    """One float32 unit row per text, in order; raise when the encoder breaks that."""
    vectors = np.asarray(enc.embed(texts), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(texts):
        raise StageError(f"the encoder returned {vectors.shape} for {len(texts)} texts")
    if not np.isfinite(vectors).all():
        raise StageError("the encoder returned non-finite values")
    norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
    off = np.flatnonzero(np.abs(norms - 1) > NORM_TOLERANCE)
    if off.size:
        raise StageError(f"{off.size} vectors are not unit length (first: row {off[0]})")
    return vectors

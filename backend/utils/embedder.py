"""
BGE-M3 query embedding for semantic search.
Loads model at startup and provides encode function.
"""

import logging
from typing import Optional

import numpy as np

from config import settings
from ragcommon import encoder

logger = logging.getLogger(__name__)

_model = None
_device: Optional[str] = None
_fingerprint: Optional[dict] = None


def init_model():
    """Load BGE-M3 at startup, encoding with the pinned tokenizer.json (G28).

    Raises EncoderContractError, failing startup, when the configured model is
    not the pinned one or its tokenizer fails the contract probes.
    """
    global _model, _device, _fingerprint
    from sentence_transformers import SentenceTransformer
    import torch

    encoder.check_model_name(encoder.BGE_M3, settings.embedding_model)
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading {settings.embedding_model} on {_device}...")
    model = SentenceTransformer(settings.embedding_model, device=_device)
    # After the model: loading it by repo id may move refs/main, which the pin checks.
    tokenizer, fingerprint = encoder.load_pinned(encoder.BGE_M3)
    model.tokenizer = tokenizer
    _model, _fingerprint = model, fingerprint
    logger.info(
        f"Embedding model loaded. dim={settings.embedding_dim}, device={_device}, "
        f"tokenizer fingerprint={fingerprint}"
    )


def get_device() -> str:
    return _device or "unknown"


def get_fingerprint() -> Optional[dict]:
    """The pinned tokenizer's fingerprint, or None before init_model succeeded."""
    return dict(_fingerprint) if _fingerprint else None


def encode_query(text: str) -> list[float]:
    """Encode a query string into a 1024-dim embedding vector."""
    if _model is None:
        raise RuntimeError("Embedding model not initialized")
    embedding = _model.encode(text, normalize_embeddings=True)
    return embedding.tolist()

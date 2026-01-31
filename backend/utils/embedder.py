"""
BGE-M3 query embedding for semantic search.
Loads model at startup and provides encode function.
"""

import logging
from typing import Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)

_model = None
_device: Optional[str] = None


def init_model():
    """Load BGE-M3 model to GPU (or CPU fallback) at startup."""
    global _model, _device
    from sentence_transformers import SentenceTransformer
    import torch

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading {settings.embedding_model} on {_device}...")
    _model = SentenceTransformer(settings.embedding_model, device=_device)
    logger.info(f"Embedding model loaded. dim={settings.embedding_dim}, device={_device}")


def get_device() -> str:
    return _device or "unknown"


def encode_query(text: str) -> list[float]:
    """Encode a query string into a 1024-dim embedding vector."""
    if _model is None:
        raise RuntimeError("Embedding model not initialized")
    embedding = _model.encode(text, normalize_embeddings=True)
    return embedding.tolist()

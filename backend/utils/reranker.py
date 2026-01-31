"""
BGE Reranker v2 M3 for cross-encoder reranking.
Uses transformers AutoModelForSequenceClassification directly.
"""

import logging

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config import settings

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_device = None


def init_reranker():
    """Load bge-reranker-v2-m3 at startup."""
    global _model, _tokenizer, _device

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading reranker {settings.reranker_model} on {_device}...")

    _tokenizer = AutoTokenizer.from_pretrained(settings.reranker_model)
    _model = AutoModelForSequenceClassification.from_pretrained(
        settings.reranker_model,
        torch_dtype=torch.float16 if _device == "cuda" else torch.float32,
    ).to(_device)
    _model.eval()

    logger.info("Reranker loaded")


def _compute_scores(pairs: list[list[str]]) -> list[float]:
    """Compute reranker scores for query-passage pairs."""
    with torch.no_grad():
        inputs = _tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(_device)
        scores = _model(**inputs, return_dict=True).logits.view(-1).float()

    # Sigmoid normalize to [0, 1]
    scores = torch.sigmoid(scores)
    return scores.cpu().tolist()


def rerank(query: str, passages: list[dict], top_k: int = 5, text_key: str = "content") -> list[dict]:
    """
    Rerank passages using bge-reranker-v2-m3 cross-encoder.

    Args:
        query: The user query.
        passages: List of dicts, each must have `text_key` field.
        top_k: Number of top results to return.
        text_key: Key in passage dict containing the text to score.

    Returns:
        Top-k passages sorted by reranker score, with 'rerank_score' added.
    """
    if _model is None:
        raise RuntimeError("Reranker not initialized")

    if not passages:
        return []

    pairs = [[query, p.get(text_key, "")] for p in passages]
    scores = _compute_scores(pairs)

    for p, s in zip(passages, scores):
        p["rerank_score"] = float(s)

    ranked = sorted(passages, key=lambda x: x["rerank_score"], reverse=True)
    return ranked[:top_k]

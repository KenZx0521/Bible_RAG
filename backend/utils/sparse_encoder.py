"""
Sparse encoder for query-time BM25 vector generation.
Loads pre-computed vocabulary and uses CKIP for tokenization.
"""

import json
import logging
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)

# Global encoder state
_vocabulary: Optional[Dict[str, int]] = None
_idf: Optional[Dict[str, float]] = None
_avgdl: float = 0.0
_k1: float = 1.5
_b: float = 0.75
_epsilon: float = 0.25
_initialized: bool = False

# Tokenizer state (lazy loaded)
_ws_driver = None
_tokenizer_initialized: bool = False

# Stopwords
STOPWORDS = {
    "的", "了", "是", "在", "有", "和", "與", "就", "都", "也",
    "而", "及", "或", "把", "被", "對", "給", "從", "到", "向",
    "為", "以", "於", "這", "那", "之", "所", "使", "能", "要",
    "會", "可", "將", "又", "再", "很", "更", "最", "才", "只",
    "若", "如", "若", "且", "因", "但", "卻", "乃", "便", "則",
    "他", "她", "它", "我", "你", "們", "他們", "她們", "我們", "你們",
    "這個", "那個", "什麼", "怎麼", "誰", "哪", "哪裡", "哪個",
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "百", "千", "萬", "第", "說", "來", "去", "做", "讓", "叫",
}

# Pattern to match non-Chinese characters and punctuation
_PUNCTUATION_PATTERN = re.compile(
    r'[^\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u0030-\u0039\u0041-\u005a\u0061-\u007a]+'
)


def _init_tokenizer():
    """Lazy initialization of CKIP tokenizer."""
    global _ws_driver, _tokenizer_initialized

    if _tokenizer_initialized:
        return

    try:
        from ckip_transformers.nlp import CkipWordSegmenter

        logger.info("Loading CKIP Word Segmenter for sparse encoding...")
        _ws_driver = CkipWordSegmenter(model="bert-base", device=-1)
        _tokenizer_initialized = True
        logger.info("CKIP tokenizer ready")

    except ImportError:
        logger.error(
            "CKIP Transformers not installed. "
            "Install with: pip install ckip-transformers"
        )
        raise
    except Exception as e:
        logger.error(f"Failed to initialize CKIP tokenizer: {e}")
        raise


def _tokenize(text: str) -> List[str]:
    """Tokenize text using CKIP and filter stopwords."""
    _init_tokenizer()

    result = _ws_driver([text])
    tokens = result[0] if result else []

    processed = []
    for token in tokens:
        if not token or not token.strip():
            continue
        token = _PUNCTUATION_PATTERN.sub("", token)
        if not token or len(token) < 1:
            continue
        if token in STOPWORDS:
            continue
        processed.append(token)

    return processed


def init_sparse_encoder() -> bool:
    """
    Initialize the sparse encoder by loading vocabulary and IDF values.

    Returns:
        True if initialization successful, False otherwise.
    """
    global _vocabulary, _idf, _avgdl, _k1, _b, _epsilon, _initialized

    if _initialized:
        return True

    vocab_path = Path(settings.bm25_vocabulary_path)

    if not vocab_path.exists():
        logger.warning(f"BM25 vocabulary not found at {vocab_path}")
        logger.warning("Sparse encoding will not be available")
        return False

    try:
        with open(vocab_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        _vocabulary = state["vocabulary"]
        _idf = state["idf"]
        _avgdl = state["avgdl"]
        _k1 = state.get("k1", 1.5)
        _b = state.get("b", 0.75)
        _epsilon = state.get("epsilon", 0.25)
        _initialized = True

        logger.info(
            f"Sparse encoder initialized: vocabulary size = {len(_vocabulary)}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to load BM25 vocabulary: {e}")
        return False


def encode_query(query: str) -> Tuple[List[int], List[float]]:
    """
    Encode a query into a sparse vector.

    Uses presence-based weighting with IDF scores (query mode).

    Args:
        query: The query text.

    Returns:
        Tuple of (indices, values) for the sparse vector.
    """
    if not _initialized:
        raise RuntimeError("Sparse encoder not initialized")

    tokens = _tokenize(query)

    if not tokens:
        return [], []

    # For queries, use presence-based weighting with IDF
    unique_tokens = set(tokens)
    indices = []
    values = []

    for token in unique_tokens:
        if token not in _vocabulary:
            continue

        idx = _vocabulary[token]
        idf = _idf.get(token, _epsilon)

        indices.append(idx)
        values.append(idf)

    # Sort by index
    if indices:
        sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
        indices, values = zip(*sorted_pairs)
        indices = list(indices)
        values = list(values)

    return indices, values


def is_initialized() -> bool:
    """Check if sparse encoder is initialized."""
    return _initialized


def get_vocabulary_size() -> int:
    """Get vocabulary size."""
    return len(_vocabulary) if _vocabulary else 0

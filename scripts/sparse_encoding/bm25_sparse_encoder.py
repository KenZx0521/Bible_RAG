"""
BM25-based Sparse Vector Encoder for Qdrant hybrid search.

This module implements BM25 scoring to generate sparse vectors that can be
used alongside dense vectors for hybrid retrieval in Qdrant.
"""

import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .ckip_tokenizer import CKIPTokenizer

logger = logging.getLogger(__name__)


class BM25SparseEncoder:
    """
    BM25-based sparse vector encoder for hybrid search.

    This encoder:
    1. Uses CKIP tokenizer for Chinese word segmentation
    2. Calculates BM25 weights for each token
    3. Outputs sparse vectors in Qdrant-compatible format

    BM25 Formula:
    score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))

    Where:
    - IDF(qi) = log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
    - f(qi, D) = frequency of term qi in document D
    - |D| = document length (number of tokens)
    - avgdl = average document length
    - k1, b = BM25 parameters
    """

    def __init__(
        self,
        tokenizer: Optional[CKIPTokenizer] = None,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        """
        Initialize the BM25 sparse encoder.

        Args:
            tokenizer: CKIPTokenizer instance. If None, creates a new one.
            k1: BM25 term frequency saturation parameter.
            b: BM25 document length normalization parameter.
            epsilon: Floor for IDF values to prevent negative scores.
        """
        self.tokenizer = tokenizer or CKIPTokenizer()
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon

        # Vocabulary: token -> index
        self.vocabulary: Dict[str, int] = {}

        # IDF values: token -> IDF score
        self.idf: Dict[str, float] = {}

        # Corpus statistics
        self.doc_count: int = 0
        self.avgdl: float = 0.0
        self.doc_freqs: Dict[str, int] = {}  # token -> number of documents containing it

        self._fitted = False

    def fit(
        self,
        documents: List[str],
        show_progress: bool = True,
    ) -> "BM25SparseEncoder":
        """
        Fit the encoder on a corpus of documents.

        This builds the vocabulary and calculates IDF values.

        Args:
            documents: List of document texts.
            show_progress: Whether to show progress bar.

        Returns:
            self for method chaining.
        """
        logger.info(f"Fitting BM25 encoder on {len(documents)} documents...")

        # Reset state
        self.vocabulary = {}
        self.idf = {}
        self.doc_freqs = {}
        total_length = 0
        vocab_index = 0

        # Optional progress bar
        if show_progress:
            try:
                from tqdm import tqdm
                doc_iter = tqdm(documents, desc="Building vocabulary")
            except ImportError:
                doc_iter = documents
        else:
            doc_iter = documents

        # First pass: tokenize all documents and build vocabulary
        tokenized_docs = []
        for doc in doc_iter:
            tokens = self.tokenizer.tokenize(doc, remove_stopwords=True)
            tokenized_docs.append(tokens)
            total_length += len(tokens)

            # Count document frequencies
            unique_tokens = set(tokens)
            for token in unique_tokens:
                if token not in self.vocabulary:
                    self.vocabulary[token] = vocab_index
                    vocab_index += 1
                    self.doc_freqs[token] = 0
                self.doc_freqs[token] += 1

        self.doc_count = len(documents)
        self.avgdl = total_length / self.doc_count if self.doc_count > 0 else 0

        # Calculate IDF for each token
        for token, df in self.doc_freqs.items():
            # IDF with smoothing (BM25 variant)
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1)
            # Apply epsilon floor to prevent negative values
            self.idf[token] = max(idf, self.epsilon)

        self._fitted = True
        logger.info(
            f"BM25 encoder fitted: vocabulary size = {len(self.vocabulary)}, "
            f"avgdl = {self.avgdl:.2f}"
        )

        return self

    def encode(self, text: str) -> Tuple[List[int], List[float]]:
        """
        Encode a single text into a sparse vector.

        Args:
            text: The text to encode.

        Returns:
            Tuple of (indices, values) for the sparse vector.
        """
        if not self._fitted:
            raise RuntimeError("Encoder not fitted. Call fit() first.")

        tokens = self.tokenizer.tokenize(text, remove_stopwords=True)
        return self._encode_tokens(tokens)

    def _encode_tokens(self, tokens: List[str]) -> Tuple[List[int], List[float]]:
        """
        Encode a list of tokens into a sparse vector using BM25 weights.

        Args:
            tokens: List of tokens.

        Returns:
            Tuple of (indices, values) for the sparse vector.
        """
        if not tokens:
            return [], []

        # Count term frequencies
        tf = Counter(tokens)
        doc_len = len(tokens)

        indices = []
        values = []

        for token, freq in tf.items():
            if token not in self.vocabulary:
                # Skip OOV tokens
                continue

            idx = self.vocabulary[token]
            idf = self.idf.get(token, self.epsilon)

            # BM25 score
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score = idf * (numerator / denominator)

            if score > 0:
                indices.append(idx)
                values.append(score)

        # Sort by index for consistent output
        if indices:
            sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
            indices, values = zip(*sorted_pairs)
            indices = list(indices)
            values = list(values)

        return indices, values

    def encode_batch(
        self,
        texts: List[str],
        show_progress: bool = False,
    ) -> List[Tuple[List[int], List[float]]]:
        """
        Encode a batch of texts into sparse vectors.

        Args:
            texts: List of texts to encode.
            show_progress: Whether to show progress bar.

        Returns:
            List of (indices, values) tuples.
        """
        if not self._fitted:
            raise RuntimeError("Encoder not fitted. Call fit() first.")

        # Batch tokenize for efficiency
        tokenized = self.tokenizer.tokenize_batch(texts, remove_stopwords=True)

        # Encode each
        if show_progress:
            try:
                from tqdm import tqdm
                token_iter = tqdm(tokenized, desc="Encoding sparse vectors")
            except ImportError:
                token_iter = tokenized
        else:
            token_iter = tokenized

        return [self._encode_tokens(tokens) for tokens in token_iter]

    def encode_query(self, query: str) -> Tuple[List[int], List[float]]:
        """
        Encode a query into a sparse vector.

        For queries, we use a simplified BM25 scoring:
        - TF is capped at 1 (presence/absence)
        - Only IDF weights are used

        Args:
            query: The query text.

        Returns:
            Tuple of (indices, values) for the sparse vector.
        """
        if not self._fitted:
            raise RuntimeError("Encoder not fitted. Call fit() first.")

        tokens = self.tokenizer.tokenize(query, remove_stopwords=True)

        if not tokens:
            return [], []

        # For queries, use presence-based weighting with IDF
        unique_tokens = set(tokens)
        indices = []
        values = []

        for token in unique_tokens:
            if token not in self.vocabulary:
                continue

            idx = self.vocabulary[token]
            idf = self.idf.get(token, self.epsilon)

            indices.append(idx)
            values.append(idf)

        # Sort by index
        if indices:
            sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
            indices, values = zip(*sorted_pairs)
            indices = list(indices)
            values = list(values)

        return indices, values

    def save(self, path: Union[str, Path]):
        """
        Save the encoder state to a JSON file.

        Args:
            path: Path to save the encoder state.
        """
        if not self._fitted:
            raise RuntimeError("Encoder not fitted. Nothing to save.")

        state = {
            "vocabulary": self.vocabulary,
            "idf": self.idf,
            "doc_count": self.doc_count,
            "avgdl": self.avgdl,
            "doc_freqs": self.doc_freqs,
            "k1": self.k1,
            "b": self.b,
            "epsilon": self.epsilon,
        }

        path = Path(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        logger.info(f"BM25 encoder saved to {path}")

    @classmethod
    def load(
        cls,
        path: Union[str, Path],
        tokenizer: Optional[CKIPTokenizer] = None,
    ) -> "BM25SparseEncoder":
        """
        Load an encoder from a saved state file.

        Args:
            path: Path to the saved encoder state.
            tokenizer: Optional tokenizer instance. If None, creates new one.

        Returns:
            Loaded BM25SparseEncoder instance.
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)

        encoder = cls(
            tokenizer=tokenizer,
            k1=state.get("k1", 1.5),
            b=state.get("b", 0.75),
            epsilon=state.get("epsilon", 0.25),
        )

        encoder.vocabulary = state["vocabulary"]
        encoder.idf = state["idf"]
        encoder.doc_count = state["doc_count"]
        encoder.avgdl = state["avgdl"]
        encoder.doc_freqs = state.get("doc_freqs", {})
        encoder._fitted = True

        logger.info(
            f"BM25 encoder loaded from {path}: "
            f"vocabulary size = {len(encoder.vocabulary)}"
        )

        return encoder

    def get_vocabulary_size(self) -> int:
        """Get the size of the vocabulary."""
        return len(self.vocabulary)

    def get_top_idf_terms(self, n: int = 20) -> List[Tuple[str, float]]:
        """
        Get the top N terms by IDF score.

        Args:
            n: Number of terms to return.

        Returns:
            List of (term, idf_score) tuples sorted by IDF descending.
        """
        sorted_idf = sorted(self.idf.items(), key=lambda x: x[1], reverse=True)
        return sorted_idf[:n]

    def to_qdrant_sparse_vector(
        self,
        indices: List[int],
        values: List[float],
    ) -> dict:
        """
        Convert indices and values to Qdrant SparseVector format.

        Args:
            indices: List of vocabulary indices.
            values: List of BM25 scores.

        Returns:
            Dict with 'indices' and 'values' keys for Qdrant.
        """
        return {
            "indices": indices,
            "values": values,
        }

"""Embedding service using bge-m3."""

from typing import Any

import numpy as np

from app.core.config import settings


class EmbeddingService:
    """Service for generating embeddings using bge-m3."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.EMBED_MODEL_NAME
        self.model = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the embedding model."""
        if self._initialized:
            return

        try:
            from FlagEmbedding import BGEM3FlagModel

            self.model = BGEM3FlagModel(
                self.model_name,
                use_fp16=settings.EMBED_USE_FP16,
            )
            self._initialized = True
        except ImportError:
            raise RuntimeError(
                "FlagEmbedding not installed. Run: pip install FlagEmbedding"
            )

    async def encode(
        self,
        text: str | list[str],
        return_sparse: bool = False,
    ) -> np.ndarray | dict[str, Any]:
        """Encode text to embedding(s).

        Args:
            text: Single text or list of texts to encode
            return_sparse: If True, also return sparse lexical weights

        Returns:
            Dense embedding(s) or dict with both dense and sparse if return_sparse=True
        """
        if not self._initialized:
            await self.initialize()

        if isinstance(text, str):
            text = [text]

        output = self.model.encode(
            text,
            return_dense=True,
            return_sparse=return_sparse,
            return_colbert_vecs=False,
        )

        if return_sparse:
            return {
                "dense": output["dense_vecs"],
                "sparse": output["lexical_weights"],
            }

        # Return just dense embeddings
        embeddings = output["dense_vecs"]
        if len(text) == 1:
            return embeddings[0]
        return embeddings

    async def encode_query(self, query: str) -> np.ndarray:
        """Encode a query text to embedding."""
        return await self.encode(query)

    async def encode_documents(self, documents: list[str]) -> np.ndarray:
        """Encode multiple documents to embeddings."""
        return await self.encode(documents)

    def compute_similarity(
        self,
        query_embedding: np.ndarray,
        doc_embeddings: np.ndarray,
    ) -> np.ndarray:
        """Compute cosine similarity between query and documents."""
        # Normalize embeddings
        query_norm = query_embedding / np.linalg.norm(query_embedding)
        doc_norms = doc_embeddings / np.linalg.norm(doc_embeddings, axis=1, keepdims=True)

        # Cosine similarity
        return np.dot(doc_norms, query_norm)


# Singleton instance
_embedding_service: EmbeddingService | None = None


async def get_embedding_service() -> EmbeddingService:
    """Get or create embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
        await _embedding_service.initialize()
    return _embedding_service

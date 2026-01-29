"""
BGE-M3 Embedder for Bible RAG System.
Uses sentence-transformers with BAAI/bge-m3 model.
"""

import logging
from typing import List, Optional, Union
import numpy as np

logger = logging.getLogger(__name__)


class BGEEmbedder:
    """
    BGE-M3 embedding generator using sentence-transformers.
    
    Produces 1024-dimensional dense vectors suitable for semantic search.
    """
    
    MODEL_NAME = "BAAI/bge-m3"
    EMBEDDING_DIM = 1024
    MAX_LENGTH = 8192
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        normalize: bool = True,
    ):
        """
        Initialize the BGE-M3 embedder.
        
        Args:
            model_name: Model to use (default: BAAI/bge-m3).
            device: Device to use ('cuda', 'cpu', or None for auto-detect).
            normalize: Whether to normalize embeddings to unit length.
        """
        self.model_name = model_name or self.MODEL_NAME
        self.normalize = normalize
        self.model = None
        self._device = device
        self._initialized = False
    
    def _initialize(self):
        """Lazy initialization of the model."""
        if self._initialized:
            return
        
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            
            # Auto-detect device if not specified
            if self._device is None:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            
            logger.info(f"Loading {self.model_name} on {self._device}...")
            
            self.model = SentenceTransformer(
                self.model_name,
                device=self._device,
            )
            
            self._initialized = True
            logger.info(f"Model loaded successfully. Embedding dimension: {self.EMBEDDING_DIM}")
            
        except ImportError as e:
            logger.error("sentence-transformers not installed. Install with: pip install sentence-transformers")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize model: {e}")
            raise
    
    @property
    def device(self) -> str:
        """Get the device being used."""
        self._initialize()
        return self._device
    
    def encode(
        self,
        text: str,
        show_progress: bool = False,
    ) -> List[float]:
        """
        Encode a single text into an embedding vector.
        
        Args:
            text: Text to encode.
            show_progress: Whether to show progress bar.
            
        Returns:
            List of floats representing the embedding (1024 dimensions).
        """
        self._initialize()
        
        embedding = self.model.encode(
            text,
            normalize_embeddings=self.normalize,
            show_progress_bar=show_progress,
        )
        
        return embedding.tolist()
    
    def encode_batch(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = True,
    ) -> List[List[float]]:
        """
        Encode multiple texts into embedding vectors.
        
        Args:
            texts: List of texts to encode.
            batch_size: Batch size for encoding.
            show_progress: Whether to show progress bar.
            
        Returns:
            List of embeddings, each a list of 1024 floats.
        """
        self._initialize()
        
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=show_progress,
        )
        
        return embeddings.tolist()
    
    def get_embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return self.EMBEDDING_DIM


def test_embedder():
    """Quick test of the embedder."""
    embedder = BGEEmbedder()
    
    # Test single encoding
    text = "起初，上帝創造天地。"
    embedding = embedder.encode(text)
    
    print(f"Input: {text}")
    print(f"Embedding dimension: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")
    print(f"Device: {embedder.device}")
    
    # Test batch encoding
    texts = [
        "起初，上帝創造天地。",
        "神愛世人，甚至將他的獨生子賜給他們。",
        "你們要彼此相愛，像我愛你們一樣。",
    ]
    embeddings = embedder.encode_batch(texts, show_progress=False)
    print(f"\nBatch encoding: {len(embeddings)} texts encoded")
    
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_embedder()

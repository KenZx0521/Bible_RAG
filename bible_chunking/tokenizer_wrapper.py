"""
Tokenizer Wrapper for BGE-M3

Provides a simple interface for counting tokens using the BGE-M3 tokenizer.
"""

from typing import Optional
from functools import lru_cache

from .config import TOKEN_CONFIG


class TokenizerWrapper:
    """Wrapper for BGE-M3 tokenizer with caching."""

    _instance: Optional["TokenizerWrapper"] = None
    _tokenizer = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._tokenizer is None:
            self._load_tokenizer()

    def _load_tokenizer(self):
        """Load the tokenizer lazily."""
        try:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                TOKEN_CONFIG["model_name"], trust_remote_code=True
            )
        except ImportError:
            raise ImportError(
                "transformers package is required. Install with: pip install transformers"
            )
        except Exception as e:
            # Fallback to a simple character-based estimation
            print(f"Warning: Could not load tokenizer ({e}). Using fallback estimation.")
            self._tokenizer = None

    @lru_cache(maxsize=10000)
    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in a text string.

        Uses caching to avoid repeated tokenization of the same text.
        """
        if not text:
            return 0

        if self._tokenizer is not None:
            # Use actual tokenizer
            tokens = self._tokenizer.encode(text, add_special_tokens=False)
            return len(tokens)
        else:
            # Fallback: estimate based on characters
            # For Chinese text, roughly 1.5 characters per token
            return int(len(text) / 1.5)

    def tokenize(self, text: str):
        """Tokenize text and return token IDs."""
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not available")
        return self._tokenizer.encode(text, add_special_tokens=False)

    def decode(self, token_ids) -> str:
        """Decode token IDs back to text."""
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not available")
        return self._tokenizer.decode(token_ids)


# Singleton instance
_tokenizer: Optional[TokenizerWrapper] = None


def get_tokenizer() -> TokenizerWrapper:
    """Get the singleton tokenizer instance."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = TokenizerWrapper()
    return _tokenizer


def count_tokens(text: str) -> int:
    """Convenience function to count tokens in text."""
    return get_tokenizer().count_tokens(text)

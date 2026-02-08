"""
LLM client abstraction layer.
Supports Ollama, Claude, OpenAI, and Gemini providers.
"""

from .base import LLMClient
from .factory import get_llm_client

__all__ = ["LLMClient", "get_llm_client"]

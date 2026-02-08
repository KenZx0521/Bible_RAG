"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Unified interface for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        """Send chat messages and return the assistant's reply text."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and the model is available."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider + model identifier, e.g. 'Ollama (gemma3:4b)'."""

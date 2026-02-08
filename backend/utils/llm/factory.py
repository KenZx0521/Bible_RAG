"""Factory for creating LLM client instances."""

from .base import LLMClient

_instance: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return a singleton LLM client based on settings.llm_provider."""
    global _instance
    if _instance is not None:
        return _instance

    from config import settings

    provider = settings.llm_provider.lower()

    if provider == "ollama":
        from .ollama_client import OllamaClient
        _instance = OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )
    elif provider == "claude":
        from .claude_client import ClaudeClient
        _instance = ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )
    elif provider == "openai":
        from .openai_client import OpenAIClient
        _instance = OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    elif provider == "gemini":
        from .gemini_client import GeminiClient
        _instance = GeminiClient(
            api_key=settings.google_api_key,
            model=settings.gemini_model,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. "
                         f"Choose from: ollama, claude, openai, gemini")

    return _instance

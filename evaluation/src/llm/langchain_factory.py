"""
LangChain ChatModel factory for RAGAS evaluation.
Creates the appropriate ChatModel based on eval_llm_provider setting.
"""

from __future__ import annotations

import logging

from ..config import settings

logger = logging.getLogger(__name__)


def create_langchain_llm():
    """Create a LangChain ChatModel for the configured eval LLM provider."""
    provider = settings.eval_llm_provider.lower()

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic

        logger.info("[LangChain] Creating ChatAnthropic model=%s", settings.eval_claude_model)
        return ChatAnthropic(
            model=settings.eval_claude_model,
            anthropic_api_key=settings.anthropic_api_key,
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        logger.info("[LangChain] Creating ChatOpenAI model=%s", settings.eval_openai_model)
        return ChatOpenAI(
            model=settings.eval_openai_model,
            api_key=settings.openai_api_key,
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
        )

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        logger.info("[LangChain] Creating ChatGoogleGenerativeAI model=%s", settings.eval_gemini_model)
        return ChatGoogleGenerativeAI(
            model=settings.eval_gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0.0,
            max_output_tokens=settings.llm_max_tokens,
        )

    elif provider == "ollama":
        from langchain_ollama import ChatOllama

        logger.info("[LangChain] Creating ChatOllama model=%s", settings.eval_ollama_model)
        return ChatOllama(
            model=settings.eval_ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0.0,
            num_predict=1024,
            num_ctx=8192,
            format="json",
            keep_alive="60m",
        )

    else:
        raise ValueError(f"Unknown eval LLM provider: {provider!r}. "
                         f"Choose from: claude, openai, gemini, ollama")

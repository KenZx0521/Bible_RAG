"""
Unified LLM completion for evaluation judge tasks.
Supports Claude, OpenAI, Gemini, and Ollama providers.
"""

from __future__ import annotations

import logging
import time

from ..config import settings

logger = logging.getLogger(__name__)


async def judge_completion(
    prompt: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> str:
    """
    Send a single prompt to the configured eval LLM provider and return the response text.
    """
    provider = settings.eval_llm_provider.lower()

    if provider == "claude":
        return await _claude_completion(prompt, max_tokens, temperature)
    elif provider == "openai":
        return await _openai_completion(prompt, max_tokens, temperature)
    elif provider == "gemini":
        return await _gemini_completion(prompt, max_tokens, temperature)
    elif provider == "ollama":
        return await _ollama_completion(prompt, max_tokens, temperature)
    else:
        raise ValueError(f"Unknown eval LLM provider: {provider!r}. "
                         f"Choose from: claude, openai, gemini, ollama")


async def _claude_completion(prompt: str, max_tokens: int, temperature: float) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    logger.info("[Claude API] POST messages  model=%s", settings.eval_claude_model)
    t0 = time.perf_counter()

    raw_resp = await client.messages.with_raw_response.create(
        model=settings.eval_claude_model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.perf_counter() - t0
    resp = raw_resp.parse()
    text = resp.content[0].text.strip()

    logger.info("[Claude API] %d  %.2fs  usage: in=%d out=%d",
                raw_resp.status_code, elapsed,
                resp.usage.input_tokens, resp.usage.output_tokens)
    return text


async def _openai_completion(prompt: str, max_tokens: int, temperature: float) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    logger.info("[OpenAI API] POST completions  model=%s", settings.eval_openai_model)
    t0 = time.perf_counter()

    resp = await client.chat.completions.create(
        model=settings.eval_openai_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    elapsed = time.perf_counter() - t0
    text = resp.choices[0].message.content or ""

    logger.info("[OpenAI API] %.2fs  usage: in=%d out=%d",
                elapsed,
                resp.usage.prompt_tokens if resp.usage else 0,
                resp.usage.completion_tokens if resp.usage else 0)
    return text.strip()


async def _gemini_completion(prompt: str, max_tokens: int, temperature: float) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.google_api_key)
    logger.info("[Gemini API] POST generate  model=%s", settings.eval_gemini_model)
    t0 = time.perf_counter()

    resp = await client.aio.models.generate_content(
        model=settings.eval_gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    elapsed = time.perf_counter() - t0
    text = resp.text or ""

    logger.info("[Gemini API] %.2fs", elapsed)
    return text.strip()


async def _ollama_completion(prompt: str, max_tokens: int, temperature: float) -> str:
    import httpx

    logger.info("[Ollama API] POST generate  model=%s", settings.eval_ollama_model)
    t0 = time.perf_counter()

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.eval_ollama_model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
        )
        resp.raise_for_status()
        elapsed = time.perf_counter() - t0
        text = resp.json().get("response", "")

    logger.info("[Ollama API] %.2fs", elapsed)
    return text.strip()

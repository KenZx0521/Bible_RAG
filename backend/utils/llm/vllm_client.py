"""vLLM LLM client using httpx (the OpenAI-compatible /v1/chat/completions).

Asks for gemma4's thinking on every request: Ollama 0.32 thinks by default for
gemma4, and ``max_tokens`` covers the thought and the answer alike, as Ollama's
``num_predict`` did. The server's gemma4 reasoning parser keeps the thought out
of ``content``. vLLM decodes with the HF tokenizer, so gemma4's byte tokens come
back as text (no ``<0xNN>`` runs to merge, unlike Ollama's GGUF).
"""

import httpx

from .base import LLMClient


class VLLMClient(LLMClient):
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return f"vLLM ({self._model})"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "chat_template_kwargs": {"enable_thinking": True},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # content is null when the thought used up max_tokens
            return data["choices"][0]["message"].get("content") or ""

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/v1/models")
                resp.raise_for_status()
                return any(m.get("id") == self._model for m in resp.json().get("data", []))
        except Exception:
            return False

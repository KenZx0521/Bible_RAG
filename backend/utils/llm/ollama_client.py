"""Ollama LLM client using httpx.

gemma4's 256 byte tokens are typed NORMAL in its GGUF, so Ollama prints them
literally (``<0xE7><0xA5><0x9E>`` for 神); chat() joins each such run back into
its UTF-8 text (a stopgap: the fixed model blob would change the generator digest).
"""

import re

import httpx

from .base import LLMClient

_BYTE_RUN = re.compile(r"(?:<0x[0-9A-Fa-f]{2}>)+")


def merge_byte_tokens(text: str) -> str:
    """Decode every run of literal ``<0xNN>`` tokens as UTF-8 (invalid bytes become U+FFFD)."""
    return _BYTE_RUN.sub(
        lambda m: bytes(int(t, 16) for t in re.findall(r"<0x([0-9A-Fa-f]{2})>", m.group(0)))
        .decode("utf-8", errors="replace"), text)


class OllamaClient(LLMClient):
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return f"Ollama ({self._model})"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return merge_byte_tokens(data.get("message", {}).get("content", ""))

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                model_base = self._model.split(":")[0]
                return any(model_base in m for m in models)
        except Exception:
            return False

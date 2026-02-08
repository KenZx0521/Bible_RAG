"""OpenAI LLM client."""

from openai import AsyncOpenAI

from .base import LLMClient


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return f"OpenAI ({self._model})"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def health_check(self) -> bool:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=10,
            )
            return bool(resp.choices)
        except Exception:
            return False

"""Google Gemini LLM client using google-genai SDK."""

from google import genai
from google.genai import types

from .base import LLMClient


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self._model = model
        self._client = genai.Client(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return f"Gemini ({self._model})"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> str:
        # Convert OpenAI-style messages to Gemini format
        system_text = ""
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])],
                ))

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_text:
            config.system_instruction = system_text

        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )
        return resp.text or ""

    async def health_check(self) -> bool:
        try:
            resp = await self._client.aio.models.generate_content(
                model=self._model,
                contents="hi",
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
            return bool(resp.text)
        except Exception:
            return False

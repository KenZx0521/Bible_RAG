"""Ollama LLM client service."""

from ollama import AsyncClient

from app.core.config import settings


class OllamaLLMClient:
    """Async client for Ollama LLM."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.LLM_MODEL_NAME
        self.client = AsyncClient(host=self.base_url)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text response from prompt.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (default from settings)
            max_tokens: Max tokens to generate (default from settings)

        Returns:
            Generated text
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat(
            model=self.model,
            messages=messages,
            options={
                "temperature": temperature or settings.LLM_TEMPERATURE,
                "num_predict": max_tokens or settings.LLM_MAX_TOKENS,
            },
        )

        return response["message"]["content"]

    async def classify_query(self, query: str) -> str:
        """Classify a query into predefined types.

        Args:
            query: User query text

        Returns:
            Query type string
        """
        system_prompt = """你是一個聖經問題分類器。根據用戶的問題，將其分類為以下類型之一：

- VERSE_LOOKUP: 用戶想查詢特定經文（包含書卷名、章節號）
- TOPIC_QUESTION: 用戶詢問關於某個主題或概念（如饒恕、信心、愛）
- PERSON_QUESTION: 用戶詢問關於某個人物（如亞伯拉罕、保羅、耶穌）
- EVENT_QUESTION: 用戶詢問關於某個事件（如出埃及、復活、五旬節）
- GENERAL_BIBLE_QUESTION: 其他一般性的聖經問題

只回答分類類型，不要有其他文字。"""

        response = await self.generate(
            prompt=f"請分類這個問題：{query}",
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=50,
        )

        # Parse response
        response = response.strip().upper()

        valid_types = [
            "VERSE_LOOKUP",
            "TOPIC_QUESTION",
            "PERSON_QUESTION",
            "EVENT_QUESTION",
            "GENERAL_BIBLE_QUESTION",
        ]

        for query_type in valid_types:
            if query_type in response:
                return query_type

        return "GENERAL_BIBLE_QUESTION"

    async def generate_answer(
        self,
        query: str,
        context: str,
        query_type: str,
    ) -> str:
        """Generate answer based on query and context.

        Args:
            query: User query
            context: Retrieved context (formatted pericopes)
            query_type: Classified query type

        Returns:
            Generated answer in markdown
        """
        system_prompt = """你是一個專業的聖經知識助手。請根據提供的聖經經文內容回答用戶的問題。

回答指南：
1. 只使用提供的經文內容作為主要依據
2. 使用繁體中文回答
3. 清楚標出引用的經文卷章節（例如：馬太福音 5:7）
4. 回答應該簡潔明瞭，但足夠完整
5. 避免給出與聖經無關的個人意見
6. 使用 Markdown 格式組織回答

回答格式：
## 摘要
（簡短回答問題的核心）

## 相關經文
（列出最相關的經文及其解釋）

## 結論
（總結要點）"""

        prompt = f"""問題類型：{query_type}

用戶問題：{query}

參考經文：
{context}

請根據以上經文回答用戶的問題。"""

        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )


# Singleton instance
_llm_client: OllamaLLMClient | None = None


async def get_llm_client() -> OllamaLLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = OllamaLLMClient()
    return _llm_client

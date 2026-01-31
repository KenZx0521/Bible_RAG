"""
Answer generator using gemma3:4b via Ollama REST API.
Constructs context prompt from retrieved passages and generates response.
"""

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位精通聖經的助手，專門回答聖經相關問題。
請根據提供的經文內容來回答問題。回答時請：
1. 直接引用相關經文段落
2. 提供清楚的解釋
3. 如果提供的經文不足以完整回答，請說明
4. 回答使用繁體中文"""

CONTEXT_TEMPLATE = """以下是相關經文段落：

{context}

---

請根據以上經文回答以下問題：
{question}"""


def _build_context(sources: list[dict]) -> str:
    """Build context string from retrieved sources."""
    parts = []
    for i, src in enumerate(sources, 1):
        book = src.get("book_name", "")
        chapter = src.get("chapter_num", "")
        title = src.get("title", "")
        verse_range = src.get("verse_range", "")
        content = src.get("content", "")

        header = f"[{i}] {book} 第{chapter}章"
        if title:
            header += f" - {title}"
        if verse_range:
            header += f" ({verse_range}節)"

        parts.append(f"{header}\n{content}")

    return "\n\n".join(parts)


async def generate_answer(question: str, sources: list[dict]) -> str:
    """
    Generate an answer using gemma3:4b via Ollama API.

    Args:
        question: User's question.
        sources: Top-k retrieved and reranked passages.

    Returns:
        Generated answer text.
    """
    if not sources:
        return "找不到相關的經文內容來回答這個問題。"

    context = _build_context(sources)
    prompt = CONTEXT_TEMPLATE.format(context=context, question=question)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 1024,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "生成回答時發生錯誤。")

    except httpx.TimeoutException:
        logger.error("Ollama request timed out")
        return "回答生成超時，請稍後再試。"
    except Exception as e:
        logger.error(f"Ollama generation failed: {e}")
        return f"生成回答時發生錯誤：{e}"


async def check_ollama() -> bool:
    """Check if Ollama is accessible and the model is available."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            model_base = settings.ollama_model.split(":")[0]
            return any(model_base in m for m in models)
    except Exception:
        return False

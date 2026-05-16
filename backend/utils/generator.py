"""
Answer generator using the configured LLM provider.
Constructs context prompt from retrieved passages and generates response.
"""

import logging

from config import settings
from utils.llm import get_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」中的資訊來回答，禁止使用經文以外的任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）
3. 將相關經文內容整理成連貫的回答
4. 不要加入經文中沒有提到的推論、解讀或額外資訊
5. 回答使用繁體中文"""

CONTEXT_TEMPLATE = """以下是提供的經文段落（你只能使用這些內容來回答）：

{context}

---

嚴格根據以上經文段落的內容，回答以下問題。不要添加經文中沒有的資訊：
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
    Generate an answer using the configured LLM provider.

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
        llm = get_llm_client()
        answer = await llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        return answer or "生成回答時發生錯誤。"

    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return f"生成回答時發生錯誤：{e}"

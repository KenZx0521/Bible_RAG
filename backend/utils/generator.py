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

# With a chronology card (utils.regnal): experiment A's prompt (cards_common.py), byte for
# byte; the blind confirmation set measured exactly this. Rule 1 widened to the auxiliary
# block, which follows the passages, and the answer ends in one 「答案：」 line.
SYSTEM_PROMPT_AUX = """你是一位聖經問答助手。你必須嚴格遵守以下規則：

規則：
1. 只能使用「提供的經文段落」與「輔助資料」中的資訊來回答，禁止使用其他任何知識
2. 回答時必須引用具體的經文出處（書卷、章節）
3. 將相關經文內容整理成連貫的回答
4. 不要加入提供內容中沒有提到的推論、解讀或額外資訊
5. 回答使用繁體中文"""

AUX_LABEL = "以下是輔助資料（依經文整理）："
ANSWER_INSTRUCTION = "請先逐步列出推理，最後一行只寫「答案：」加上答案。"

CONTEXT_TEMPLATE_AUX = """以下是提供的經文段落（你只能使用這些內容來回答）：

{context}
{aux}
---

嚴格根據以上經文段落{aux_ref}的內容，回答以下問題。不要添加提供內容中沒有的資訊。{instruction}
{question}"""


def build_context_blocks(sources: list[dict]) -> list[str]:
    """
    One context block per retrieved source: ``[i] 書卷 第N章 - 標題 (節)`` + text.

    The evaluation judge must see exactly these blocks (returned via
    ``include_context``); keep the format in sync with
    ``evaluation/src/context_blocks.py``.
    """
    blocks = []
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

        blocks.append(f"{header}\n{content}")

    return blocks


def _build_context(sources: list[dict]) -> str:
    """Build context string from retrieved sources."""
    return "\n\n".join(build_context_blocks(sources))


# the passages as the generator (and the chronology card's seed call) read them
build_context = _build_context


def build_messages(question: str, context: str, aux_block: str | None = None) -> list[dict]:
    """The generator's messages; without ``aux_block`` they are the ordinary prompt."""
    if not aux_block:
        return [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": CONTEXT_TEMPLATE.format(context=context, question=question)}]
    user = CONTEXT_TEMPLATE_AUX.format(context=context, aux=f"\n{AUX_LABEL}\n{aux_block}\n",
                                       aux_ref="與輔助資料", instruction=ANSWER_INSTRUCTION,
                                       question=question)
    return [{"role": "system", "content": SYSTEM_PROMPT_AUX}, {"role": "user", "content": user}]


async def generate_answer(question: str, sources: list[dict], aux_block: str | None = None) -> str:
    """
    Generate an answer using the configured LLM provider.

    Args:
        question: User's question.
        sources: Top-k retrieved and reranked passages.
        aux_block: A chronology card (utils.regnal) to answer with, or None.

    Returns:
        Generated answer text.
    """
    if not sources:
        return "找不到相關的經文內容來回答這個問題。"

    try:
        llm = get_llm_client()
        answer = await llm.chat(
            messages=build_messages(question, _build_context(sources), aux_block),
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        return answer or "生成回答時發生錯誤。"

    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return f"生成回答時發生錯誤：{e}"

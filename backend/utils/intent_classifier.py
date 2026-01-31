"""
Intent classifier using gemma3:4b via Ollama.
Hybrid approach: regex for verse refs + LLM for semantic intent.
"""

import json
import logging

import httpx

from config import settings
from utils.verse_parser import parse_verse_references, VerseRef

logger = logging.getLogger(__name__)

INTENT_TYPES = ["verse_lookup", "topic", "person", "event", "cross_reference"]

CLASSIFICATION_PROMPT = """你是一個聖經問題分類器。根據使用者的問題，回傳 JSON 格式的分類結果。

分類類型:
- verse_lookup: 查詢特定經文內容（包含明確經文引用）
- topic: 查詢聖經主題、教義、概念
- person: 查詢聖經人物相關資訊
- event: 查詢聖經事件
- cross_reference: 涉及不同書卷間的對照、引用、預表

請回傳以下 JSON 格式（不要包含其他文字）:
{
  "intent": "類型",
  "entities": ["相關人名/地名/事件名"],
  "keywords": ["關鍵詞"]
}

範例:
問題: "保羅歸主的經過為何？"
{"intent": "event", "entities": ["保羅"], "keywords": ["歸主", "經過"]}

問題: "摩西與葉忒羅的關係如何影響以色列人的治理？"
{"intent": "person", "entities": ["摩西", "葉忒羅", "以色列人"], "keywords": ["關係", "治理"]}

問題: "彼得前書如何引用以賽亞書論房角石？"
{"intent": "cross_reference", "entities": ["彼得前書", "以賽亞書"], "keywords": ["引用", "房角石"]}

問題: "根據創世記第1章，神如何按次序創造天地萬物？"
{"intent": "topic", "entities": [], "keywords": ["創造", "次序", "天地萬物"]}

問題: "根據羅馬書3:23-24，保羅如何描述世人的光景和神的救贖？"
{"intent": "verse_lookup", "entities": ["保羅"], "keywords": ["世人", "光景", "救贖"]}

現在分類這個問題:
"""


async def classify_intent(question: str) -> dict:
    """
    Classify the user's question intent.

    Hybrid approach:
    1. Regex detection for verse references
    2. LLM classification for semantic intent

    Returns:
        {
            "type": str,  # one of INTENT_TYPES
            "entities": list[str],
            "keywords": list[str],
            "verse_refs": list[VerseRef]
        }
    """
    # Step 1: Detect verse references
    verse_refs = parse_verse_references(question)

    # Step 2: LLM classification
    intent_type = "topic"  # default
    entities: list[str] = []
    keywords: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": CLASSIFICATION_PROMPT + f'問題: "{question}"',
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 256,
                    },
                },
            )
            resp.raise_for_status()
            response_text = resp.json().get("response", "")

            # Parse JSON from response
            parsed = _extract_json(response_text)
            if parsed:
                raw_intent = parsed.get("intent", "topic")
                if raw_intent in INTENT_TYPES:
                    intent_type = raw_intent
                entities = parsed.get("entities", [])
                keywords = parsed.get("keywords", [])

    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}")
        # Fallback: if verse refs detected, it's verse_lookup
        if verse_refs:
            intent_type = "verse_lookup"

    # Override: if verse refs detected but LLM didn't say verse_lookup, keep both
    if verse_refs and intent_type not in ("verse_lookup", "cross_reference"):
        intent_type = "verse_lookup"

    return {
        "type": intent_type,
        "entities": entities,
        "keywords": keywords,
        "verse_refs": verse_refs,
    }


def _extract_json(text: str) -> dict | None:
    """Extract first JSON object from text."""
    # Try direct parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None

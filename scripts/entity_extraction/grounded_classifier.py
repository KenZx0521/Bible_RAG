"""
Phase 4: LLM-as-Classifier (grounded).

The LLM does NOT generate entities — it classifies pre-extracted candidates
into Event/Object/Theme, citing evidence from the original text.
"""

import json
import logging
import time
from typing import List, Dict, Optional

from .models import EntityCandidate, EntityType
from .config import EntityExtractLLMConfig
from .llm_extractor import BaseLLMClient, create_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是聖經文本分析專家。你的任務是對已從聖經原文中提取的候選詞進行分類。

分類規則：
- Event (事件)：聖經中的具體事件（如：出埃及、洪水、耶穌受洗）
- Object (物件)：聖經中的具體物件或儀式用品（如：約櫃、會幕、法版）
- Theme (主題)：神學主題或抽象概念（如：救贖、恩典、信心）
- None：無法確定分類

重要限制：
1. 你只能分類已提供的候選詞，絕對不可新增任何詞彙
2. 每個分類必須引用經文原文中的句子作為 evidence
3. 如果不確定，分類為 null

回應格式（JSON）：
```json
{
  "classifications": [
    {
      "name": "候選詞名稱",
      "type": "Event|Object|Theme",
      "evidence": "經文原文中包含此詞的句子"
    }
  ]
}
```

如果某候選詞無法分類：
```json
{"name": "候選詞", "type": null, "evidence": ""}
```"""

USER_PROMPT_TEMPLATE = """請對以下候選詞進行分類。

經文原文：
{text}

候選詞列表：
{candidates}

請以 JSON 格式回應，只分類以上候選詞。"""


class GroundedClassifier:
    """LLM-as-Classifier for grounded entity classification."""

    def __init__(self, config: Optional[EntityExtractLLMConfig] = None):
        if config is None:
            config = EntityExtractLLMConfig.from_env()
        self.config = config
        self.client: BaseLLMClient = create_llm_client(config)

    def classify_batch(
        self,
        candidates: List[EntityCandidate],
        batch_size: int = 10,
    ) -> List[EntityCandidate]:
        """
        Classify candidates via LLM in batches grouped by source pericope.

        Post-processing validates that evidence actually exists in grounding_text.
        """
        # Group candidates by their first source_id for batching
        source_groups: Dict[str, List[EntityCandidate]] = {}
        for c in candidates:
            key = c.source_ids[0] if c.source_ids else "unknown"
            source_groups.setdefault(key, []).append(c)

        classified: List[EntityCandidate] = []

        # Flatten all batches for progress tracking
        all_batches = []
        for source_id, group in source_groups.items():
            for i in range(0, len(group), batch_size):
                all_batches.append(group[i : i + batch_size])

        try:
            from tqdm import tqdm
            batch_iter = tqdm(
                all_batches,
                desc="Phase 4 LLM Classification",
                unit="batch",
            )
        except ImportError:
            batch_iter = all_batches

        for batch in batch_iter:
            results = self._classify_group(batch)
            classified.extend(results)

        logger.info(f"Phase 4: classified {len(classified)} candidates via LLM")
        return classified

    def _classify_group(
        self,
        candidates: List[EntityCandidate],
    ) -> List[EntityCandidate]:
        """Classify a group of candidates sharing similar context."""
        # Build context text from grounding
        context_parts = []
        for c in candidates:
            if c.grounding_text:
                context_parts.append(c.grounding_text)
        context_text = "\n".join(set(context_parts))[:3000]  # limit context

        candidate_names = ", ".join(c.name for c in candidates)

        user_prompt = USER_PROMPT_TEMPLATE.format(
            text=context_text,
            candidates=candidate_names,
        )

        # Call LLM with retry
        raw = self._call_with_retry(user_prompt)
        if raw is None:
            return candidates  # return unchanged on failure

        # Parse and apply classifications
        return self._apply_classifications(candidates, raw, context_text)

    def _call_with_retry(self, user_prompt: str) -> Optional[Dict]:
        for attempt in range(self.config.max_retries):
            try:
                content = self.client.call(SYSTEM_PROMPT, user_prompt)
                parsed = self._parse_json(content)
                if parsed is not None:
                    return parsed
                logger.warning(
                    f"LLM returned unparseable response (attempt {attempt + 1}/{self.config.max_retries}), "
                    f"raw content (first 500 chars): {repr(content[:500]) if content else '<empty>'}"
                )
            except Exception as e:
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{self.config.max_retries}): {e}"
                )
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay * (attempt + 1))
        return None

    def _parse_json(self, content: str) -> Optional[Dict]:
        if not content or not content.strip():
            logger.warning(f"LLM returned empty response, raw repr: {repr(content)}")
            return None
        try:
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                if end > start:
                    content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                if end > start:
                    content = content[start:end].strip()
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON: {e}")
            return None

    def _apply_classifications(
        self,
        candidates: List[EntityCandidate],
        result: Dict,
        context_text: str,
    ) -> List[EntityCandidate]:
        """Apply LLM classifications with evidence validation."""
        # Build lookup
        by_name = {c.name: c for c in candidates}
        classifications = result.get("classifications", [])

        for item in classifications:
            name = item.get("name", "").strip()
            type_str = item.get("type")
            evidence = item.get("evidence", "").strip()

            if name not in by_name:
                continue  # LLM hallucinated a name

            c = by_name[name]

            # Validate type
            if type_str is None or type_str == "null":
                c.extraction_phase = 4
                continue

            try:
                entity_type = EntityType(type_str)
            except ValueError:
                continue

            if entity_type not in {EntityType.EVENT, EntityType.OBJECT, EntityType.THEME}:
                continue

            # Validate evidence exists in original text
            if evidence and evidence not in context_text:
                logger.debug(
                    f"Evidence not found in text for '{name}', "
                    f"downgrading to None"
                )
                c.extraction_phase = 4
                c.confidence = 0.0
                continue

            c.proposed_type = entity_type
            c.confidence = 0.75
            c.extraction_phase = 4
            c.evidence = evidence

        return candidates

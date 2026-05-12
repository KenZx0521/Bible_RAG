"""Phase R4 — Grounded LLM classifier for relation extraction.

For each pair the LLM is given the grounding text and a CLOSED set of
candidate relation names matching the (head_type, tail_type). It must pick
exactly one or NONE. Output relation must be in the candidate set; evidence
must be a substring of the grounding text. Both checks are enforced post-hoc.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import httpx

from .config import RELLMConfig
from .models import ExtractedRelation, ExtractionPhase, RelationCandidate
from .schema_loader import RelationSchema

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是聖經敘事關係抽取器。你的工作是判斷給定的兩個實體在指定上下文中是否存在某種預定義關係。

嚴格規則:
1. 你**只能**從題目所列的候選關係中選擇,不可發明新名稱。
2. 若上下文中沒有清楚證據支持任何候選關係,必須選擇 NONE。
3. evidence 必須是上下文中的**原文片段**,不可改寫或概括。
4. 不確定就選 NONE,寧可漏抽也不可亂選。

輸出格式 (JSON, 不加 markdown):
{
  "items": [
    {"pair_index": 0, "relation": "FATHER_OF", "evidence": "亞伯拉罕生以撒"},
    {"pair_index": 1, "relation": "NONE", "evidence": ""}
  ]
}"""


USER_PROMPT_TEMPLATE = """請依下列上下文判斷每個候選對的關係。

上下文:
\"\"\"{context}\"\"\"

候選對:
{pairs}

針對每個 pair_index,回傳 relation (從候選列表選一個或填 NONE) 與 evidence (上下文原文)。
"""


@dataclass
class _PromptPair:
    candidate: RelationCandidate
    candidate_relation_names: list[str]


class GroundedREClassifier:
    def __init__(self, config: RELLMConfig):
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=httpx.Timeout(180.0, connect=15.0, read=180.0, write=15.0),
        )
        self._last_request_ts = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def classify_batch(
        self,
        candidates: list[RelationCandidate],
        schema: RelationSchema,
    ) -> list[ExtractedRelation]:
        if not candidates:
            return []

        by_pericope: dict[str, list[RelationCandidate]] = {}
        for c in candidates:
            by_pericope.setdefault(c.source_pericope_id, []).append(c)

        results: list[ExtractedRelation] = []
        for _pericope_id, group in by_pericope.items():
            for batch in _chunk(group, self.config.batch_size):
                prompt_pairs = self._build_prompt_pairs(batch, schema)
                if not prompt_pairs:
                    continue
                triples = self._classify_one_prompt(prompt_pairs, schema)
                results.extend(triples)
        return results

    def _build_prompt_pairs(
        self,
        batch: list[RelationCandidate],
        schema: RelationSchema,
    ) -> list[_PromptPair]:
        pairs: list[_PromptPair] = []
        for cand in batch:
            forward = schema.candidates_for(cand.head_type, cand.tail_type)
            reverse = [
                e for e in schema.candidates_for(cand.tail_type, cand.head_type)
                if e not in forward
            ]
            allowed: list[str] = [e.name for e in forward + reverse]
            if not allowed:
                continue
            pairs.append(_PromptPair(candidate=cand, candidate_relation_names=allowed))
        return pairs

    def _classify_one_prompt(
        self,
        prompt_pairs: list[_PromptPair],
        schema: RelationSchema,
    ) -> list[ExtractedRelation]:
        context = prompt_pairs[0].candidate.grounding_text
        pair_lines = []
        for idx, pp in enumerate(prompt_pairs):
            head_label = f"{pp.candidate.head_canonical}({pp.candidate.head_type})"
            tail_label = f"{pp.candidate.tail_canonical}({pp.candidate.tail_type})"
            cand_pool = ", ".join(pp.candidate_relation_names + ["NONE"])
            pair_lines.append(
                f"{idx}. head={head_label}, tail={tail_label}, candidates=[{cand_pool}]"
            )

        user_prompt = USER_PROMPT_TEMPLATE.format(
            context=context,
            pairs="\n".join(pair_lines),
        )

        data = self._call_with_retry(user_prompt)
        if data is None:
            return []

        return self._parse_response(data, prompt_pairs, context, schema)

    def _call_with_retry(self, user_prompt: str) -> Optional[dict]:
        for attempt in range(self.config.max_retries):
            content: str = ""
            try:
                self._rate_limit()
                response = self._client.post(
                    "/api/chat",
                    json={
                        "model": self.config.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        # Models like gemma4:*-it advertise a `thinking` capability
                        # that routes reasoning tokens into message.thinking and
                        # leaves message.content empty until the model finishes
                        # thinking. For closed-set RE this reasoning is unnecessary
                        # and exhausts num_predict, returning empty content.
                        "think": False,
                        # Grammar-constrained JSON decoding — Ollama guarantees the
                        # output terminates as valid JSON, eliminating mid-string
                        # truncation when num_predict is hit.
                        "format": "json",
                        "options": {
                            "temperature": self.config.temperature,
                            "num_ctx": self.config.num_ctx,
                            "num_predict": self.config.max_tokens,
                        },
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload.get("message", {}).get("content", "")
                if not content:
                    raise ValueError("empty response content")
                return _coerce_json(content)
            except json.JSONDecodeError as e:
                logger.warning(
                    "RE LLM JSON parse failed (attempt %d/%d): %s | len=%d | head=%r",
                    attempt + 1, self.config.max_retries, e, len(content), content[:200],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "RE LLM call failed (attempt %d/%d): %s",
                    attempt + 1, self.config.max_retries, e,
                )
            if attempt < self.config.max_retries - 1:
                time.sleep(self.config.retry_delay * (attempt + 1))
        return None

    def _rate_limit(self) -> None:
        if self.config.rate_limit_delay <= 0:
            return
        elapsed = time.time() - self._last_request_ts
        if elapsed < self.config.rate_limit_delay:
            time.sleep(self.config.rate_limit_delay - elapsed)
        self._last_request_ts = time.time()

    def _parse_response(
        self,
        data: dict,
        prompt_pairs: list[_PromptPair],
        context: str,
        schema: RelationSchema,
    ) -> list[ExtractedRelation]:
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []

        results: list[ExtractedRelation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("pair_index", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(prompt_pairs):
                continue

            pp = prompt_pairs[idx]
            relation = (item.get("relation") or "NONE").strip().upper()
            evidence = (item.get("evidence") or "").strip()

            if relation == "NONE" or not relation:
                continue
            if relation not in pp.candidate_relation_names:
                logger.debug(
                    "RE LLM proposed out-of-set relation %s for pair %s — discarded",
                    relation, pp.candidate.pair_key,
                )
                continue
            if evidence and evidence not in context:
                logger.debug(
                    "RE LLM evidence not a substring of context — discarded for pair %s",
                    pp.candidate.pair_key,
                )
                continue

            entry = schema.get(relation)
            if entry is None:
                continue

            head_id, tail_id = pp.candidate.head_id, pp.candidate.tail_id
            head_canonical, tail_canonical = pp.candidate.head_canonical, pp.candidate.tail_canonical
            head_type, tail_type = pp.candidate.head_type, pp.candidate.tail_type
            if not entry.accepts_pair(head_type, tail_type):
                if entry.accepts_pair(tail_type, head_type):
                    head_id, tail_id = pp.candidate.tail_id, pp.candidate.head_id
                    head_canonical, tail_canonical = (
                        pp.candidate.tail_canonical,
                        pp.candidate.head_canonical,
                    )
                else:
                    continue

            results.append(ExtractedRelation(
                head_id=head_id,
                tail_id=tail_id,
                relation=relation,
                confidence=entry.confidence_for(ExtractionPhase.GROUNDED_LLM),
                evidence_span=evidence or context[:80],
                source_pericope_id=pp.candidate.source_pericope_id,
                extraction_phase=ExtractionPhase.GROUNDED_LLM,
                head_canonical=head_canonical,
                tail_canonical=tail_canonical,
            ))

        return results


def _chunk(items: Iterable, size: int) -> Iterable[list]:
    bucket: list = []
    for item in items:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def _coerce_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)

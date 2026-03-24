"""
LLM-based entity extractor supporting multiple providers.
Extracts Event, Object, and Theme entities from Bible text.
"""

import json
import logging
import time
from typing import List, Dict, Tuple, Optional
from abc import ABC, abstractmethod

from .models import Entity, EntityMention, EntityType, ExtractionMethod
from .config import LLMConfig

logger = logging.getLogger(__name__)


# Prompt templates
SYSTEM_PROMPT = """你是一位專業的聖經文本分析師。你的任務是從聖經經文中抽取以下類型的實體：

1. **Event (事件)** - 聖經中的重要事件，如：出埃及、洪水、耶穌受洗、復活、五旬節、創世等
2. **Object (物件)** - 聖經中的重要物件，如：約櫃、會幕、十字架、燔祭、聖殿、法版等
3. **Theme (主題)** - 神學主題或概念，如：救贖、恩典、信心、愛、公義、審判、立約等

請注意：
- 只抽取經文中明確提到或強烈暗示的實體
- Event 應該是具體可識別的事件
- Object 應該是具體的物件或儀式用品
- Theme 應該是經文中討論或體現的神學概念

請以 JSON 格式回應：
```json
{
  "entities": [
    {
      "name": "實體名稱",
      "type": "Event|Object|Theme",
      "description": "簡短描述"
    }
  ]
}
```

如果沒有找到任何實體，請回傳空陣列：
```json
{"entities": []}
```"""

USER_PROMPT_TEMPLATE = """請從以下聖經經文中抽取 Event（事件）、Object（物件）、Theme（主題）實體：

經文 ID: {source_id}
經文內容:
{text}

請以 JSON 格式回應。"""


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        self._last_request_time = 0
    
    @abstractmethod
    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Call the LLM and return the response text."""
        pass
    
    def rate_limit(self):
        """Apply rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.config.rate_limit_delay:
            time.sleep(self.config.rate_limit_delay - elapsed)
        self._last_request_time = time.time()


class ClaudeClient(BaseLLMClient):
    """Claude API client."""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.client = None
        self._initialize()
    
    def _initialize(self):
        """Initialize Anthropic client."""
        try:
            import anthropic
            
            if not self.config.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")
            
            self.client = anthropic.Anthropic(api_key=self.config.api_key)
            logger.info(f"Claude client initialized with model: {self.config.model}")
            
        except ImportError:
            raise ImportError("anthropic package not installed. Install with: pip install anthropic")
    
    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Call Claude API."""
        self.rate_limit()
        
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        
        return response.content[0].text


class GeminiClient(BaseLLMClient):
    """Gemini API client."""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.client = None
        self._initialize()
    
    def _initialize(self):
        """Initialize Gemini client."""
        try:
            import google.generativeai as genai
            
            if not self.config.api_key:
                raise ValueError("GOOGLE_API_KEY not set in environment")
            
            genai.configure(api_key=self.config.api_key)
            self.client = genai.GenerativeModel(self.config.model)
            logger.info(f"Gemini client initialized with model: {self.config.model}")
            
        except ImportError:
            raise ImportError("google-generativeai package not installed. Install with: pip install google-generativeai")
    
    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini API."""
        self.rate_limit()
        
        # Gemini combines system and user prompts
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        response = self.client.generate_content(
            full_prompt,
            generation_config={
                "temperature": self.config.temperature,
                "max_output_tokens": self.config.max_tokens,
            }
        )
        
        return response.text


class OpenAIClient(BaseLLMClient):
    """OpenAI API client."""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.client = None
        self._initialize()
    
    def _initialize(self):
        """Initialize OpenAI client."""
        try:
            from openai import OpenAI
            
            if not self.config.api_key:
                raise ValueError("OPENAI_API_KEY not set in environment")
            
            self.client = OpenAI(api_key=self.config.api_key)
            logger.info(f"OpenAI client initialized with model: {self.config.model}")
            
        except ImportError:
            raise ImportError("openai package not installed. Install with: pip install openai")
    
    def call(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI API."""
        self.rate_limit()
        
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        
        return response.choices[0].message.content


def create_llm_client(config) -> BaseLLMClient:
    """Factory function to create LLM client based on provider."""
    if config.provider == "claude":
        return ClaudeClient(config)
    elif config.provider == "gemini":
        return GeminiClient(config)
    elif config.provider == "openai":
        return OpenAIClient(config)
    elif config.provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(config)
    else:
        raise ValueError(f"Unknown LLM provider: {config.provider}")


class LLMExtractor:
    """
    LLM-based entity extractor supporting multiple providers.
    Extracts Event, Object, and Theme entities that require semantic understanding.
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize the LLM extractor.
        
        Args:
            config: LLM configuration. If None, loads from environment.
        """
        if config is None:
            config = LLMConfig.from_env()
        
        self.config = config
        self.client = create_llm_client(config)

    def extract_from_text(
        self,
        text: str,
        source_id: str,
        source_type: str,
    ) -> Tuple[List[Entity], List[EntityMention]]:
        """
        Extract Event, Object, and Theme entities from text using LLM.
        
        Args:
            text: The text to extract entities from.
            source_id: ID of the source.
            source_type: Type of source ("pericope" or "chunk").
            
        Returns:
            Tuple of (entities, mentions).
        """
        # Call LLM with retry logic
        raw_result = self._call_llm_with_retry(text, source_id)
        
        if not raw_result or not raw_result.get("entities"):
            return [], []
        
        # Convert to Entity and EntityMention objects
        return self._process_llm_result(raw_result, text, source_id, source_type)

    def _call_llm_with_retry(
        self,
        text: str,
        source_id: str,
    ) -> Optional[Dict]:
        """Call LLM with retry logic."""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            source_id=source_id,
            text=text,
        )
        
        for attempt in range(self.config.max_retries):
            try:
                content = self.client.call(SYSTEM_PROMPT, user_prompt)
                return self._parse_json_response(content)
                
            except Exception as e:
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{self.config.max_retries}): {e}"
                )
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
        
        logger.error(f"LLM call failed after {self.config.max_retries} attempts")
        return None

    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """Parse JSON from LLM response."""
        try:
            # Try to extract JSON from markdown code block
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
            logger.warning(f"Failed to parse JSON response: {e}")
            return None

    def _process_llm_result(
        self,
        result: Dict,
        text: str,
        source_id: str,
        source_type: str,
    ) -> Tuple[List[Entity], List[EntityMention]]:
        """Process LLM result into Entity and EntityMention objects."""
        entities: Dict[str, Entity] = {}
        mentions: List[EntityMention] = []
        mention_counter = 0
        
        for item in result.get("entities", []):
            name = item.get("name", "").strip()
            type_str = item.get("type", "").strip()
            description = item.get("description", "").strip()
            
            if not name or not type_str:
                continue
            
            # Map to EntityType
            try:
                entity_type = EntityType(type_str)
            except ValueError:
                logger.warning(f"Unknown entity type: {type_str}")
                continue
            
            # Only accept Event, Object, Theme from LLM
            if entity_type not in [EntityType.EVENT, EntityType.OBJECT, EntityType.THEME]:
                continue
            
            entity_id = self._generate_entity_id(entity_type, name)
            
            # Create or update entity
            if entity_id not in entities:
                entities[entity_id] = Entity(
                    entity_id=entity_id,
                    type=entity_type,
                    canonical_name=name,
                    description=description,
                    extraction_method=ExtractionMethod.LLM,
                    mention_count=1,
                )
            else:
                entities[entity_id].mention_count += 1
            
            # Create mention
            mention_counter += 1
            
            # Try to find position in text
            start_pos = text.find(name) if name in text else None
            end_pos = start_pos + len(name) if start_pos is not None else None
            
            context = self._get_context(text, name)
            
            mention = EntityMention(
                mention_id=f"m:{source_id}:{mention_counter:03d}",
                entity_id=entity_id,
                source_id=source_id,
                source_type=source_type,
                text_span=name,
                context=context,
                start_pos=start_pos,
                end_pos=end_pos,
            )
            mentions.append(mention)
        
        return list(entities.values()), mentions

    def _generate_entity_id(self, entity_type: EntityType, name: str) -> str:
        """Generate a unique entity ID."""
        try:
            from pypinyin import lazy_pinyin
            pinyin = "".join(lazy_pinyin(name))
        except ImportError:
            pinyin = name.replace(" ", "_").lower()
        
        type_prefix = entity_type.value.lower()
        return f"{type_prefix}:{pinyin}"

    def _get_context(self, text: str, entity_name: str, window: int = 30) -> str:
        """Get context around an entity mention."""
        pos = text.find(entity_name)
        if pos == -1:
            # Return first part of text as context
            return text[:min(len(text), 60)] + "..." if len(text) > 60 else text
        
        start = max(0, pos - window)
        end = min(len(text), pos + len(entity_name) + window)
        
        context = text[start:end]
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
        
        return context


def extract_entities_batch(
    extractor: LLMExtractor,
    items: List[Dict],
    show_progress: bool = True,
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """
    Extract entities from a batch of items using LLM.
    
    Args:
        extractor: The LLM extractor instance.
        items: List of items with 'id', 'type', and 'text' fields.
        show_progress: Whether to show progress bar.
        
    Returns:
        Tuple of (entity_dict, mentions_list).
    """
    all_entities: Dict[str, Entity] = {}
    all_mentions: List[EntityMention] = []
    
    if show_progress:
        try:
            from tqdm import tqdm
            items = tqdm(items, desc="LLM Extraction")
        except ImportError:
            pass
    
    for item in items:
        try:
            entities, mentions = extractor.extract_from_text(
                text=item["text"],
                source_id=item["id"],
                source_type=item["type"],
            )
            
            # Merge entities
            for entity in entities:
                if entity.entity_id not in all_entities:
                    all_entities[entity.entity_id] = entity
                else:
                    existing = all_entities[entity.entity_id]
                    existing.mention_count += entity.mention_count
            
            all_mentions.extend(mentions)
            
        except Exception as e:
            logger.error(f"Failed to extract from {item.get('id')}: {e}")
    
    return all_entities, all_mentions

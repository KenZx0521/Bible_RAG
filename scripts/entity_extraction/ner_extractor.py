"""
NER-based entity extractor using CKIP Transformers.
Extracts Person, Place, and Group entities from Traditional Chinese Bible text.
"""

import logging
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass

from .models import Entity, EntityMention, EntityType, ExtractionMethod
from .entity_dict import (
    PERSON_DICT,
    PLACE_DICT,
    GROUP_DICT,
    get_all_person_names,
    get_all_place_names,
    get_all_group_names,
    find_canonical_name,
)

logger = logging.getLogger(__name__)


@dataclass
class NERResult:
    """Result from NER extraction."""
    text: str
    entity_type: str
    start: int
    end: int


class NERExtractor:
    """
    NER-based entity extractor using CKIP Transformers.
    Combines CKIP NER with custom biblical dictionary for enhanced accuracy.
    """

    def __init__(self, use_gpu: bool = False):
        """
        Initialize the NER extractor.
        
        Args:
            use_gpu: Whether to use GPU for CKIP models.
        """
        self.ner_driver = None
        self.ws_driver = None
        self.use_gpu = use_gpu
        self._initialized = False
        
        # Pre-compile entity name sets for fast lookup
        self._person_names = get_all_person_names()
        self._place_names = get_all_place_names()
        self._group_names = get_all_group_names()
        
        # Combined dictionary for fast lookup
        self._all_entities: Dict[str, str] = {}
        for name in self._person_names:
            self._all_entities[name] = "Person"
        for name in self._place_names:
            self._all_entities[name] = "Place"
        for name in self._group_names:
            self._all_entities[name] = "Group"

    def _initialize_ckip(self):
        """Lazy initialization of CKIP models."""
        if self._initialized:
            return
        
        try:
            from ckip_transformers.nlp import CkipWordSegmenter, CkipNerChunker
            
            logger.info("Loading CKIP models...")
            device = 0 if self.use_gpu else -1
            
            # Word segmenter for dictionary-based extraction
            self.ws_driver = CkipWordSegmenter(model="bert-base", device=device)
            
            # NER model for additional entity recognition
            self.ner_driver = CkipNerChunker(model="bert-base", device=device)
            
            self._initialized = True
            logger.info("CKIP models loaded successfully")
            
        except ImportError:
            logger.error("CKIP Transformers not installed. Install with: pip install ckip-transformers")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize CKIP: {e}")
            raise

    def extract_from_text(
        self,
        text: str,
        source_id: str,
        source_type: str,
    ) -> Tuple[List[Entity], List[EntityMention]]:
        """
        Extract entities from a single text.
        
        Args:
            text: The text to extract entities from.
            source_id: ID of the source (pericope or chunk).
            source_type: Type of source ("pericope" or "chunk").
            
        Returns:
            Tuple of (entities, mentions).
        """
        self._initialize_ckip()
        
        entities: Dict[str, Entity] = {}
        mentions: List[EntityMention] = []
        mention_counter = 0
        
        # Method 1: Dictionary-based extraction (faster, more accurate for known entities)
        dict_results = self._extract_by_dictionary(text)
        
        # Method 2: CKIP NER extraction (catches entities not in dictionary)
        ner_results = self._extract_by_ckip_ner(text)
        
        # Combine results (dictionary takes precedence)
        all_results = self._merge_results(dict_results, ner_results)
        
        # Create Entity and EntityMention objects
        for result in all_results:
            entity_type = EntityType(result.entity_type)
            canonical_name = find_canonical_name(result.text, result.entity_type)
            entity_id = self._generate_entity_id(entity_type, canonical_name)
            
            # Create or update entity
            if entity_id not in entities:
                aliases = []
                if result.text != canonical_name:
                    aliases.append(result.text)
                
                entities[entity_id] = Entity(
                    entity_id=entity_id,
                    type=entity_type,
                    canonical_name=canonical_name,
                    aliases=aliases,
                    extraction_method=ExtractionMethod.NER,
                    mention_count=1,
                )
            else:
                entities[entity_id].mention_count += 1
                if result.text != canonical_name and result.text not in entities[entity_id].aliases:
                    entities[entity_id].aliases.append(result.text)
            
            # Create mention
            mention_counter += 1
            context = self._get_context(text, result.start, result.end)
            
            mention = EntityMention(
                mention_id=f"m:{source_id}:{mention_counter:03d}",
                entity_id=entity_id,
                source_id=source_id,
                source_type=source_type,
                text_span=result.text,
                context=context,
                start_pos=result.start,
                end_pos=result.end,
            )
            mentions.append(mention)
        
        return list(entities.values()), mentions

    def _extract_by_dictionary(self, text: str) -> List[NERResult]:
        """Extract entities using dictionary matching."""
        results = []
        
        # Sort by length (longest first) to avoid partial matches
        sorted_entities = sorted(self._all_entities.keys(), key=len, reverse=True)
        
        # Track matched positions to avoid duplicates
        matched_positions: Set[Tuple[int, int]] = set()
        
        for entity_name in sorted_entities:
            start = 0
            while True:
                pos = text.find(entity_name, start)
                if pos == -1:
                    break
                
                end = pos + len(entity_name)
                
                # Check if this position overlaps with an existing match
                overlaps = False
                for (m_start, m_end) in matched_positions:
                    if not (end <= m_start or pos >= m_end):
                        overlaps = True
                        break
                
                if not overlaps:
                    entity_type = self._all_entities[entity_name]
                    results.append(NERResult(
                        text=entity_name,
                        entity_type=entity_type,
                        start=pos,
                        end=end,
                    ))
                    matched_positions.add((pos, end))
                
                start = pos + 1
        
        return results

    def _extract_by_ckip_ner(self, text: str) -> List[NERResult]:
        """Extract entities using CKIP NER."""
        results = []
        
        try:
            ner_output = self.ner_driver([text])
            
            # CKIP returns list of NerToken objects with 'word' and 'ner' attributes
            for entity in ner_output[0]:
                # Handle different CKIP output formats
                if hasattr(entity, 'ner') and hasattr(entity, 'word'):
                    # New format: NerToken(word='...', ner='...')
                    ner_type = entity.ner
                    entity_text = entity.word
                elif isinstance(entity, tuple) and len(entity) >= 2:
                    # Old format: (word, ner) or (start, end, type, text)
                    if len(entity) == 2:
                        entity_text, ner_type = entity
                    else:
                        ner_type = entity[2]
                        entity_text = entity[3] if len(entity) > 3 else entity[0]
                else:
                    continue
                
                # Map CKIP NER types to our entity types
                mapped_type = self._map_ckip_type(ner_type)
                if mapped_type:
                    # Find position in text
                    start = text.find(entity_text)
                    if start != -1:
                        results.append(NERResult(
                            text=entity_text,
                            entity_type=mapped_type,
                            start=start,
                            end=start + len(entity_text),
                        ))
        except Exception as e:
            logger.warning(f"CKIP NER failed: {e}")
        
        return results

    def _map_ckip_type(self, ckip_type: str) -> Optional[str]:
        """Map CKIP NER type to our entity type."""
        type_mapping = {
            "PERSON": "Person",
            "GPE": "Place",  # Geo-Political Entity
            "LOC": "Place",  # Location
            "ORG": "Group",  # Organization
            "NORP": "Group",  # Nationalities, religious, political groups
        }
        return type_mapping.get(ckip_type)

    def _merge_results(
        self,
        dict_results: List[NERResult],
        ner_results: List[NERResult],
    ) -> List[NERResult]:
        """Merge dictionary and NER results, preferring dictionary matches."""
        # Dictionary results take precedence
        merged = dict_results.copy()
        dict_positions = {(r.start, r.end) for r in dict_results}
        
        # Add NER results that don't overlap with dictionary results
        for ner_result in ner_results:
            overlaps = False
            for (d_start, d_end) in dict_positions:
                if not (ner_result.end <= d_start or ner_result.start >= d_end):
                    overlaps = True
                    break
            
            if not overlaps:
                merged.append(ner_result)
        
        return merged

    def _generate_entity_id(self, entity_type: EntityType, name: str) -> str:
        """Generate a unique entity ID."""
        try:
            from pypinyin import lazy_pinyin
            pinyin = "".join(lazy_pinyin(name))
        except ImportError:
            # Fallback if pypinyin not available
            pinyin = name.replace(" ", "_").lower()
        
        type_prefix = entity_type.value.lower()
        return f"{type_prefix}:{pinyin}"

    def _get_context(self, text: str, start: int, end: int, window: int = 30) -> str:
        """Get context around an entity mention."""
        context_start = max(0, start - window)
        context_end = min(len(text), end + window)
        
        context = text[context_start:context_end]
        if context_start > 0:
            context = "..." + context
        if context_end < len(text):
            context = context + "..."
        
        return context


def extract_entities_from_batch(
    extractor: NERExtractor,
    items: List[Dict],
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """
    Extract entities from a batch of items.
    
    Args:
        extractor: The NER extractor instance.
        items: List of items with 'id', 'type', and 'text' fields.
        
    Returns:
        Tuple of (entity_dict, mentions_list).
    """
    all_entities: Dict[str, Entity] = {}
    all_mentions: List[EntityMention] = []
    
    for item in items:
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
                # Update mention count and aliases
                existing = all_entities[entity.entity_id]
                existing.mention_count += entity.mention_count
                for alias in entity.aliases:
                    if alias not in existing.aliases:
                        existing.aliases.append(alias)
        
        all_mentions.extend(mentions)
    
    return all_entities, all_mentions

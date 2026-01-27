"""
Entity normalizer for deduplication and consolidation.
"""

import logging
from typing import Dict, List, Set, Tuple
from collections import defaultdict

from .models import Entity, EntityMention, EntityType

logger = logging.getLogger(__name__)


class EntityNormalizer:
    """
    Normalizes entities by deduplicating and consolidating aliases.
    """

    def __init__(self):
        """Initialize the normalizer."""
        self._canonical_mapping: Dict[str, str] = {}  # entity_id -> canonical_entity_id

    def normalize(
        self,
        entities: Dict[str, Entity],
        mentions: List[EntityMention],
    ) -> Tuple[Dict[str, Entity], List[EntityMention]]:
        """
        Normalize entities and update mentions accordingly.
        
        Args:
            entities: Dictionary of entity_id -> Entity.
            mentions: List of EntityMention objects.
            
        Returns:
            Tuple of (normalized_entities, updated_mentions).
        """
        # Step 1: Find similar entities to merge
        merge_groups = self._find_merge_groups(entities)
        
        # Step 2: Merge entities
        normalized_entities = self._merge_entities(entities, merge_groups)
        
        # Step 3: Update mentions
        updated_mentions = self._update_mentions(mentions, self._canonical_mapping)
        
        logger.info(
            f"Normalized {len(entities)} entities to {len(normalized_entities)} "
            f"(merged {len(entities) - len(normalized_entities)})"
        )
        
        return normalized_entities, updated_mentions

    def _find_merge_groups(
        self,
        entities: Dict[str, Entity],
    ) -> Dict[str, List[str]]:
        """
        Find groups of entities that should be merged.
        
        Returns:
            Dictionary of canonical_id -> list of entity_ids to merge.
        """
        merge_groups: Dict[str, List[str]] = defaultdict(list)
        
        # Group by type first
        by_type: Dict[EntityType, List[Entity]] = defaultdict(list)
        for entity in entities.values():
            by_type[entity.type].append(entity)
        
        # Within each type, find similar entities
        for entity_type, type_entities in by_type.items():
            # Sort by mention count (prefer more common as canonical)
            type_entities.sort(key=lambda e: e.mention_count, reverse=True)
            
            merged: Set[str] = set()
            
            for i, entity1 in enumerate(type_entities):
                if entity1.entity_id in merged:
                    continue
                
                group = [entity1.entity_id]
                
                for entity2 in type_entities[i + 1:]:
                    if entity2.entity_id in merged:
                        continue
                    
                    if self._should_merge(entity1, entity2):
                        group.append(entity2.entity_id)
                        merged.add(entity2.entity_id)
                
                if len(group) > 1:
                    merge_groups[entity1.entity_id] = group
                else:
                    merge_groups[entity1.entity_id] = [entity1.entity_id]
        
        return merge_groups

    def _should_merge(self, entity1: Entity, entity2: Entity) -> bool:
        """Determine if two entities should be merged."""
        # Same canonical name
        if entity1.canonical_name == entity2.canonical_name:
            return True
        
        # One is alias of the other
        if entity1.canonical_name in entity2.aliases:
            return True
        if entity2.canonical_name in entity1.aliases:
            return True
        
        # Check alias overlap
        aliases1 = set(entity1.aliases)
        aliases1.add(entity1.canonical_name)
        aliases2 = set(entity2.aliases)
        aliases2.add(entity2.canonical_name)
        
        if aliases1 & aliases2:  # Non-empty intersection
            return True
        
        return False

    def _merge_entities(
        self,
        entities: Dict[str, Entity],
        merge_groups: Dict[str, List[str]],
    ) -> Dict[str, Entity]:
        """Merge entities according to merge groups."""
        normalized: Dict[str, Entity] = {}
        
        for canonical_id, group_ids in merge_groups.items():
            if canonical_id not in entities:
                continue
            
            canonical = entities[canonical_id]
            
            # Collect all aliases
            all_aliases: Set[str] = set(canonical.aliases)
            total_mentions = canonical.mention_count
            
            for entity_id in group_ids:
                if entity_id == canonical_id:
                    continue
                if entity_id not in entities:
                    continue
                
                other = entities[entity_id]
                all_aliases.add(other.canonical_name)
                all_aliases.update(other.aliases)
                total_mentions += other.mention_count
                
                # Update mapping
                self._canonical_mapping[entity_id] = canonical_id
            
            # Remove canonical_name from aliases
            all_aliases.discard(canonical.canonical_name)
            
            # Create merged entity
            merged = Entity(
                entity_id=canonical_id,
                type=canonical.type,
                canonical_name=canonical.canonical_name,
                aliases=sorted(all_aliases),
                description=canonical.description,
                extraction_method=canonical.extraction_method,
                mention_count=total_mentions,
            )
            
            normalized[canonical_id] = merged
            self._canonical_mapping[canonical_id] = canonical_id
        
        # Add entities that weren't in any merge group
        for entity_id, entity in entities.items():
            if entity_id not in self._canonical_mapping:
                normalized[entity_id] = entity
                self._canonical_mapping[entity_id] = entity_id
        
        return normalized

    def _update_mentions(
        self,
        mentions: List[EntityMention],
        mapping: Dict[str, str],
    ) -> List[EntityMention]:
        """Update mentions to point to canonical entities."""
        updated = []
        
        for mention in mentions:
            new_entity_id = mapping.get(mention.entity_id, mention.entity_id)
            
            updated_mention = EntityMention(
                mention_id=mention.mention_id,
                entity_id=new_entity_id,
                source_id=mention.source_id,
                source_type=mention.source_type,
                text_span=mention.text_span,
                context=mention.context,
                start_pos=mention.start_pos,
                end_pos=mention.end_pos,
            )
            updated.append(updated_mention)
        
        return updated


def normalize_and_merge(
    ner_entities: Dict[str, Entity],
    llm_entities: Dict[str, Entity],
    ner_mentions: List[EntityMention],
    llm_mentions: List[EntityMention],
) -> Tuple[Dict[str, Entity], List[EntityMention]]:
    """
    Merge NER and LLM extraction results and normalize.
    
    Args:
        ner_entities: Entities from NER extraction.
        llm_entities: Entities from LLM extraction.
        ner_mentions: Mentions from NER extraction.
        llm_mentions: Mentions from LLM extraction.
        
    Returns:
        Tuple of (all_entities, all_mentions).
    """
    # Combine entities
    all_entities = ner_entities.copy()
    
    for entity_id, entity in llm_entities.items():
        if entity_id not in all_entities:
            all_entities[entity_id] = entity
        else:
            # Merge mention counts
            all_entities[entity_id].mention_count += entity.mention_count
    
    # Combine mentions
    all_mentions = ner_mentions + llm_mentions
    
    # Normalize
    normalizer = EntityNormalizer()
    return normalizer.normalize(all_entities, all_mentions)

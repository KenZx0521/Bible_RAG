"""
Phase 2: CKIP POS Tagging for Object/Theme candidate extraction.

Uses CkipWordSegmenter + CkipPosTagger to extract nouns from pericope texts,
then filters and aggregates by frequency.
"""

import logging
from collections import Counter, defaultdict
from typing import List, Set, Tuple

from .models import EntityCandidate, EntityType
from .bible_md_parser import PericopeData
from .entity_dict import (
    PERSON_DICT,
    PLACE_DICT,
    GROUP_DICT,
)

logger = logging.getLogger(__name__)

# Build flat name sets for filtering
_ALL_KNOWN_NAMES: Set[str] = set()
for _d in (PERSON_DICT, PLACE_DICT, GROUP_DICT):
    for canonical, aliases in _d.items():
        _ALL_KNOWN_NAMES.add(canonical)
        _ALL_KNOWN_NAMES.update(aliases)

# POS tags of interest
# Na = common noun, Nb = proper noun, Nv = verbal noun
NOUN_POS_TAGS = {"Na", "Nb", "Nv", "Nc"}

# Single-char stopwords to exclude
STOPWORDS = {
    "人", "地", "天", "日", "年", "月", "時", "水", "山", "海",
    "王", "子", "民", "城", "國", "家", "道", "事", "話", "名",
    "手", "心", "口", "眼", "身", "頭", "腳", "耳", "血", "骨",
    "神", "靈", "主",
}


class CkipPosExtractor:
    """Extract noun candidates from pericope texts via CKIP POS tagging."""

    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self._ws = None
        self._pos = None

    def _init_models(self):
        if self._ws is not None:
            return
        from ckip_transformers.nlp import CkipWordSegmenter, CkipPosTagger

        device = 0 if self.use_gpu else -1
        logger.info("Loading CKIP WS + POS models...")
        self._ws = CkipWordSegmenter(model="bert-base", device=device)
        self._pos = CkipPosTagger(model="bert-base", device=device)
        logger.info("CKIP models loaded.")

    def extract_candidates(
        self,
        pericopes: List[PericopeData],
        min_freq: int = 3,
        batch_size: int = 64,
    ) -> List[EntityCandidate]:
        """
        Phase 2: Extract noun candidates from pericope texts.

        Returns candidates with frequency >= min_freq, excluding known
        Person/Place/Group names and single-char stopwords.
        """
        self._init_models()

        # Collect all texts
        texts = [p.full_text for p in pericopes if p.full_text]
        source_map = {p.full_text: p.source_id for p in pericopes if p.full_text}

        # Process in batches
        all_nouns: Counter = Counter()
        noun_sources: dict[str, list[str]] = defaultdict(list)
        noun_pos: dict[str, str] = {}
        noun_grounding: dict[str, str] = {}

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            ws_results = self._ws(batch)
            pos_results = self._pos(ws_results)

            for text, words, tags in zip(batch, ws_results, pos_results):
                src_id = source_map[text]
                self._extract_from_sentence(
                    words, tags, src_id, text,
                    all_nouns, noun_sources, noun_pos, noun_grounding,
                )
                # N-gram: combine adjacent Na+Na
                self._extract_ngrams(
                    words, tags, src_id, text,
                    all_nouns, noun_sources, noun_pos, noun_grounding,
                )

        # Filter by frequency
        candidates: List[EntityCandidate] = []
        for noun, freq in all_nouns.most_common():
            if freq < min_freq:
                continue
            pos_tag = noun_pos.get(noun, "")
            proposed_type = self._pos_to_type(pos_tag)

            candidates.append(EntityCandidate(
                name=noun,
                proposed_type=proposed_type,
                source_ids=noun_sources[noun][:10],  # limit stored sources
                grounding_text=noun_grounding.get(noun, ""),
                confidence=0.0,
                extraction_phase=2,
                pos_tag=pos_tag,
                frequency=freq,
            ))

        logger.info(
            f"Phase 2: extracted {len(candidates)} candidates "
            f"(min_freq={min_freq}) from {len(texts)} texts"
        )
        return candidates

    def _extract_from_sentence(
        self,
        words: List[str],
        tags: List[str],
        source_id: str,
        text: str,
        counter: Counter,
        sources: dict,
        pos_map: dict,
        grounding: dict,
    ):
        for word, tag in zip(words, tags):
            if tag not in NOUN_POS_TAGS:
                continue
            if len(word) <= 1:
                continue
            if word in STOPWORDS:
                continue
            if word in _ALL_KNOWN_NAMES:
                continue
            counter[word] += 1
            sources[word].append(source_id)
            if word not in pos_map:
                pos_map[word] = tag
            if word not in grounding:
                # Find word in context
                idx = text.find(word)
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(text), idx + len(word) + 20)
                    grounding[word] = text[start:end]

    def _extract_ngrams(
        self,
        words: List[str],
        tags: List[str],
        source_id: str,
        text: str,
        counter: Counter,
        sources: dict,
        pos_map: dict,
        grounding: dict,
    ):
        """Combine adjacent Na+Na into compound nouns (e.g., 燔+祭=燔祭)."""
        for i in range(len(words) - 1):
            if tags[i] in {"Na", "Nb"} and tags[i + 1] in {"Na", "Nb"}:
                compound = words[i] + words[i + 1]
                if len(compound) <= 1 or compound in _ALL_KNOWN_NAMES:
                    continue
                # Verify compound exists in original text
                if compound not in text:
                    continue
                counter[compound] += 1
                sources[compound].append(source_id)
                if compound not in pos_map:
                    pos_map[compound] = f"{tags[i]}+{tags[i+1]}"
                if compound not in grounding:
                    idx = text.find(compound)
                    if idx >= 0:
                        start = max(0, idx - 20)
                        end = min(len(text), idx + len(compound) + 20)
                        grounding[compound] = text[start:end]

    @staticmethod
    def _pos_to_type(pos_tag: str) -> EntityType | None:
        """Map POS tag to proposed EntityType."""
        if pos_tag == "Nv":
            return EntityType.EVENT
        if pos_tag in {"Na", "Nc"} or "Na" in pos_tag:
            return EntityType.OBJECT
        if pos_tag == "Nb":
            return None  # proper noun, needs further classification
        return None

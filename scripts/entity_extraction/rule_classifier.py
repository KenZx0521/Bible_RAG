"""
Phase 3: Rule-based classification of entity candidates.

Applies deterministic rules to assign EntityType and confidence.
Candidates below rule_confidence threshold are forwarded to Phase 4 (LLM).
"""

import logging
from typing import List, Tuple

from .models import EntityCandidate, EntityType

logger = logging.getLogger(__name__)

# ── Rule tables ──

OBJECT_SUFFIXES = (
    "壇", "器", "衣", "冠", "殿", "櫃", "幕", "杖", "碗", "燈",
    "餅", "袍", "印", "角", "瓶", "盆", "桌", "座", "柱", "爐",
    "門", "幔", "鉤", "環", "板", "栓", "架", "帳", "鐘", "鏟",
    "刀", "弓", "箭", "盾", "槍", "琴", "鈸", "號", "祭", "香",
    "油", "酒", "鹽", "樹", "冕", "帕",
)

OBJECT_EXACT = {
    "約櫃", "法版", "會幕", "聖殿", "銅蛇", "金牛犢", "以弗得",
    "烏陵", "土明", "陳設餅", "無酵餅", "嗎哪", "生命樹",
    "分別善惡的樹", "十字架", "荊棘冠冕", "聖衣", "胸牌",
    "燈臺", "香壇", "銅祭壇", "洗濯盆", "施恩座", "方舟",
}

THEME_KEYWORDS = {
    "救贖", "恩典", "信心", "公義", "審判", "聖潔", "盼望",
    "慈愛", "憐憫", "悔改", "饒恕", "智慧", "律法", "誡命",
    "應許", "祝福", "咒詛", "順服", "敬拜", "禱告", "讚美",
    "復興", "潔淨", "稱義", "成聖", "忍耐", "謙卑", "誠實",
    "正直", "罪", "罪惡", "赦免", "救恩", "永生", "天國",
    "福音", "聖靈", "神的國", "上帝的國", "割禮", "安息日",
    "逾越", "五旬", "贖罪", "立約", "愛", "盟約", "重生",
    "受洗", "揀選", "預定", "神蹟", "復活的盼望",
}

THEME_EXACT = {
    "因信稱義", "道成肉身", "三位一體", "末世論", "新約",
    "舊約", "先知預言", "彌賽亞", "天父", "聖靈的果子",
    "信望愛", "十字架的道理", "神的愛",
}

EVENT_VERB_COMPONENTS = {
    "創造", "墮落", "洪水", "出埃及", "過紅海", "征服",
    "被擄", "歸回", "重建", "受洗", "受試探", "升天",
    "降生", "釘十字架", "復活", "差遣", "宣教", "殉道",
    "戰爭", "爭戰", "獻祭", "膏立", "分裂", "叛亂",
    "圍城", "陷落", "逃亡", "漂流", "探子", "過約旦河",
}


def classify_candidates(
    candidates: List[EntityCandidate],
    rule_confidence: float = 0.8,
) -> Tuple[List[EntityCandidate], List[EntityCandidate]]:
    """
    Phase 3: Apply rule-based classification.

    Returns:
        (classified, unclassified) — classified candidates have
        confidence >= rule_confidence; unclassified go to Phase 4.
    """
    classified: List[EntityCandidate] = []
    unclassified: List[EntityCandidate] = []

    for c in candidates:
        name = c.name
        matched_type, conf = _apply_rules(name, c)

        if conf >= rule_confidence:
            c.proposed_type = matched_type
            c.confidence = conf
            c.extraction_phase = 3
            classified.append(c)
        else:
            # Keep whatever Phase 1/2 suggested but mark low confidence
            if matched_type is not None and c.proposed_type is None:
                c.proposed_type = matched_type
            c.confidence = conf
            unclassified.append(c)

    logger.info(
        f"Phase 3: classified {len(classified)}, "
        f"unclassified {len(unclassified)} (threshold={rule_confidence})"
    )
    return classified, unclassified


def _apply_rules(
    name: str,
    candidate: EntityCandidate,
) -> Tuple[EntityType | None, float]:
    """Apply rules in priority order, return (type, confidence)."""
    # Exact matches (highest confidence)
    if name in OBJECT_EXACT:
        return EntityType.OBJECT, 0.95
    if name in THEME_EXACT:
        return EntityType.THEME, 0.95

    # Suffix match for Object
    for suffix in OBJECT_SUFFIXES:
        if name.endswith(suffix) and len(name) >= 2:
            return EntityType.OBJECT, 0.9

    # Theme keyword containment
    for kw in THEME_KEYWORDS:
        if kw in name:
            return EntityType.THEME, 0.9

    # Event verb component
    for verb in EVENT_VERB_COMPONENTS:
        if verb in name:
            return EntityType.EVENT, 0.85

    # From pericope title (Phase 1) with verb-like content
    if candidate.extraction_phase == 1:
        return EntityType.EVENT, 0.7

    # POS-based hints
    if candidate.pos_tag == "Nv" and candidate.frequency >= 5:
        return EntityType.EVENT, 0.6

    # No confident match
    return candidate.proposed_type, 0.0

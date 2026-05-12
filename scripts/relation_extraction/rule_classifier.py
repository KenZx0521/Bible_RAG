"""Phase R2 — Rule-based classifier.

Walks the schema's prompt_signals against the candidate pair's grounding text.
A signal counts as a match when it appears between (or near) the head and tail
canonical names. Matches yield ExtractedRelation with extraction_phase=RULE_MATCH.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .models import ExtractedRelation, ExtractionPhase, RelationCandidate
from .schema_loader import RelationSchema, RelationSchemaEntry

logger = logging.getLogger(__name__)


_PROXIMITY_WINDOW = 25


def _signal_to_regex(signal: str) -> str:
    if "..." not in signal:
        return re.escape(signal)
    return ".{0,8}".join(re.escape(seg) for seg in signal.split("..."))


def _signal_matches(text: str, signal: str) -> bool:
    if "..." not in signal:
        return signal in text
    pattern = re.compile(_signal_to_regex(signal))
    return bool(pattern.search(text))


def _names_within_window(text: str, name_a: str, name_b: str, signal: str) -> bool:
    if not name_a or not name_b:
        return False
    a_pos = text.find(name_a)
    b_pos = text.find(name_b)
    if a_pos < 0 or b_pos < 0:
        return False
    pattern = re.compile(_signal_to_regex(signal))
    for m in pattern.finditer(text):
        s, e = m.span()
        near_a = abs(s - a_pos) <= _PROXIMITY_WINDOW or abs(e - a_pos) <= _PROXIMITY_WINDOW
        near_b = abs(s - b_pos) <= _PROXIMITY_WINDOW or abs(e - b_pos) <= _PROXIMITY_WINDOW
        if near_a and near_b:
            return True
    return False


def _evidence_window(text: str, name_a: str, name_b: str, signal: str) -> str:
    a_pos = text.find(name_a) if name_a else -1
    b_pos = text.find(name_b) if name_b else -1
    pattern = re.compile(_signal_to_regex(signal))
    m = pattern.search(text)
    centers = [pos for pos in (a_pos, b_pos, m.start() if m else -1) if pos >= 0]
    if not centers:
        return text[:80]
    centre = sum(centers) // len(centers)
    lo = max(0, centre - 40)
    hi = min(len(text), centre + 40)
    return text[lo:hi]


def classify_by_rules(
    candidate: RelationCandidate,
    schema: RelationSchema,
) -> Optional[ExtractedRelation]:
    text = candidate.grounding_text or ""
    forward_entries = schema.candidates_for(candidate.head_type, candidate.tail_type)
    reverse_entries = schema.candidates_for(candidate.tail_type, candidate.head_type)

    best: Optional[ExtractedRelation] = None

    for entry in forward_entries:
        match = _try_entry(entry, candidate, text, candidate.head_canonical, candidate.tail_canonical, swap=False)
        best = _pick_better(best, match)

    for entry in reverse_entries:
        if entry in forward_entries and entry.direction == "directed":
            continue
        match = _try_entry(entry, candidate, text, candidate.tail_canonical, candidate.head_canonical, swap=True)
        best = _pick_better(best, match)

    return best


def _try_entry(
    entry: RelationSchemaEntry,
    candidate: RelationCandidate,
    text: str,
    name_a: str,
    name_b: str,
    swap: bool,
) -> Optional[ExtractedRelation]:
    if not entry.prompt_signals:
        return None
    for signal in entry.prompt_signals:
        if not _signal_matches(text, signal):
            continue
        if not _names_within_window(text, name_a, name_b, signal):
            continue
        evidence = _evidence_window(text, name_a, name_b, signal)
        head_id = candidate.tail_id if swap else candidate.head_id
        tail_id = candidate.head_id if swap else candidate.tail_id
        head_canonical = candidate.tail_canonical if swap else candidate.head_canonical
        tail_canonical = candidate.head_canonical if swap else candidate.tail_canonical
        return ExtractedRelation(
            head_id=head_id,
            tail_id=tail_id,
            relation=entry.name,
            confidence=entry.confidence_for(ExtractionPhase.RULE_MATCH),
            evidence_span=evidence,
            source_pericope_id=candidate.source_pericope_id,
            extraction_phase=ExtractionPhase.RULE_MATCH,
            head_canonical=head_canonical,
            tail_canonical=tail_canonical,
            notes=f"signal={signal}",
        )
    return None


def _pick_better(a: Optional[ExtractedRelation], b: Optional[ExtractedRelation]) -> Optional[ExtractedRelation]:
    if a is None:
        return b
    if b is None:
        return a
    return a if a.confidence >= b.confidence else b

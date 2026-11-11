"""What a question asks for, read from its text: the scripture references it writes."""

import logging

from utils.question_refs import find_verse_references

logger = logging.getLogger(__name__)


def classify_intent(question: str) -> dict:
    """
    The question's references (ragcommon.refs, checked against the PDF verse grid).

    Returns:
        {
            "type": str,  # "verse_lookup" when a reference was read, else "topic"
            "verse_refs": list[VerseRef],
            "rejected_refs": list[str],  # reference-shaped text naming no verse
        }
    """
    found = find_verse_references(question)
    verse_refs = list(found.refs)
    rejected = [r.raw for r in found.rejected]
    if rejected:
        logger.warning("References naming no verse, not routed: %s", rejected)
    return {
        "type": "verse_lookup" if verse_refs else "topic",
        "verse_refs": verse_refs,
        "rejected_refs": rejected,
    }

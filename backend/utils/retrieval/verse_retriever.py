"""
Verse Retriever — exact verse/chapter lookup from PostgreSQL.
"""

import logging

from database import postgres
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)


async def retrieve_by_verse_refs(verse_refs: list[VerseRef]) -> list[dict]:
    """
    Retrieve pericopes matching exact verse references from PostgreSQL.

    Returns list of candidate dicts with: id, content, title, book_name,
    chapter_num, verse_range, source_strategy, weight.
    """
    candidates = []
    seen_ids: set[str] = set()

    for ref in verse_refs:
        pericopes = await postgres.search_pericopes_by_verse_ref(
            book_id=ref.book_id,
            chapter_num=ref.chapter,
            verse_num=ref.verse_start,
        )
        for p in pericopes:
            if p["id"] not in seen_ids:
                seen_ids.add(p["id"])
                candidates.append({
                    "id": p["id"],
                    "content": p["content"],
                    "title": p["title"],
                    "book_name": p["book_name"],
                    "chapter_num": p["chapter_num"],
                    "verse_range": p.get("verse_range", ""),
                    "source_strategy": "verse_direct",
                    "weight": 1.0,
                })

    logger.info(f"Verse retriever: {len(candidates)} candidates from {len(verse_refs)} refs")
    return candidates

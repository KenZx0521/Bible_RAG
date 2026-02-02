"""
Verse Retriever — exact verse lookup from PostgreSQL.

Locates specific book:chapter:verse and returns verse-level content.
Falls back to pericope-level for chapter-only references.
"""

import logging

from database import postgres
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)


async def retrieve_by_verse_refs(verse_refs: list[VerseRef]) -> list[dict]:
    """
    Retrieve exact verse content matching verse references from PostgreSQL.

    Flow per reference:
      1. verse range  (e.g. 羅馬書3:23-24) → get_verses_range()
      2. single verse (e.g. 羅馬書3:23)    → get_verse()
      3. chapter only (e.g. 創世記第1章)   → search_pericopes_by_verse_ref()

    Returns list of candidate dicts compatible with generator._build_context:
        id, content, title, book_name, chapter_num, verse_range,
        source_strategy, weight.
    """
    candidates = []
    seen_ids: set[str] = set()

    for ref in verse_refs:
        if ref.verse_start is not None and ref.verse_end is not None and ref.verse_end > ref.verse_start:
            # Verse range: e.g. 羅馬書3:23-24
            verses = await postgres.get_verses_range(
                book_id=ref.book_id,
                chapter_num=ref.chapter,
                start_verse=ref.verse_start,
                end_verse=ref.verse_end,
            )
            if verses:
                cid = f"{ref.book_id}:{ref.chapter}:{ref.verse_start}-{ref.verse_end}"
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    content = "\n".join(
                        f"{v['verse']}. {v['text']}" for v in verses
                    )
                    candidates.append({
                        "id": cid,
                        "content": content,
                        "title": verses[0].get("pericope_title", ""),
                        "book_name": verses[0]["book_name"],
                        "chapter_num": ref.chapter,
                        "verse_range": f"{ref.verse_start}-{ref.verse_end}",
                        "source_strategy": "verse_direct",
                        "weight": 1.0,
                    })

        elif ref.verse_start is not None:
            # Single verse: e.g. 羅馬書3:23
            verse = await postgres.get_verse(
                book_id=ref.book_id,
                chapter_num=ref.chapter,
                verse_num=ref.verse_start,
            )
            if verse:
                cid = f"{ref.book_id}:{ref.chapter}:{ref.verse_start}"
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append({
                        "id": cid,
                        "content": f"{verse['verse']}. {verse['text']}",
                        "title": verse.get("pericope_title", ""),
                        "book_name": verse["book_name"],
                        "chapter_num": ref.chapter,
                        "verse_range": str(ref.verse_start),
                        "source_strategy": "verse_direct",
                        "weight": 1.0,
                    })

        else:
            # Chapter only: e.g. 創世記第1章 → fall back to pericope-level
            pericopes = await postgres.search_pericopes_by_verse_ref(
                book_id=ref.book_id,
                chapter_num=ref.chapter,
                verse_num=None,
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

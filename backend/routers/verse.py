"""
Verse and chapter lookup endpoints (design §2.23).

/verse returns the whole unit holding a verse (a merged unit once, its label
naming the range; a mid-verse heading listed with its offset), or for an omitted
slot 「本譯本此節從缺」 with the variant footnote; an external verse number
resolves through ref_aliases, and one that resolves to nothing is a 404.
/chapter returns the chapter's passages in canonical order plus its
superscription and book division texts.
"""

from fastapi import APIRouter, HTTPException

from database import content, postgres
from models.response import ChapterResponse, MidHeading, VerseResponse
from ragcommon import books, ids
from ragcommon.versification import VersificationError, default_versification
from serving import context

router = APIRouter(prefix="/api/v1/verse", tags=["verse"])


def _known_book(book_id: str) -> None:
    if not books.is_book_id(book_id):
        raise HTTPException(status_code=404, detail=f"找不到書卷 {book_id}")


@router.get("/{book_id}/{chapter}", response_model=ChapterResponse, summary="取得章節內容")
async def get_chapter(book_id: str, chapter: int):
    """取得指定書卷章節的段落（依正典順序）、篇題與卷分隔。"""
    build_id = context.active().build.build_id
    _known_book(book_id)
    row = await postgres.chapter_row(book_id, chapter) if chapter >= 1 else None
    if not row:
        raise HTTPException(status_code=404, detail=f"找不到 {book_id} 第{chapter}章")
    passages = await postgres.chapter_passages(book_id, chapter)
    keep = ("id", "pericope_id", "title", "content", "verse_range", "start_key", "end_key")
    return ChapterResponse(
        id=row["chapter_key"], chapter_num=row["chapter"], book_name=row["name"],
        book_name_en=row["name_en"], total_verses=row["max_verse"],
        pericopes=[{k: p[k] for k in keep} for p in passages],
        chapter_texts=await postgres.chapter_texts(row["chapter_key"]), build_id=build_id)


def _resolve_slot(book_id: str, chapter: int, verse: int) -> tuple[str, str | None]:
    try:
        slot, alias = default_versification().resolve(book_id, chapter, verse)
    except (VersificationError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=f"找不到 {book_id} {chapter}:{verse}：{exc}")
    return slot, (f"{alias.external_ref}->{alias.target}" if alias else None)


@router.get("/{book_id}/{chapter}/{verse}", response_model=VerseResponse, summary="取得特定經文")
async def get_verse(book_id: str, chapter: int, verse: int):
    """取得指定書卷、章、節所在的整個節單位（合併節、缺號槽、節中標題見說明）。"""
    build_id = context.active().build.build_id
    _known_book(book_id)
    slot, alias = _resolve_slot(book_id, chapter, verse)
    try:
        [piece] = await postgres.verse_slots([slot])
    except content.ContentError as exc:
        raise HTTPException(status_code=404, detail=f"本 build 沒有 {slot}：{exc}")
    at = ids.parse(slot)
    owner = (await postgres.owner_passages([piece.unit_key]))[piece.unit_key] \
        if piece.unit_key else {"passage_id": None, "split_passage_ids": []}
    passage = (await postgres.fetch_sources([owner["passage_id"]]))[owner["passage_id"]] \
        if owner["passage_id"] else {}
    headings = await postgres.mid_headings([piece.unit_key]) if piece.unit_key else []
    return VerseResponse(
        book_id=book_id, book_name=await postgres.book_name(book_id) or "", chapter=at.chapter,
        verse=at.verse, text=piece.text, pericope_id=owner["passage_id"],
        pericope_title=passage.get("title"), verse_range=piece.label, unit_key=piece.unit_key,
        status=piece.status, footnote=piece.footnote_text, passage_id=owner["passage_id"],
        split_passage_ids=owner["split_passage_ids"], alias=alias, build_id=build_id,
        headings=[MidHeading(heading_id=h["heading_id"], offset=h["anchor_offset"],
                             text=h["text"]) for h in headings])

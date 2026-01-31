"""
Verse and chapter lookup endpoints.
"""

from fastapi import APIRouter, HTTPException

from database import postgres
from models.response import VerseResponse, ChapterResponse

router = APIRouter(prefix="/api/v1/verse", tags=["verse"])


@router.get(
    "/{book_id}/{chapter}",
    response_model=ChapterResponse,
    summary="取得章節內容",
)
async def get_chapter(book_id: str, chapter: int):
    """取得指定書卷章節的完整內容，包含所有段落。"""
    result = await postgres.get_chapter(book_id, chapter)
    if not result:
        raise HTTPException(status_code=404, detail=f"找不到 {book_id} 第{chapter}章")
    return result


@router.get(
    "/{book_id}/{chapter}/{verse}",
    response_model=VerseResponse,
    summary="取得特定經文",
)
async def get_verse(book_id: str, chapter: int, verse: int):
    """取得指定書卷、章、節的經文內容。"""
    result = await postgres.get_verse(book_id, chapter, verse)
    if not result:
        raise HTTPException(status_code=404, detail=f"找不到 {book_id} {chapter}:{verse}")
    return result

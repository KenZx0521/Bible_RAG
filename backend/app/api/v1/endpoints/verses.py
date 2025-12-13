"""Verses endpoint."""

import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.orm import Book, Verse
from app.models.schemas import (
    VerseBase,
    VerseDetail,
    VerseList,
    VerseSearchResult,
)

router = APIRouter()


@router.get("/search", response_model=VerseSearchResult)
async def search_verses(
    db: DbSession,
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
    book_id: int | None = Query(None, description="Filter by book ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """Search for verses containing the query text.

    Uses ILIKE for Chinese text search (PostgreSQL FTS 'simple' config
    doesn't tokenize Chinese characters properly).
    """
    offset = (page - 1) * page_size

    # Build base query with ILIKE for Chinese text search
    # FTS with 'simple' config doesn't work well with Chinese
    base_query = (
        select(Verse)
        .options(selectinload(Verse.book))
        .where(Verse.text.ilike(f"%{q}%"))
    )

    if book_id is not None:
        base_query = base_query.where(Verse.book_id == book_id)

    # Count total matches
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        base_query.order_by(Verse.book_id, Verse.chapter, Verse.verse)
        .offset(offset)
        .limit(page_size)
    )
    verses = result.scalars().all()

    verse_list = [
        VerseBase(
            id=v.id,
            book_id=v.book_id,
            book_name=v.book.name_zh if v.book else "",
            chapter=v.chapter,
            verse=v.verse,
            text=v.text,
            reference=f"{v.book.name_zh} {v.chapter}:{v.verse}" if v.book else "",
        )
        for v in verses
    ]

    return VerseSearchResult(
        query=q,
        verses=verse_list,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get("", response_model=VerseList)
async def list_verses(
    db: DbSession,
    book_id: int | None = Query(None, description="Filter by book ID"),
    chapter: int | None = Query(None, ge=1, description="Filter by chapter"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List verses with pagination."""
    offset = (page - 1) * page_size

    # Build query
    base_query = select(Verse).options(selectinload(Verse.book))
    if book_id is not None:
        base_query = base_query.where(Verse.book_id == book_id)
    if chapter is not None:
        base_query = base_query.where(Verse.chapter == chapter)

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        base_query.order_by(Verse.book_id, Verse.chapter, Verse.verse)
        .offset(offset)
        .limit(page_size)
    )
    verses = result.scalars().all()

    verse_list = [
        VerseBase(
            id=v.id,
            book_id=v.book_id,
            book_name=v.book.name_zh if v.book else "",
            chapter=v.chapter,
            verse=v.verse,
            text=v.text,
            reference=f"{v.book.name_zh} {v.chapter}:{v.verse}" if v.book else "",
        )
        for v in verses
    ]

    return VerseList(
        verses=verse_list,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{verse_id}", response_model=VerseDetail)
async def get_verse(verse_id: int, db: DbSession):
    """Get a verse by ID."""
    result = await db.execute(
        select(Verse)
        .where(Verse.id == verse_id)
        .options(selectinload(Verse.book), selectinload(Verse.pericope))
    )
    verse = result.scalar_one_or_none()

    if not verse:
        raise HTTPException(status_code=404, detail="Verse not found")

    return VerseDetail(
        id=verse.id,
        book_id=verse.book_id,
        book_name=verse.book.name_zh if verse.book else "",
        chapter=verse.chapter,
        verse=verse.verse,
        text=verse.text,
        reference=f"{verse.book.name_zh} {verse.chapter}:{verse.verse}" if verse.book else "",
        pericope_id=verse.pericope.id if verse.pericope else None,
        pericope_title=verse.pericope.title if verse.pericope else None,
    )

"""Pericopes endpoint."""

import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.orm import Pericope, Verse
from app.models.schemas import (
    PericopeBase,
    PericopeDetail,
    PericopeList,
    VerseBase,
)

router = APIRouter()


@router.get("", response_model=PericopeList)
async def list_pericopes(
    db: DbSession,
    book_id: int | None = Query(None, description="Filter by book ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List pericopes with pagination."""
    offset = (page - 1) * page_size

    # Build query
    base_query = select(Pericope).options(selectinload(Pericope.book))
    if book_id is not None:
        base_query = base_query.where(Pericope.book_id == book_id)

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        base_query.order_by(Pericope.book_id, Pericope.chapter_start, Pericope.verse_start)
        .offset(offset)
        .limit(page_size)
    )
    pericopes = result.scalars().all()

    pericope_list = [
        PericopeBase(
            id=p.id,
            book_id=p.book_id,
            book_name=p.book.name_zh if p.book else "",
            title=p.title,
            reference=f"{p.book.name_zh} {p.reference}" if p.book else "",
            chapter_start=p.chapter_start,
            verse_start=p.verse_start,
            chapter_end=p.chapter_end,
            verse_end=p.verse_end,
        )
        for p in pericopes
    ]

    return PericopeList(
        pericopes=pericope_list,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{pericope_id}", response_model=PericopeDetail)
async def get_pericope(pericope_id: int, db: DbSession):
    """Get a pericope with its verses."""
    result = await db.execute(
        select(Pericope)
        .where(Pericope.id == pericope_id)
        .options(selectinload(Pericope.book), selectinload(Pericope.verses))
    )
    pericope = result.scalar_one_or_none()

    if not pericope:
        raise HTTPException(status_code=404, detail="Pericope not found")

    book_name = pericope.book.name_zh if pericope.book else ""

    verses = [
        VerseBase(
            id=v.id,
            book_id=v.book_id,
            book_name=book_name,
            chapter=v.chapter,
            verse=v.verse,
            text=v.text,
            reference=f"{book_name} {v.chapter}:{v.verse}",
        )
        for v in sorted(pericope.verses, key=lambda x: (x.chapter, x.verse))
    ]

    return PericopeDetail(
        id=pericope.id,
        book_id=pericope.book_id,
        book_name=book_name,
        title=pericope.title,
        reference=f"{book_name} {pericope.reference}",
        chapter_start=pericope.chapter_start,
        verse_start=pericope.verse_start,
        chapter_end=pericope.chapter_end,
        verse_end=pericope.verse_end,
        summary=pericope.summary,
        verses=verses,
    )

"""Books endpoint."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.orm import Book, Pericope, Verse
from app.models.schemas import (
    BookBase,
    BookChapters,
    BookDetail,
    BookList,
    BookPericopes,
    BookVerses,
    ChapterInfo,
    PericopeBase,
    VerseBase,
)

router = APIRouter()


@router.get("", response_model=BookList)
async def list_books(db: DbSession):
    """Get all Bible books."""
    result = await db.execute(select(Book).order_by(Book.order_index))
    books = result.scalars().all()
    return BookList(
        books=[BookBase.model_validate(book) for book in books],
        total=len(books),
    )


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(book_id: int, db: DbSession):
    """Get a specific book by ID with statistics."""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get chapter count
    chapter_count_result = await db.execute(
        select(func.count(distinct(Verse.chapter))).where(Verse.book_id == book_id)
    )
    chapter_count = chapter_count_result.scalar() or 0

    # Get verse count
    verse_count_result = await db.execute(
        select(func.count()).where(Verse.book_id == book_id)
    )
    verse_count = verse_count_result.scalar() or 0

    # Get pericope count
    pericope_count_result = await db.execute(
        select(func.count()).where(Pericope.book_id == book_id)
    )
    pericope_count = pericope_count_result.scalar() or 0

    return BookDetail(
        id=book.id,
        name_zh=book.name_zh,
        abbrev_zh=book.abbrev_zh,
        testament=book.testament,
        order_index=book.order_index,
        chapter_count=chapter_count,
        verse_count=verse_count,
        pericope_count=pericope_count,
    )


@router.get("/{book_id}/chapters", response_model=BookChapters)
async def get_book_chapters(book_id: int, db: DbSession):
    """Get all chapters in a book with verse counts."""
    # Check if book exists
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get chapters with verse counts
    result = await db.execute(
        select(Verse.chapter, func.count().label("verse_count"))
        .where(Verse.book_id == book_id)
        .group_by(Verse.chapter)
        .order_by(Verse.chapter)
    )
    chapters_data = result.all()

    chapters = [
        ChapterInfo(chapter=row.chapter, verse_count=row.verse_count)
        for row in chapters_data
    ]

    return BookChapters(
        book_id=book.id,
        book_name=book.name_zh,
        chapters=chapters,
        total=len(chapters),
    )


@router.get("/{book_id}/pericopes", response_model=BookPericopes)
async def get_book_pericopes(book_id: int, db: DbSession):
    """Get all pericopes in a book."""
    # Check if book exists
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Get pericopes
    result = await db.execute(
        select(Pericope)
        .where(Pericope.book_id == book_id)
        .order_by(Pericope.chapter_start, Pericope.verse_start)
    )
    pericopes = result.scalars().all()

    pericope_list = [
        PericopeBase(
            id=p.id,
            book_id=book.id,
            book_name=book.name_zh,
            title=p.title,
            reference=f"{book.name_zh} {p.reference}",
            chapter_start=p.chapter_start,
            verse_start=p.verse_start,
            chapter_end=p.chapter_end,
            verse_end=p.verse_end,
        )
        for p in pericopes
    ]

    return BookPericopes(
        book_id=book.id,
        book_name=book.name_zh,
        pericopes=pericope_list,
        total=len(pericope_list),
    )


@router.get("/{book_id}/verses", response_model=BookVerses)
async def get_book_verses(
    book_id: int,
    db: DbSession,
    chapter: int | None = Query(None, ge=1, description="Filter by chapter"),
):
    """Get all verses in a book, optionally filtered by chapter."""
    # Check if book exists
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Build query
    query = select(Verse).where(Verse.book_id == book_id)
    if chapter is not None:
        query = query.where(Verse.chapter == chapter)
    query = query.order_by(Verse.chapter, Verse.verse)

    result = await db.execute(query)
    verses = result.scalars().all()

    verse_list = [
        VerseBase(
            id=v.id,
            book_id=book.id,
            book_name=book.name_zh,
            chapter=v.chapter,
            verse=v.verse,
            text=v.text,
            reference=f"{book.name_zh} {v.chapter}:{v.verse}",
        )
        for v in verses
    ]

    return BookVerses(
        book_id=book.id,
        book_name=book.name_zh,
        chapter=chapter,
        verses=verse_list,
        total=len(verse_list),
    )

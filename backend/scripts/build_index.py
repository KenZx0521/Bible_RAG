"""Build index CLI for Bible RAG system.

Usage:
    python -m scripts.build_index --pdf backend/pdf/cmn-cu89t_a4.pdf
    python -m scripts.build_index --json bible_parsed.json --skip-parse
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.models.orm import Book, Chapter, Pericope, Verse
from scripts.pdf_parser import BiblePDFParser


async def init_database(engine) -> None:
    """Initialize database with required extensions."""
    async with engine.begin() as conn:
        # Enable extensions
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        # Create tables
        from app.models.orm import Base
        await conn.run_sync(Base.metadata.create_all)

    print("Database initialized with extensions and tables")


async def clear_tables(session: AsyncSession) -> None:
    """Clear all Bible data tables."""
    print("Clearing existing data...")

    # Delete in order to respect foreign keys
    await session.execute(text("DELETE FROM verse_entities"))
    await session.execute(text("DELETE FROM verse_topics"))
    await session.execute(text("DELETE FROM verses"))
    await session.execute(text("DELETE FROM pericopes"))
    await session.execute(text("DELETE FROM chapters"))
    await session.execute(text("DELETE FROM books"))
    await session.execute(text("DELETE FROM entities"))
    await session.execute(text("DELETE FROM topics"))

    await session.commit()
    print("Tables cleared")


async def import_from_json(
    session: AsyncSession,
    json_path: Path,
    verbose: bool = False,
) -> None:
    """Import parsed Bible data from JSON to PostgreSQL."""
    print(f"Loading data from {json_path}...")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    metadata = data["metadata"]
    print(f"  Found {metadata['total_books']} books")
    print(f"  Found {metadata['total_pericopes']} pericopes")
    print(f"  Found {metadata['total_verses']} verses")

    books_data = data["books"]
    total_pericopes = 0
    total_verses = 0

    for book_data in books_data:
        if verbose:
            print(f"  Importing: {book_data['name_zh']}")

        # Create book
        book = Book(
            name_zh=book_data["name_zh"],
            abbrev_zh=book_data["abbrev_zh"],
            testament=book_data["testament"],
            order_index=book_data["order_index"],
        )
        session.add(book)
        await session.flush()  # Get book.id

        # Create chapters and pericopes
        for chapter_data in book_data["chapters"]:
            chapter = Chapter(
                book_id=book.id,
                number=chapter_data["number"],
            )
            session.add(chapter)
            await session.flush()

            for pericope_data in chapter_data["pericopes"]:
                pericope = Pericope(
                    book_id=book.id,
                    chapter_start=pericope_data["chapter_start"],
                    verse_start=pericope_data["verse_start"],
                    chapter_end=pericope_data["chapter_end"],
                    verse_end=pericope_data["verse_end"],
                    title=pericope_data["title"],
                )
                session.add(pericope)
                await session.flush()
                total_pericopes += 1

                # Create verses
                for verse_data in pericope_data["verses"]:
                    verse = Verse(
                        book_id=book.id,
                        chapter=verse_data["chapter"],
                        verse=verse_data["verse"],
                        text=verse_data["text"],
                        pericope_id=pericope.id,
                    )
                    session.add(verse)
                    total_verses += 1

        await session.commit()

    print(f"Imported {len(books_data)} books, {total_pericopes} pericopes, {total_verses} verses")


async def generate_embeddings(session: AsyncSession, verbose: bool = False) -> None:
    """Generate embeddings for all pericopes using bge-m3."""
    print("Generating embeddings...")

    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError:
        print("FlagEmbedding not installed. Run: pip install FlagEmbedding")
        print("Skipping embedding generation.")
        return

    # Load model
    print("Loading bge-m3 model (this may take a while)...")
    model = BGEM3FlagModel(
        settings.EMBED_MODEL_NAME,
        use_fp16=settings.EMBED_USE_FP16,
    )
    print("Model loaded")

    # Get all pericopes without embeddings
    from sqlalchemy import select
    result = await session.execute(
        select(Pericope).where(Pericope.embedding.is_(None))
    )
    pericopes = result.scalars().all()
    print(f"Found {len(pericopes)} pericopes to embed")

    if not pericopes:
        print("No pericopes need embedding")
        return

    # Process in batches
    batch_size = settings.EMBED_BATCH_SIZE
    total_batches = (len(pericopes) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(pericopes))
        batch = pericopes[start_idx:end_idx]

        if verbose or batch_num % 10 == 0:
            print(f"  Processing batch {batch_num + 1}/{total_batches}")

        # Prepare texts (combine title and verse texts)
        texts = []
        for pericope in batch:
            # Get verse texts
            verse_result = await session.execute(
                select(Verse.text).where(Verse.pericope_id == pericope.id)
            )
            verse_texts = verse_result.scalars().all()
            full_text = f"{pericope.title}\n" + "\n".join(verse_texts)
            texts.append(full_text)

        # Generate embeddings
        output = model.encode(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)
        embeddings = output["dense_vecs"]

        # Update pericopes
        for pericope, embedding in zip(batch, embeddings):
            pericope.embedding = embedding.tolist()

        await session.commit()

    print(f"Generated embeddings for {len(pericopes)} pericopes")


async def build_index(
    pdf_path: Path | None = None,
    json_path: Path | None = None,
    output_json: Path | None = None,
    drop_existing: bool = False,
    skip_parse: bool = False,
    skip_embed: bool = False,
    verbose: bool = False,
) -> None:
    """Main build index function."""
    # Create engine and session
    engine = create_async_engine(settings.DATABASE_URL, echo=verbose)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # Initialize database
        await init_database(engine)

        async with async_session() as session:
            # Clear existing data if requested
            if drop_existing:
                await clear_tables(session)

            # Parse PDF if needed
            if not skip_parse and pdf_path:
                print(f"\n=== Parsing PDF: {pdf_path} ===")
                parser = BiblePDFParser(pdf_path)
                parser.parse()

                # Save to JSON
                output = output_json or Path("bible_parsed.json")
                parser.save_json(output)
                json_path = output

            # Import from JSON
            if json_path and json_path.exists():
                print(f"\n=== Importing from JSON: {json_path} ===")
                await import_from_json(session, json_path, verbose)
            else:
                print("No JSON file found. Please parse PDF first or provide --json path.")
                return

            # Generate embeddings
            if not skip_embed:
                print("\n=== Generating Embeddings ===")
                await generate_embeddings(session, verbose)
            else:
                print("\n=== Skipping Embedding Generation ===")

            print("\n=== Build Index Complete ===")

    finally:
        await engine.dispose()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Build Bible RAG index from PDF or JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from PDF
  python -m scripts.build_index --pdf backend/pdf/cmn-cu89t_a4.pdf --drop-existing

  # Skip PDF parsing, use existing JSON
  python -m scripts.build_index --json bible_parsed.json --skip-parse

  # Skip embedding generation
  python -m scripts.build_index --json bible_parsed.json --skip-parse --skip-embed
        """,
    )

    parser.add_argument(
        "--pdf",
        type=Path,
        help="Path to Bible PDF file",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Path to parsed JSON file (input or output)",
    )
    parser.add_argument(
        "-o", "--output-json",
        type=Path,
        default=Path("bible_parsed.json"),
        help="Output JSON file path (default: bible_parsed.json)",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing data before import",
    )
    parser.add_argument(
        "--skip-parse",
        action="store_true",
        help="Skip PDF parsing step",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Skip embedding generation step",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.skip_parse and not args.pdf:
        parser.error("--pdf is required unless --skip-parse is specified")

    if args.skip_parse and not args.json:
        args.json = args.output_json

    # Run
    asyncio.run(
        build_index(
            pdf_path=args.pdf,
            json_path=args.json,
            output_json=args.output_json,
            drop_existing=args.drop_existing,
            skip_parse=args.skip_parse,
            skip_embed=args.skip_embed,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()

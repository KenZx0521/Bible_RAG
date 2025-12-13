"""Entity extraction script using LLM.

This script extracts entities (Person, Place, Group, Event) and topics
from Bible pericopes using Ollama LLM.

Usage:
    cd backend
    python -m scripts.entity_extractor
    python -m scripts.entity_extractor --batch-size 5 --no-resume
    python -m scripts.entity_extractor --limit 100  # Process only first 100 pericopes
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.models.orm import Book, Pericope, Verse, Entity, VerseEntity, Topic, VerseTopic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Checkpoint file
CHECKPOINT_FILE = Path("entity_extraction_checkpoint.json")

# Extraction system prompt
EXTRACTION_SYSTEM_PROMPT = """你是聖經文本分析專家。請分析給定的聖經段落，提取以下實體：

1. **人物 (PERSON)**: 具名人物（如亞伯拉罕、摩西、耶穌、保羅、大衛）
2. **地點 (PLACE)**: 地理位置（如耶路撒冷、埃及、加利利、伯利恆）
3. **群體 (GROUP)**: 族群或組織（如法利賽人、以色列人、門徒、利未人）
4. **事件 (EVENT)**: 重要事件（如出埃及、復活、五旬節、最後晚餐）
5. **主題 (TOPIC)**: 教義或主題概念

主題類型：
- DOCTRINE: 教義（如救贖、恩典、信心、稱義）
- MORAL: 道德（如饒恕、愛、誠實、謙卑）
- HISTORICAL: 歷史（如創世、洪水、出埃及）
- PROPHETIC: 預言（如彌賽亞預言、末世）
- OTHER: 其他

請以嚴格的 JSON 格式回應：
{
    "persons": [{"name": "名稱", "role": "角色描述"}],
    "places": [{"name": "名稱"}],
    "groups": [{"name": "名稱"}],
    "events": [{"name": "名稱"}],
    "topics": [{"name": "名稱", "type": "DOCTRINE|MORAL|HISTORICAL|PROPHETIC|OTHER"}]
}

注意：
- 只提取在經文中明確提及的實體
- 名稱使用繁體中文
- 如果某類實體不存在，返回空陣列 []
- 只輸出 JSON，不要有其他文字或解釋"""


class EntityExtractor:
    """Extract entities from Bible pericopes using LLM."""

    def __init__(
        self,
        session: AsyncSession,
        batch_size: int = 10,
    ):
        self.session = session
        self.batch_size = batch_size
        self.entity_cache: dict[tuple[str, str], int] = {}  # (name, type) -> id
        self.topic_cache: dict[str, int] = {}  # name -> id
        self.llm_client = None

    async def _init_llm(self):
        """Initialize LLM client."""
        if self.llm_client is None:
            from app.services.llm_client import OllamaLLMClient
            self.llm_client = OllamaLLMClient()

    async def extract_all(
        self,
        resume: bool = True,
        limit: int | None = None,
    ) -> dict[str, int]:
        """Extract entities from all pericopes.

        Args:
            resume: Whether to resume from checkpoint
            limit: Optional limit on number of pericopes to process

        Returns:
            Statistics dict with counts
        """
        await self._init_llm()

        # Load checkpoint
        processed_ids: set[int] = set()
        if resume and CHECKPOINT_FILE.exists():
            try:
                checkpoint = json.loads(CHECKPOINT_FILE.read_text())
                processed_ids = set(checkpoint.get("processed_ids", []))
                logger.info(f"Resuming from checkpoint: {len(processed_ids)} already processed")
            except json.JSONDecodeError:
                logger.warning("Invalid checkpoint file, starting fresh")

        # Get pericopes to process
        query = select(Pericope).order_by(Pericope.id)
        if limit:
            query = query.limit(limit)

        result = await self.session.execute(query)
        all_pericopes = result.scalars().all()
        total = len(all_pericopes)

        logger.info(f"Total pericopes: {total}, already processed: {len(processed_ids)}")

        stats = {
            "total": total,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "entities_created": 0,
            "topics_created": 0,
        }

        for i, pericope in enumerate(all_pericopes):
            if pericope.id in processed_ids:
                stats["skipped"] += 1
                continue

            try:
                counts = await self._process_pericope(pericope)
                processed_ids.add(pericope.id)
                stats["processed"] += 1
                stats["entities_created"] += counts.get("entities", 0)
                stats["topics_created"] += counts.get("topics", 0)

            except Exception as e:
                logger.error(f"Error processing pericope {pericope.id}: {e}")
                stats["errors"] += 1
                continue

            # Commit and save checkpoint every batch
            if (i + 1) % self.batch_size == 0:
                await self.session.commit()
                self._save_checkpoint(processed_ids)
                logger.info(
                    f"Progress: {i + 1}/{total} "
                    f"(processed: {stats['processed']}, errors: {stats['errors']})"
                )

        # Final commit and checkpoint
        await self.session.commit()
        self._save_checkpoint(processed_ids)

        logger.info(f"Extraction complete: {stats}")
        return stats

    def _save_checkpoint(self, processed_ids: set[int]) -> None:
        """Save checkpoint to file."""
        CHECKPOINT_FILE.write_text(json.dumps({
            "processed_ids": list(processed_ids),
        }))

    async def _process_pericope(self, pericope: Pericope) -> dict[str, int]:
        """Process a single pericope.

        Args:
            pericope: Pericope to process

        Returns:
            Counts of created entities and topics
        """
        # Get verses for this pericope
        result = await self.session.execute(
            select(Verse)
            .where(Verse.pericope_id == pericope.id)
            .order_by(Verse.chapter, Verse.verse)
        )
        verses = result.scalars().all()

        if not verses:
            return {"entities": 0, "topics": 0}

        # Get book name
        book_result = await self.session.execute(
            select(Book).where(Book.id == pericope.book_id)
        )
        book = book_result.scalar_one_or_none()
        book_name = book.name_zh if book else ""

        # Build context for LLM
        text_context = f"書卷：{book_name}\n"
        text_context += f"段落標題：{pericope.title}\n\n"
        text_context += "經文內容：\n"
        for v in verses:
            text_context += f"{v.chapter}:{v.verse} {v.text}\n"

        # Call LLM for extraction
        prompt = f"請分析以下聖經段落，提取實體和主題：\n\n{text_context}"

        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning(f"LLM call failed for pericope {pericope.id}: {e}")
            return {"entities": 0, "topics": 0}

        # Parse JSON response
        data = self._parse_llm_response(response)
        if not data:
            return {"entities": 0, "topics": 0}

        # Store entities and create relationships
        counts = await self._store_entities(verses, data)
        return counts

    def _parse_llm_response(self, response: str) -> dict | None:
        """Parse LLM JSON response.

        Args:
            response: Raw LLM response

        Returns:
            Parsed dict or None if parsing fails
        """
        try:
            # Try direct JSON parse
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from response
        try:
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        logger.warning(f"Failed to parse LLM response: {response[:200]}...")
        return None

    async def _store_entities(
        self,
        verses: list[Verse],
        data: dict,
    ) -> dict[str, int]:
        """Store extracted entities in PostgreSQL.

        Args:
            verses: List of verses
            data: Extracted entity data

        Returns:
            Counts of created items
        """
        entity_count = 0
        topic_count = 0
        verse_ids = [v.id for v in verses]

        # Process persons
        for person in data.get("persons", []):
            if not person.get("name"):
                continue
            entity_id = await self._get_or_create_entity(
                person["name"], "PERSON"
            )
            if entity_id:
                entity_count += 1
                for verse_id in verse_ids:
                    await self._create_verse_entity(
                        verse_id, entity_id, person.get("role")
                    )

        # Process places
        for place in data.get("places", []):
            if not place.get("name"):
                continue
            entity_id = await self._get_or_create_entity(
                place["name"], "PLACE"
            )
            if entity_id:
                entity_count += 1
                for verse_id in verse_ids:
                    await self._create_verse_entity(verse_id, entity_id, None)

        # Process groups
        for group in data.get("groups", []):
            if not group.get("name"):
                continue
            entity_id = await self._get_or_create_entity(
                group["name"], "GROUP"
            )
            if entity_id:
                entity_count += 1
                for verse_id in verse_ids:
                    await self._create_verse_entity(verse_id, entity_id, None)

        # Process events
        for event in data.get("events", []):
            if not event.get("name"):
                continue
            entity_id = await self._get_or_create_entity(
                event["name"], "EVENT"
            )
            if entity_id:
                entity_count += 1
                for verse_id in verse_ids:
                    await self._create_verse_entity(verse_id, entity_id, None)

        # Process topics
        for topic in data.get("topics", []):
            if not topic.get("name"):
                continue
            topic_type = topic.get("type", "OTHER")
            if topic_type not in ("DOCTRINE", "MORAL", "HISTORICAL", "PROPHETIC", "OTHER"):
                topic_type = "OTHER"

            topic_id = await self._get_or_create_topic(
                topic["name"], topic_type
            )
            if topic_id:
                topic_count += 1
                for verse_id in verse_ids:
                    await self._create_verse_topic(verse_id, topic_id, 1.0)

        return {"entities": entity_count, "topics": topic_count}

    async def _get_or_create_entity(
        self,
        name: str,
        entity_type: str,
    ) -> int | None:
        """Get or create an entity.

        Args:
            name: Entity name
            entity_type: PERSON, PLACE, GROUP, or EVENT

        Returns:
            Entity ID or None
        """
        # Check cache
        cache_key = (name, entity_type)
        if cache_key in self.entity_cache:
            return self.entity_cache[cache_key]

        # Check database
        result = await self.session.execute(
            select(Entity).where(
                Entity.name == name,
                Entity.type == entity_type,
            )
        )
        entity = result.scalar_one_or_none()

        if entity is None:
            # Create new entity
            entity = Entity(name=name, type=entity_type)
            self.session.add(entity)
            await self.session.flush()

        self.entity_cache[cache_key] = entity.id
        return entity.id

    async def _get_or_create_topic(
        self,
        name: str,
        topic_type: str,
    ) -> int | None:
        """Get or create a topic.

        Args:
            name: Topic name
            topic_type: DOCTRINE, MORAL, HISTORICAL, PROPHETIC, or OTHER

        Returns:
            Topic ID or None
        """
        # Check cache
        if name in self.topic_cache:
            return self.topic_cache[name]

        # Check database
        result = await self.session.execute(
            select(Topic).where(Topic.name == name)
        )
        topic = result.scalar_one_or_none()

        if topic is None:
            # Create new topic
            topic = Topic(name=name, type=topic_type)
            self.session.add(topic)
            await self.session.flush()

        self.topic_cache[name] = topic.id
        return topic.id

    async def _create_verse_entity(
        self,
        verse_id: int,
        entity_id: int,
        role: str | None,
    ) -> None:
        """Create verse-entity association (upsert).

        Args:
            verse_id: Verse ID
            entity_id: Entity ID
            role: Optional role description
        """
        stmt = insert(VerseEntity).values(
            verse_id=verse_id,
            entity_id=entity_id,
            role=role,
        ).on_conflict_do_nothing()
        await self.session.execute(stmt)

    async def _create_verse_topic(
        self,
        verse_id: int,
        topic_id: int,
        weight: float,
    ) -> None:
        """Create verse-topic association (upsert).

        Args:
            verse_id: Verse ID
            topic_id: Topic ID
            weight: Relevance weight
        """
        stmt = insert(VerseTopic).values(
            verse_id=verse_id,
            topic_id=topic_id,
            weight=weight,
        ).on_conflict_do_nothing()
        await self.session.execute(stmt)


async def main(
    resume: bool = True,
    batch_size: int = 10,
    limit: int | None = None,
) -> None:
    """Main entry point.

    Args:
        resume: Whether to resume from checkpoint
        batch_size: Number of pericopes per batch
        limit: Optional limit on pericopes to process
    """
    # Create async engine
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        extractor = EntityExtractor(session, batch_size=batch_size)
        stats = await extractor.extract_all(resume=resume, limit=limit)
        print(f"\nExtraction Statistics:")
        print(f"  Total pericopes: {stats['total']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Skipped (already done): {stats['skipped']}")
        print(f"  Errors: {stats['errors']}")
        print(f"  Entities created: {stats['entities_created']}")
        print(f"  Topics created: {stats['topics_created']}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract entities from Bible pericopes using LLM"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh, ignore checkpoint",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of pericopes per batch (default: 10)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of pericopes to process",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(main(
        resume=not args.no_resume,
        batch_size=args.batch_size,
        limit=args.limit,
    ))

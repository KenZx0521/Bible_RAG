"""Graph-based retriever using Neo4j knowledge graph."""

import logging
from dataclasses import dataclass, field

from app.core.neo4j_client import Neo4jClient
from app.services.llm_client import OllamaLLMClient

logger = logging.getLogger(__name__)


@dataclass
class GraphRetrievalResult:
    """Result from graph retrieval."""

    id: int  # pericope_id
    book_id: int
    book_name: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    title: str
    text: str
    score: float = 0.0
    graph_context: dict = field(default_factory=dict)

    @property
    def reference(self) -> str:
        """Get formatted reference string."""
        if self.chapter_start == self.chapter_end:
            return f"{self.book_name} {self.chapter_start}:{self.verse_start}-{self.verse_end}"
        return f"{self.book_name} {self.chapter_start}:{self.verse_start}-{self.chapter_end}:{self.verse_end}"


class GraphRetriever:
    """Graph-based retriever using Neo4j for entity-based retrieval."""

    def __init__(self, llm_client: OllamaLLMClient | None = None):
        """Initialize graph retriever.

        Args:
            llm_client: Optional LLM client for entity extraction from queries
        """
        self.llm_client = llm_client

    async def retrieve(
        self,
        query: str,
        query_type: str,
        top_k: int = 20,
    ) -> list[GraphRetrievalResult]:
        """Retrieve pericopes based on graph traversal.

        Args:
            query: User query text
            query_type: Classified query type (PERSON_QUESTION, TOPIC_QUESTION, etc.)
            top_k: Number of results to return

        Returns:
            List of graph retrieval results
        """
        if not Neo4jClient.is_available():
            logger.debug("Neo4j not available, skipping graph retrieval")
            return []

        # Extract entity names from query
        entities = await self._extract_entities_from_query(query, query_type)

        if not entities:
            logger.debug(f"No entities extracted from query: {query}")
            return []

        logger.debug(f"Extracted entities: {entities}")

        # Execute appropriate query based on type
        if query_type == "PERSON_QUESTION":
            return await self._retrieve_by_person(entities, top_k)
        elif query_type == "TOPIC_QUESTION":
            return await self._retrieve_by_topic(entities, top_k)
        elif query_type == "EVENT_QUESTION":
            return await self._retrieve_by_event(entities, top_k)
        else:
            # General: combine all entity types
            return await self._retrieve_general(entities, top_k)

    async def _extract_entities_from_query(
        self,
        query: str,
        query_type: str,
    ) -> list[str]:
        """Extract entity names from query using LLM.

        Args:
            query: User query text
            query_type: Query type for context

        Returns:
            List of entity names
        """
        if not self.llm_client:
            # Fallback: use the query as-is
            return [query]

        system_prompt = """從用戶問題中提取關鍵實體名稱（人物、地點、事件、主題）。
只輸出實體名稱，以逗號分隔。不要有其他文字或解釋。
如果問題是關於人物，輸出人物名稱。
如果問題是關於主題，輸出主題關鍵詞。
如果問題是關於事件，輸出事件名稱。

範例：
問題: 亞伯拉罕是誰？
輸出: 亞伯拉罕

問題: 聖經怎麼談饒恕？
輸出: 饒恕

問題: 出埃及記講什麼？
輸出: 出埃及"""

        try:
            response = await self.llm_client.generate(
                prompt=f"問題類型: {query_type}\n問題: {query}",
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=100,
            )

            # Parse comma-separated response
            entities = [e.strip() for e in response.strip().split(",")]
            return [e for e in entities if e and len(e) > 0]

        except Exception as e:
            logger.warning(f"Entity extraction failed: {e}")
            return [query]

    async def _retrieve_by_person(
        self,
        names: list[str],
        top_k: int,
    ) -> list[GraphRetrievalResult]:
        """Retrieve pericopes by person names.

        Args:
            names: List of person names to search
            top_k: Max results

        Returns:
            List of retrieval results
        """
        # Try fulltext search first, fall back to CONTAINS
        query = """
        UNWIND $names AS name
        OPTIONAL MATCH (person:Person)
        WHERE person.name CONTAINS name OR name CONTAINS person.name
        WITH person, name
        WHERE person IS NOT NULL

        MATCH (v:Verse)-[:MENTIONS_PERSON]->(person)
        MATCH (p:Pericope)-[:HAS_VERSE]->(v)
        MATCH (b:Book {id: p.book_id})

        WITH p, b, person,
             collect(DISTINCT v.text) AS verse_texts,
             count(DISTINCT v) AS mention_count

        RETURN DISTINCT
            p.id AS id,
            p.book_id AS book_id,
            b.name_zh AS book_name,
            p.chapter_start AS chapter_start,
            p.verse_start AS verse_start,
            p.chapter_end AS chapter_end,
            p.verse_end AS verse_end,
            p.title AS title,
            verse_texts,
            mention_count,
            collect(DISTINCT person.name) AS mentioned_persons
        ORDER BY mention_count DESC
        LIMIT $limit
        """

        try:
            results = await Neo4jClient.execute_read(
                query, {"names": names, "limit": top_k}
            )
        except Exception as e:
            logger.error(f"Person retrieval failed: {e}")
            return []

        return [
            GraphRetrievalResult(
                id=r["id"],
                book_id=r["book_id"],
                book_name=r["book_name"],
                chapter_start=r["chapter_start"],
                verse_start=r["verse_start"],
                chapter_end=r["chapter_end"],
                verse_end=r["verse_end"],
                title=r["title"],
                text="\n".join(r["verse_texts"][:5]),  # First 5 verses
                score=self._calculate_score(r["mention_count"]),
                graph_context={
                    "type": "person",
                    "entities": r["mentioned_persons"],
                    "mention_count": r["mention_count"],
                },
            )
            for r in results
        ]

    async def _retrieve_by_topic(
        self,
        topics: list[str],
        top_k: int,
    ) -> list[GraphRetrievalResult]:
        """Retrieve pericopes by topic names.

        Args:
            topics: List of topic names to search
            top_k: Max results

        Returns:
            List of retrieval results
        """
        query = """
        UNWIND $topics AS topic_name
        OPTIONAL MATCH (topic:Topic)
        WHERE topic.name CONTAINS topic_name OR topic_name CONTAINS topic.name
        WITH topic, topic_name
        WHERE topic IS NOT NULL

        MATCH (v:Verse)-[r:MENTIONS_TOPIC]->(topic)
        MATCH (p:Pericope)-[:HAS_VERSE]->(v)
        MATCH (b:Book {id: p.book_id})

        WITH p, b, topic,
             collect(DISTINCT v.text) AS verse_texts,
             sum(r.weight) AS total_weight

        RETURN DISTINCT
            p.id AS id,
            p.book_id AS book_id,
            b.name_zh AS book_name,
            p.chapter_start AS chapter_start,
            p.verse_start AS verse_start,
            p.chapter_end AS chapter_end,
            p.verse_end AS verse_end,
            p.title AS title,
            verse_texts,
            total_weight,
            collect(DISTINCT topic.name) AS related_topics
        ORDER BY total_weight DESC
        LIMIT $limit
        """

        try:
            results = await Neo4jClient.execute_read(
                query, {"topics": topics, "limit": top_k}
            )
        except Exception as e:
            logger.error(f"Topic retrieval failed: {e}")
            return []

        return [
            GraphRetrievalResult(
                id=r["id"],
                book_id=r["book_id"],
                book_name=r["book_name"],
                chapter_start=r["chapter_start"],
                verse_start=r["verse_start"],
                chapter_end=r["chapter_end"],
                verse_end=r["verse_end"],
                title=r["title"],
                text="\n".join(r["verse_texts"][:5]),
                score=self._calculate_score(r["total_weight"]),
                graph_context={
                    "type": "topic",
                    "entities": r["related_topics"],
                    "weight": r["total_weight"],
                },
            )
            for r in results
        ]

    async def _retrieve_by_event(
        self,
        events: list[str],
        top_k: int,
    ) -> list[GraphRetrievalResult]:
        """Retrieve pericopes by event names.

        Args:
            events: List of event names to search
            top_k: Max results

        Returns:
            List of retrieval results
        """
        query = """
        UNWIND $events AS event_name
        OPTIONAL MATCH (event:Event)
        WHERE event.name CONTAINS event_name OR event_name CONTAINS event.name
        WITH event, event_name
        WHERE event IS NOT NULL

        MATCH (v:Verse)-[:MENTIONS_EVENT]->(event)
        MATCH (p:Pericope)-[:HAS_VERSE]->(v)
        MATCH (b:Book {id: p.book_id})

        WITH p, b, event,
             collect(DISTINCT v.text) AS verse_texts,
             count(DISTINCT v) AS mention_count

        RETURN DISTINCT
            p.id AS id,
            p.book_id AS book_id,
            b.name_zh AS book_name,
            p.chapter_start AS chapter_start,
            p.verse_start AS verse_start,
            p.chapter_end AS chapter_end,
            p.verse_end AS verse_end,
            p.title AS title,
            verse_texts,
            mention_count,
            collect(DISTINCT event.name) AS related_events
        ORDER BY mention_count DESC
        LIMIT $limit
        """

        try:
            results = await Neo4jClient.execute_read(
                query, {"events": events, "limit": top_k}
            )
        except Exception as e:
            logger.error(f"Event retrieval failed: {e}")
            return []

        return [
            GraphRetrievalResult(
                id=r["id"],
                book_id=r["book_id"],
                book_name=r["book_name"],
                chapter_start=r["chapter_start"],
                verse_start=r["verse_start"],
                chapter_end=r["chapter_end"],
                verse_end=r["verse_end"],
                title=r["title"],
                text="\n".join(r["verse_texts"][:5]),
                score=self._calculate_score(r["mention_count"]),
                graph_context={
                    "type": "event",
                    "entities": r["related_events"],
                    "mention_count": r["mention_count"],
                },
            )
            for r in results
        ]

    async def _retrieve_general(
        self,
        keywords: list[str],
        top_k: int,
    ) -> list[GraphRetrievalResult]:
        """General retrieval across all entity types.

        Args:
            keywords: Keywords to search
            top_k: Max results

        Returns:
            Combined and deduplicated results
        """
        # Get results from each type
        k_per_type = max(top_k // 3, 5)

        all_results: list[GraphRetrievalResult] = []

        person_results = await self._retrieve_by_person(keywords, k_per_type)
        topic_results = await self._retrieve_by_topic(keywords, k_per_type)
        event_results = await self._retrieve_by_event(keywords, k_per_type)

        all_results.extend(person_results)
        all_results.extend(topic_results)
        all_results.extend(event_results)

        # Deduplicate by pericope ID
        seen_ids: set[int] = set()
        unique_results: list[GraphRetrievalResult] = []

        for r in sorted(all_results, key=lambda x: x.score, reverse=True):
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                unique_results.append(r)

        return unique_results[:top_k]

    def _calculate_score(self, weight: float) -> float:
        """Calculate normalized retrieval score.

        Args:
            weight: Raw weight/count

        Returns:
            Normalized score (0-1)
        """
        # Normalize: divide by 10 and cap at 1.0
        return min(1.0, weight / 10.0)


# Singleton instance
_graph_retriever: GraphRetriever | None = None


async def get_graph_retriever(llm_client: OllamaLLMClient | None = None) -> GraphRetriever:
    """Get or create graph retriever singleton.

    Args:
        llm_client: Optional LLM client

    Returns:
        GraphRetriever instance
    """
    global _graph_retriever
    if _graph_retriever is None:
        _graph_retriever = GraphRetriever(llm_client)
    return _graph_retriever

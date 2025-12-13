"""RAG Pipeline for Bible knowledge retrieval and generation."""

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.neo4j_client import Neo4jClient
from app.models.schemas import (
    GraphContext,
    PericopeSegment,
    QueryMeta,
    QueryResponse,
)
from app.services.context_builder import ContextBuilder
from app.services.embedding_service import EmbeddingService
from app.services.fusion import RRFFusion
from app.services.llm_client import OllamaLLMClient
from app.services.retrievers.dense_retriever import DenseRetriever
from app.services.retrievers.sparse_retriever import SparseRetriever
from app.services.retrievers.graph_retriever import GraphRetriever


class RAGPipeline:
    """Main RAG pipeline orchestrator."""

    def __init__(
        self,
        db: AsyncSession,
        embed_service: EmbeddingService,
        llm_client: OllamaLLMClient,
        use_graph: bool = True,
    ):
        self.db = db
        self.embed_service = embed_service
        self.llm_client = llm_client
        self.use_graph = use_graph

        # Initialize components
        self.dense_retriever = DenseRetriever(db, embed_service)
        self.sparse_retriever = SparseRetriever(db)
        self.graph_retriever = GraphRetriever(llm_client) if use_graph else None
        self.fusion = RRFFusion()
        self.context_builder = ContextBuilder()

    async def execute(
        self,
        query: str,
        mode: str = "auto",
        options: dict[str, Any] | None = None,
    ) -> QueryResponse:
        """Execute the full RAG pipeline.

        Args:
            query: User query text
            mode: Query mode (auto, verse, topic, person, event)
            options: Additional options (max_results, include_graph)

        Returns:
            QueryResponse with answer and sources
        """
        start_time = time.time()
        options = options or {}
        max_results = options.get("max_results", settings.TOP_K_PERICOPES)
        used_retrievers = []

        # Step 1: Classify query
        if mode == "auto":
            query_type = await self.llm_client.classify_query(query)
        else:
            query_type = mode.upper()

        # Step 2: Run retrievers
        # Dense retrieval (semantic)
        try:
            dense_results = await self.dense_retriever.retrieve(
                query,
                top_k=settings.MAX_RETRIEVE_RESULTS,
            )
            if dense_results:
                used_retrievers.append("dense")
        except Exception as e:
            print(f"Dense retrieval error: {e}")
            dense_results = []

        # Sparse retrieval (keyword)
        try:
            sparse_results = await self.sparse_retriever.retrieve(
                query,
                top_k=settings.MAX_RETRIEVE_RESULTS,
            )
            if sparse_results:
                used_retrievers.append("sparse")
        except Exception as e:
            print(f"Sparse retrieval error: {e}")
            sparse_results = []

        # Graph retrieval (knowledge graph)
        graph_results = []
        graph_context_data: dict[str, list[str]] = {"topics": [], "persons": []}
        include_graph = options.get("include_graph", True)

        if self.graph_retriever and include_graph and Neo4jClient.is_available():
            try:
                graph_results = await self.graph_retriever.retrieve(
                    query,
                    query_type=query_type,
                    top_k=settings.MAX_RETRIEVE_RESULTS,
                )
                if graph_results:
                    used_retrievers.append("graph")
                    # Extract graph context
                    graph_context_data = self._build_graph_context(graph_results)
            except Exception as e:
                print(f"Graph retrieval error: {e}")
                graph_results = []

        # Step 3: Fuse results
        result_lists = []
        if dense_results:
            result_lists.append(("dense", dense_results))
        if sparse_results:
            result_lists.append(("sparse", sparse_results))
        if graph_results:
            result_lists.append(("graph", graph_results))

        if result_lists:
            fused_results = self.fusion.fuse(result_lists)
        else:
            fused_results = []

        # Limit to max_results
        fused_results = fused_results[:max_results]

        # Step 4: Build context
        context, metadata = self.context_builder.build_with_metadata(fused_results)

        # Step 5: Generate answer
        if fused_results:
            answer = await self.llm_client.generate_answer(
                query=query,
                context=context,
                query_type=query_type,
            )
        else:
            answer = "抱歉，我找不到與您問題相關的聖經經文。請嘗試用不同的方式描述您的問題。"

        # Step 6: Build response
        processing_time = int((time.time() - start_time) * 1000)

        segments = [
            PericopeSegment(
                id=result.id,
                type="pericope",
                book=result.book_name,
                chapter_start=result.chapter_start,
                verse_start=result.verse_start,
                chapter_end=result.chapter_end,
                verse_end=result.verse_end,
                title=result.title,
                text_excerpt=result.text[:200] + "..." if len(result.text) > 200 else result.text,
                relevance_score=min(1.0, result.score * 10),  # Normalize RRF score
            )
            for result in fused_results
        ]

        # Build graph context
        graph_context = None
        if graph_context_data and (graph_context_data["topics"] or graph_context_data["persons"]):
            graph_context = GraphContext(
                related_topics=graph_context_data["topics"],
                related_persons=graph_context_data["persons"],
            )

        return QueryResponse(
            answer=answer,
            segments=segments,
            meta=QueryMeta(
                query_type=query_type,
                used_retrievers=used_retrievers,
                total_processing_time_ms=processing_time,
                llm_model=settings.LLM_MODEL_NAME,
            ),
            graph_context=graph_context,
        )

    def _build_graph_context(
        self,
        results: list,
    ) -> dict[str, list[str]]:
        """Extract unique entities from graph results.

        Args:
            results: Graph retrieval results

        Returns:
            Dict with topics and persons lists
        """
        topics: set[str] = set()
        persons: set[str] = set()

        for r in results:
            ctx = getattr(r, "graph_context", {})
            entity_type = ctx.get("type", "")
            entities = ctx.get("entities", [])

            if entity_type == "topic":
                topics.update(entities)
            elif entity_type == "person":
                persons.update(entities)

        return {
            "topics": list(topics)[:10],
            "persons": list(persons)[:10],
        }

"""Query endpoint for RAG pipeline."""

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.models.schemas import QueryRequest, QueryResponse
from app.services.embedding_service import get_embedding_service
from app.services.llm_client import get_llm_client
from app.services.rag_pipeline import RAGPipeline

router = APIRouter()


@router.post("", response_model=QueryResponse)
async def execute_query(
    request: QueryRequest,
    db: DbSession,
) -> QueryResponse:
    """Execute RAG query and return answer with sources.

    This endpoint:
    1. Classifies the query type (topic, person, event, verse lookup)
    2. Retrieves relevant pericopes using dense and sparse search
    3. Fuses results using RRF (Reciprocal Rank Fusion)
    4. Generates an answer using the LLM
    """
    try:
        # Get services
        embed_service = await get_embedding_service()
        llm_client = await get_llm_client()

        # Create and execute pipeline
        pipeline = RAGPipeline(
            db=db,
            embed_service=embed_service,
            llm_client=llm_client,
        )

        result = await pipeline.execute(
            query=request.query,
            mode=request.mode.value,
            options={
                "max_results": request.options.max_results,
                "include_graph": request.options.include_graph,
            },
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Query execution failed: {str(e)}",
        )

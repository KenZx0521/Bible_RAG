"""
Health check endpoint.
"""

from fastapi import APIRouter

from database import postgres, qdrant_db, neo4j_db
from utils.llm import get_llm_client
from models.response import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check health of all backend services."""
    pg = await postgres.health_check()
    qdrant = qdrant_db.health_check()
    neo4j = await neo4j_db.health_check()
    llm = await get_llm_client().health_check()

    services = {
        "postgres": pg,
        "qdrant": qdrant,
        "neo4j": neo4j,
        "llm": llm,
    }

    all_ok = all(services.values())
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        services=services,
    )

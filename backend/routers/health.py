"""
Health check endpoint.
"""

from fastapi import APIRouter

from database import postgres, qdrant_db, neo4j_db
from utils.generator import check_ollama
from models.response import HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check health of all backend services."""
    pg = await postgres.health_check()
    qdrant = qdrant_db.health_check()
    neo4j = await neo4j_db.health_check()
    ollama = await check_ollama()

    services = {
        "postgres": pg,
        "qdrant": qdrant,
        "neo4j": neo4j,
        "ollama": ollama,
    }

    all_ok = all(services.values())
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        services=services,
    )

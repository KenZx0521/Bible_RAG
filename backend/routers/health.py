"""
Health check endpoint: services, encoder fingerprints and the build handshake.

Any handshake mismatch (design §7.8) answers 503 and lists the mismatches.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from database import postgres, qdrant_db
from models.response import HealthResponse
from serving import context
from utils import embedder, reranker
from utils.llm import get_llm_client

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse,
            responses={503: {"description": "build handshake failed"}})
async def health_check():
    """Check the services and report the build this backend serves."""
    services = {
        "postgres": await postgres.health_check(),
        "qdrant": qdrant_db.health_check(),
        "llm": await get_llm_client().health_check(),
    }
    handshake = context.handshake()
    shook = handshake is not None and handshake.ok
    body = HealthResponse(
        status=("ok" if all(services.values()) else "degraded") if shook else "mismatch",
        services=services,
        encoder={"embedder": embedder.get_fingerprint(), "reranker": reranker.get_fingerprint()},
        build_id=handshake.build_id if handshake else None,
        handshake=handshake.to_json() if handshake else {"ok": False, "mismatches": ["not started"]},
    )
    return JSONResponse(body.model_dump(), status_code=200 if shook else 503)

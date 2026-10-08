"""
Bible RAG Backend API — FastAPI application with lifespan management.
"""

import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Add packages/ for ragcommon (the image also sets PYTHONPATH; a local
# `uv run uvicorn main:app` from backend/ does not)
packages_dir = backend_dir.parent / "packages"
if str(packages_dir) not in sys.path:
    sys.path.insert(0, str(packages_dir))

from serving import startup  # noqa: E402
from serving.context import NoActiveBuild  # noqa: E402
from utils import embedder, reranker  # noqa: E402
from utils.llm import get_llm_client  # noqa: E402
from routers import health, query, verse, entity  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_models() -> dict:
    """BGE-M3 and the reranker with their pinned tokenizers; a contract failure raises."""
    logger.info("Loading embedding model (BGE-M3)...")
    embedder.init_model()
    logger.info(f"Embedding model on device: {embedder.get_device()}")
    logger.info("Loading reranker (bge-reranker-v2-m3)...")
    reranker.init_reranker()
    return {"bge_m3": embedder.get_fingerprint(), "reranker": reranker.get_fingerprint()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the models, shake hands with the serving build, verify the LLM."""
    logger.info("Starting Bible RAG Backend...")
    fingerprints = load_models()
    try:
        await startup.run(fingerprints)
        llm = get_llm_client()
        if await llm.health_check():
            logger.info(f"LLM provider verified: {llm.provider_name}")
        else:
            logger.warning(f"LLM provider not available ({llm.provider_name}) — generation will fail")
        logger.info("Bible RAG Backend ready")
        yield
    finally:
        logger.info("Shutting down...")
        await startup.stop()
        logger.info("Shutdown complete")


app = FastAPI(
    title="Bible RAG API",
    description="聖經 RAG 後端 API — 讀取 rag_meta.serving 指定的 build（PostgreSQL schema、"
                "Qdrant collection、契約檔），透過意圖偵測路由多策略檢索並生成回答。",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NoActiveBuild)
async def no_active_build(request: Request, exc: NoActiveBuild):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# Register routers
app.include_router(health.router)
app.include_router(query.router)
app.include_router(verse.router)
app.include_router(entity.router)


@app.get("/", tags=["root"])
async def root():
    return {
        "name": "Bible RAG API",
        "version": "0.2.0",
        "docs": "/docs",
    }

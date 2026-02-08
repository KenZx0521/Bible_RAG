"""
Bible RAG Backend API — FastAPI application with lifespan management.
"""

import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path for bible_chunking imports
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from database import postgres, qdrant_db, neo4j_db
from utils import embedder, reranker
from utils.llm import get_llm_client
from routers import health, query, verse, entity
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup all resources."""
    logger.info("Starting Bible RAG Backend...")

    # Phase 1: Database connections
    logger.info("Initializing database connections...")
    await postgres.init_pool()
    qdrant_db.init_client()
    await neo4j_db.init_driver()

    # Phase 2: Load ML models
    logger.info("Loading embedding model (BGE-M3)...")
    embedder.init_model()
    logger.info(f"Embedding model on device: {embedder.get_device()}")

    logger.info("Loading reranker (bge-reranker-v2-m3)...")
    reranker.init_reranker()

    # Phase 3: Initialize sparse encoder (if hybrid search enabled)
    if settings.hybrid_search_enabled:
        logger.info("Hybrid search enabled, initializing sparse encoder...")
        from utils import sparse_encoder
        if sparse_encoder.init_sparse_encoder():
            logger.info(f"Sparse encoder ready (vocab size: {sparse_encoder.get_vocabulary_size()})")
        else:
            logger.warning("Sparse encoder initialization failed, falling back to dense-only")

    # Phase 4: Verify LLM provider
    llm = get_llm_client()
    llm_ok = await llm.health_check()
    if llm_ok:
        logger.info(f"LLM provider verified: {llm.provider_name}")
    else:
        logger.warning(f"LLM provider not available ({llm.provider_name}) — generation will fail")

    logger.info("Bible RAG Backend ready")

    yield

    # Cleanup
    logger.info("Shutting down...")
    await postgres.close_pool()
    qdrant_db.close_client()
    await neo4j_db.close_driver()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Bible RAG API",
    description="聖經 RAG 後端 API — 整合 PostgreSQL、Qdrant、Neo4j 三大資料源，"
                "透過意圖偵測路由多策略檢索，使用 gemma3:4b 生成回答。",
    version="0.1.0",
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

# Register routers
app.include_router(health.router)
app.include_router(query.router)
app.include_router(verse.router)
app.include_router(entity.router)


@app.get("/", tags=["root"])
async def root():
    return {
        "name": "Bible RAG API",
        "version": "0.1.0",
        "docs": "/docs",
    }

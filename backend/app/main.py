"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.neo4j_client import Neo4jClient


# API Tags metadata for documentation
TAGS_METADATA = [
    {
        "name": "Query",
        "description": "RAG 查詢 API - 執行完整 RAG 管線，回傳 LLM 生成的答案與相關經文。",
    },
    {
        "name": "Books",
        "description": "書卷 API - 取得聖經 66 卷書的資訊、章節、段落和經文。",
    },
    {
        "name": "Pericopes",
        "description": "段落 API - 取得聖經段落單元 (Pericope) 的詳細資訊。",
    },
    {
        "name": "Verses",
        "description": "經文 API - 取得經文詳情和全文搜尋。",
    },
    {
        "name": "Graph",
        "description": "知識圖譜 API - 存取 Neo4j 知識圖譜中的實體、主題、關係等資料。",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    await Neo4jClient.initialize()
    yield
    # Shutdown
    await Neo4jClient.close()
    await close_db()


def custom_openapi(app: FastAPI):
    """Generate custom OpenAPI schema with enhanced documentation."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Bible RAG API",
        version=settings.VERSION,
        description="""
## 聖經知識型 RAG 系統 API

基於新標點和合本聖經 PDF 的知識型檢索增強生成系統。

### 主要功能

- **RAG 查詢**: 自然語言問答，結合向量檢索、全文檢索和知識圖譜
- **經文瀏覽**: 書卷、章節、段落、經文的結構化存取
- **知識圖譜**: 人物、地點、事件、主題的關係探索

### 技術架構

- **向量檢索**: PostgreSQL + pgvector (bge-m3 embeddings)
- **全文檢索**: PostgreSQL Full-Text Search
- **知識圖譜**: Neo4j
- **LLM**: Ollama (gemma3:4b)

### Postman 使用說明

1. 點擊右上角 **「↓」** 下載 OpenAPI JSON
2. 在 Postman 中選擇 **Import → Raw Text**
3. 貼上 JSON 內容或使用 URL: `http://localhost:8000/api/v1/openapi.json`

### 相關連結

- [Swagger UI](/api/v1/docs) - 互動式 API 文檔
- [ReDoc](/api/v1/redoc) - 閱讀式 API 文檔
        """,
        routes=app.routes,
        tags=TAGS_METADATA,
    )

    # Add servers for Postman
    openapi_schema["servers"] = [
        {"url": "http://localhost:8000", "description": "本地開發環境"},
    ]

    # Add contact and license info
    openapi_schema["info"]["contact"] = {
        "name": "Bible RAG API Support",
        "url": "https://github.com/KenZx0521/bible_RAG",
    }
    openapi_schema["info"]["license"] = {
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
    )

    # Set custom OpenAPI schema
    app.openapi = lambda: custom_openapi(app)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": settings.VERSION}

    return app


app = create_app()

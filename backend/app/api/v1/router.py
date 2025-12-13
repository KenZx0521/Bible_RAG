"""API v1 router configuration."""

from fastapi import APIRouter

from app.api.v1.endpoints import books, graph, pericopes, query, verses

api_router = APIRouter()

# Include endpoint routers
api_router.include_router(query.router, prefix="/query", tags=["Query"])
api_router.include_router(books.router, prefix="/books", tags=["Books"])
api_router.include_router(pericopes.router, prefix="/pericopes", tags=["Pericopes"])
api_router.include_router(verses.router, prefix="/verses", tags=["Verses"])
api_router.include_router(graph.router, prefix="/graph", tags=["Graph"])

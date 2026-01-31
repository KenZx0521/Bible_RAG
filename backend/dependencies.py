"""
FastAPI dependency injection helpers.
Provides DB clients and model instances to route handlers.
"""

from database import postgres, qdrant_db, neo4j_db


async def get_postgres_pool():
    return postgres.get_pool()


def get_qdrant_client():
    return qdrant_db.get_client()


def get_neo4j_driver():
    return neo4j_db.get_driver()

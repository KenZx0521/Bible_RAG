"""Neo4j async client with connection pooling."""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from neo4j.exceptions import ServiceUnavailable, AuthError

from app.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Async Neo4j client with connection pooling and session management."""

    _driver: AsyncDriver | None = None
    _initialized: bool = False

    @classmethod
    async def initialize(cls) -> None:
        """Initialize the Neo4j driver.

        This should be called during application startup.
        """
        if cls._driver is not None:
            return

        try:
            cls._driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                max_connection_pool_size=50,
                connection_acquisition_timeout=30.0,
            )
            # Verify connectivity
            await cls._driver.verify_connectivity()
            cls._initialized = True
            logger.info(f"Neo4j connected to {settings.NEO4J_URI}")
        except (ServiceUnavailable, AuthError) as e:
            logger.warning(f"Neo4j connection failed: {e}. Graph features will be disabled.")
            cls._driver = None
            cls._initialized = False

    @classmethod
    async def close(cls) -> None:
        """Close the Neo4j driver.

        This should be called during application shutdown.
        """
        if cls._driver:
            await cls._driver.close()
            cls._driver = None
            cls._initialized = False
            logger.info("Neo4j connection closed")

    @classmethod
    def is_available(cls) -> bool:
        """Check if Neo4j is available."""
        return cls._initialized and cls._driver is not None

    @classmethod
    @asynccontextmanager
    async def session(cls) -> AsyncGenerator[AsyncSession, None]:
        """Get a Neo4j session context manager.

        Yields:
            AsyncSession: Neo4j async session

        Raises:
            RuntimeError: If Neo4j is not initialized
        """
        if cls._driver is None:
            raise RuntimeError("Neo4j is not initialized. Call initialize() first.")

        async with cls._driver.session() as session:
            yield session

    @classmethod
    async def execute_read(
        cls,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Execute a read query and return results as list of dicts.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dictionaries
        """
        if not cls.is_available():
            logger.warning("Neo4j not available, returning empty results")
            return []

        try:
            async with cls.session() as session:
                result = await session.run(query, parameters or {})
                return [dict(record) for record in await result.data()]
        except Exception as e:
            logger.error(f"Neo4j read query failed: {e}")
            return []

    @classmethod
    async def execute_write(
        cls,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Execute a write query.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Raises:
            RuntimeError: If Neo4j is not available
        """
        if not cls.is_available():
            raise RuntimeError("Neo4j is not available")

        async with cls.session() as session:
            await session.run(query, parameters or {})

    @classmethod
    async def execute_write_batch(
        cls,
        queries: list[tuple[str, dict[str, Any] | None]],
    ) -> None:
        """Execute multiple write queries in a single transaction.

        Args:
            queries: List of (query, parameters) tuples
        """
        if not cls.is_available():
            raise RuntimeError("Neo4j is not available")

        async with cls.session() as session:
            async with session.begin_transaction() as tx:
                for query, params in queries:
                    await tx.run(query, params or {})
                await tx.commit()

    @classmethod
    async def health_check(cls) -> dict[str, Any]:
        """Check Neo4j connectivity and return status.

        Returns:
            Health check result with status and details
        """
        if not cls.is_available():
            return {
                "status": "unavailable",
                "message": "Neo4j driver not initialized",
            }

        try:
            result = await cls.execute_read("RETURN 1 as n")
            if result and result[0].get("n") == 1:
                return {
                    "status": "healthy",
                    "uri": settings.NEO4J_URI,
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

        return {"status": "unknown"}


async def get_neo4j_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for Neo4j session.

    Yields:
        AsyncSession: Neo4j async session

    Usage:
        @router.get("/example")
        async def example(neo4j: AsyncSession = Depends(get_neo4j_session)):
            ...
    """
    if not Neo4jClient.is_available():
        raise RuntimeError("Neo4j is not available")

    async with Neo4jClient.session() as session:
        yield session

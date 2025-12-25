#!/bin/bash
set -e

echo "=========================================="
echo "  Bible RAG Backend - Initialization"
echo "=========================================="

# 1. Wait for PostgreSQL to be ready
echo "[1/6] Waiting for PostgreSQL..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-bible_user}" -q; do
    echo "  PostgreSQL is not ready yet, waiting..."
    sleep 2
done
echo "  PostgreSQL is ready!"

# 2. Run database migrations
echo "[2/6] Running database migrations..."
cd /app
alembic upgrade head
echo "  Migrations completed!"

# 3. Check if index needs to be built
echo "[3/6] Checking database status..."
VERSE_COUNT=$(python -c "
import asyncio
from sqlalchemy import text
from app.core.database import async_engine

async def count_verses():
    async with async_engine.connect() as conn:
        result = await conn.execute(text('SELECT COUNT(*) FROM verses'))
        return result.scalar()

try:
    count = asyncio.run(count_verses())
    print(count)
except Exception as e:
    print('0')
" 2>/dev/null || echo "0")

if [ "$VERSE_COUNT" -eq "0" ] || [ "$VERSE_COUNT" = "0" ]; then
    echo "  Database is empty. Building index (this may take 10-15 minutes)..."

    # Check if PDF exists
    if [ -f "pdf/cmn-cu89t_a4.pdf" ]; then
        python -m scripts.build_index --pdf pdf/cmn-cu89t_a4.pdf
        echo "  Index built successfully!"
    else
        echo "  WARNING: PDF file not found at pdf/cmn-cu89t_a4.pdf"
        echo "  Skipping index build. Please run manually:"
        echo "  docker compose exec backend python -m scripts.build_index --pdf pdf/cmn-cu89t_a4.pdf"
    fi
else
    echo "  Database already has $VERSE_COUNT verses. Skipping index build."
fi

# 4. Check Neo4j availability and build knowledge graph
echo "[4/6] Checking Neo4j availability..."

# Extract Neo4j host from URI (bolt://neo4j:7687 -> neo4j)
NEO4J_HOST=$(echo "${NEO4J_URI:-bolt://neo4j:7687}" | sed 's|bolt://||' | sed 's|:.*||')

# Check if Neo4j is reachable
NEO4J_AVAILABLE=false
if nc -z "$NEO4J_HOST" 7687 2>/dev/null; then
    echo "  Neo4j is available at $NEO4J_HOST:7687"

    # Wait for Neo4j to be fully ready
    echo "  Waiting for Neo4j to be fully ready..."
    for i in {1..30}; do
        if python -c "
from neo4j import GraphDatabase
import sys
try:
    driver = GraphDatabase.driver('${NEO4J_URI:-bolt://neo4j:7687}', auth=('${NEO4J_USER:-neo4j}', '${NEO4J_PASSWORD:-neo4j_password}'))
    driver.verify_connectivity()
    driver.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
            NEO4J_AVAILABLE=true
            echo "  Neo4j is ready!"
            break
        fi
        sleep 2
    done

    if [ "$NEO4J_AVAILABLE" = false ]; then
        echo "  WARNING: Neo4j connection failed. Skipping knowledge graph build."
    fi
else
    echo "  Neo4j is not available (use --profile full to enable). Skipping knowledge graph build."
fi

# 5. Build knowledge graph if Neo4j is available
echo "[5/6] Knowledge graph status..."

if [ "$NEO4J_AVAILABLE" = true ]; then
    # Check if entities already exist in PostgreSQL
    ENTITY_COUNT=$(python -c "
import asyncio
from sqlalchemy import text
from app.core.database import async_engine

async def count_entities():
    async with async_engine.connect() as conn:
        result = await conn.execute(text('SELECT COUNT(*) FROM entities'))
        return result.scalar()

try:
    count = asyncio.run(count_entities())
    print(count)
except Exception as e:
    print('0')
" 2>/dev/null || echo "0")

    if [ "$ENTITY_COUNT" -eq "0" ] || [ "$ENTITY_COUNT" = "0" ]; then
        echo "  No entities found. Starting knowledge graph build..."
        echo "  WARNING: This process takes 6-10 hours!"
        echo ""
        echo "  Step 1/3: LLM Entity Extraction (6-10 hours)..."

        # Run entity extractor with resume support
        if python -m scripts.entity_extractor --batch-size 10; then
            echo "  Entity extraction completed!"

            echo "  Step 2/3: Building Neo4j graph..."
            if python -m scripts.build_graph; then
                echo "  Neo4j graph built successfully!"

                echo "  Step 3/3: Computing topic relations..."
                if python -m scripts.compute_topic_relations; then
                    echo "  Topic relations computed successfully!"
                    echo "  Knowledge graph build completed!"
                else
                    echo "  WARNING: Topic relations computation failed."
                fi
            else
                echo "  WARNING: Neo4j graph build failed."
            fi
        else
            echo "  WARNING: Entity extraction failed or interrupted."
            echo "  You can resume later with: docker compose exec backend python -m scripts.entity_extractor --batch-size 10"
        fi
    else
        echo "  Knowledge graph already has $ENTITY_COUNT entities. Skipping build."

        # Check if Neo4j graph needs sync
        NEO4J_NODE_COUNT=$(python -c "
from neo4j import GraphDatabase
try:
    driver = GraphDatabase.driver('${NEO4J_URI:-bolt://neo4j:7687}', auth=('${NEO4J_USER:-neo4j}', '${NEO4J_PASSWORD:-neo4j_password}'))
    with driver.session() as session:
        result = session.run('MATCH (n) RETURN count(n) as count')
        print(result.single()['count'])
    driver.close()
except Exception as e:
    print('0')
" 2>/dev/null || echo "0")

        if [ "$NEO4J_NODE_COUNT" -eq "0" ] || [ "$NEO4J_NODE_COUNT" = "0" ]; then
            echo "  Neo4j is empty but PostgreSQL has entities. Syncing to Neo4j..."
            if python -m scripts.build_graph; then
                echo "  Neo4j graph synced successfully!"

                # Also compute topic relations
                python -m scripts.compute_topic_relations 2>/dev/null || true
            else
                echo "  WARNING: Neo4j sync failed."
            fi
        else
            echo "  Neo4j already has $NEO4J_NODE_COUNT nodes."
        fi
    fi
else
    echo "  Skipping knowledge graph (Neo4j not available)."
fi

# 6. Start the application
echo "[6/6] Starting API server..."
echo "=========================================="
echo "  Server starting at http://0.0.0.0:8000"
echo "  API docs at http://localhost/api/v1/docs"
echo "=========================================="

exec uvicorn app.main:app --host 0.0.0.0 --port 8000

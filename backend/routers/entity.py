"""
Entity information endpoint.
"""

from fastapi import APIRouter, HTTPException

from database import postgres, neo4j_db
from models.response import EntityResponse

router = APIRouter(prefix="/api/v1/entity", tags=["entity"])


@router.get(
    "/{entity_id}",
    response_model=EntityResponse,
    summary="取得實體資訊",
)
async def get_entity(entity_id: str):
    """取得實體（人物、地點、事件等）資訊及相關經文。"""
    entity = await postgres.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"找不到實體 {entity_id}")

    # Get related passages from Neo4j
    related_passages = await neo4j_db.get_entity_related_pericopes(entity_id, limit=10)

    # Get related entities from Neo4j
    related_entities = await neo4j_db.find_related_entities(entity_id, limit=10)

    return EntityResponse(
        entity_id=entity["entity_id"],
        type=entity["type"],
        canonical_name=entity["canonical_name"],
        aliases=entity.get("aliases", []),
        description=entity.get("description"),
        mention_count=entity.get("mention_count", 0),
        related_passages=related_passages,
        related_entities=related_entities,
    )

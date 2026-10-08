"""
/api/v1/entity is retired (design D-08): R1 serves no entity layer and the
endpoint has no replacement. Every request answers 410 Gone with the reason.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/entity", tags=["entity"])

RETIRED = ("/api/v1/entity 已退役（設計決定 D-08）：自 R1 起本服務不提供實體資料，"
           "也沒有替代端點。")


@router.get("/{entity_id}", status_code=410, summary="已退役（410）")
async def get_entity(entity_id: str):
    """已退役：一律回 410。"""
    raise HTTPException(status_code=410, detail=RETIRED)

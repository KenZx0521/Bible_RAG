"""
Pydantic v2 request models.
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="使用者問題")
    top_k: int = Field(default=5, ge=1, le=20, description="回傳結果數量")
    include_sources: bool = Field(default=True, description="是否包含來源資訊")
    use_graph: bool | None = Field(
        default=None,
        description="覆寫 RAG_USE_GRAPH 預設值;None 表示沿用 backend 設定",
    )
    semantic_only: bool = Field(
        default=False,
        description="僅用 semantic search,bypass R1-R6 routing、SQL、graph、cross-ref",
    )

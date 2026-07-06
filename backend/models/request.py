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
    retrieval_only: bool = Field(
        default=False,
        description="只跑檢索+重排,跳過答案生成(answer 回空字串);供檢索指標評估快速迴路使用",
    )
    fusion_alpha: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="覆寫排序融合 alpha(0=純 reranker 排序);None 沿用 backend 設定。供 A/B sweep 使用",
    )

"""
Pydantic v2 request models.
"""

from pydantic import BaseModel, Field, field_validator

from config import GraphStrategyName


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="使用者問題")
    top_k: int = Field(default=5, ge=1, le=20, description="回傳結果數量")
    include_sources: bool = Field(default=True, description="是否包含來源資訊")
    include_context: bool = Field(
        default=False,
        description="在每個 source 附上交給生成器的完整 context 區塊(標頭+經文);供評估端 judge 使用",
    )
    use_graph: bool | None = Field(
        default=None,
        description="覆寫 RAG_USE_GRAPH 預設值(只控制 event_registry 附加槽);None 表示沿用 backend 設定",
    )
    graph_strategies: list[GraphStrategyName] | None = Field(
        default=None,
        description="覆寫 RAG_GRAPH_STRATEGIES:只接受 ['event_registry'] 或 [];None 沿用 backend 設定",
    )
    use_regnal_card: bool | None = Field(
        default=None,
        description="覆寫王朝年表卡開關(只在王朝年代題觸發);None 表示沿用 RAG_REGNAL_CARD,"
                    "但 semantic_only 或 use_graph=false 時預設關閉",
    )
    use_gen_card: bool | None = Field(
        default=None,
        description="覆寫創世記年歲卡開關(只在創世記家譜年歲題觸發,王朝卡觸發時不算);"
                    "None 表示沿用 RAG_GEN_CARD,但 semantic_only 或 use_graph=false 時預設關閉",
    )
    semantic_only: bool = Field(
        default=False,
        description="僅用 dense 檢索,bypass R1-R6 routing、SQL 與 event_registry",
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

    @field_validator("graph_strategies")
    @classmethod
    def _one_lane_at_most(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) > 1:
            raise ValueError("graph_strategies must be ['event_registry'] or []")
        return value

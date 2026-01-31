"""
Pydantic v2 request models.
"""

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="使用者問題")
    top_k: int = Field(default=5, ge=1, le=20, description="回傳結果數量")
    include_sources: bool = Field(default=True, description="是否包含來源資訊")

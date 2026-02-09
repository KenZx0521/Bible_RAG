"""
Main RAG query endpoint.
"""

import logging

from fastapi import APIRouter

from models.request import QueryRequest
from models.response import QueryResponse, Source, IntentInfo, RetrievalStats
from utils.intent_classifier import classify_intent
from utils.retrieval.router import retrieve_and_rerank
from utils.generator import generate_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="RAG 聖經查詢",
)
async def rag_query(req: QueryRequest):
    """
    主 RAG 查詢端點。

    流程:
    1. 經文引用偵測 (regex)
    2. 意圖分類 (gemma3:4b)
    3. 多策略並行檢索
    4. 融合去重
    5. 重排序 (bge-reranker-v2-m3)
    6. 上下文組裝
    7. 回答生成 (gemma3:4b)
    """
    question = req.question

    # Step 1 & 2: Intent classification (includes verse ref detection)
    intent = await classify_intent(question)

    # Step 3-5: Retrieval + fusion + rerank
    results, stats = await retrieve_and_rerank(
        query=question,
        verse_refs=intent["verse_refs"],
        intent_type=intent["type"],
        entity_names=intent["entities"],
        top_k=req.top_k,
        keywords=intent.get("keywords"),
    )

    # Step 6-7: Generate answer
    answer = await generate_answer(question, results)

    # Build response
    sources = []
    if req.include_sources:
        for r in results:
            sources.append(Source(
                id=r["id"],
                book=r.get("book_name", ""),
                chapter=r.get("chapter_num"),
                title=r.get("title", ""),
                verse_range=r.get("verse_range", ""),
                score=r.get("rerank_score"),
            ))

    return QueryResponse(
        answer=answer,
        sources=sources,
        intent=IntentInfo(
            type=intent["type"],
            entities=intent["entities"],
            verse_refs=[ref.display for ref in intent["verse_refs"]],
        ),
        retrieval_stats=RetrievalStats(**stats),
    )

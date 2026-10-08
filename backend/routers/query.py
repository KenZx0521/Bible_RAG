"""
Main RAG query endpoint.
"""

import logging

from fastapi import APIRouter

from models.request import QueryRequest
from models.response import QueryResponse, Source, IntentInfo, RetrievalStats
from serving import context
from utils.intent_classifier import classify_intent
from utils.retrieval.router import retrieve_and_rerank
from utils.generator import build_context_blocks, generate_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["query"])

SOURCE_FIELDS = ("kind", "start_key", "end_key", "passage_id")


def _source(r: dict, block: str | None, build_id: str) -> Source:
    fused = r.get("fused_score")
    return Source(
        id=r["id"], book=r.get("book_name", ""), chapter=r.get("chapter_num"),
        title=r.get("title", ""), verse_range=r.get("verse_range", ""),
        score=fused if fused is not None else r.get("rerank_score"),
        strategy=r.get("source_strategy"), rerank_score=r.get("rerank_score"),
        found_by=r.get("found_by"), context=block,
        split_passage_ids=list(r.get("split_passage_ids") or []), build_id=build_id,
        **{f: r.get(f) for f in SOURCE_FIELDS},
    )


def _sources(req: QueryRequest, results: list[dict]) -> list[Source]:
    if not req.include_sources:
        return []
    # the exact blocks the generator saw, so an evaluation judge sees the same text
    blocks = build_context_blocks(results) if req.include_context else [None] * len(results)
    build_id = context.active().build.build_id
    return [_source(r, block, build_id) for r, block in zip(results, blocks)]


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="RAG 聖經查詢",
)
async def rag_query(req: QueryRequest):
    """
    主 RAG 查詢端點。

    流程: 經文引用偵測 → 意圖分類 → 路由檢索 → 去重 → 重排序 → 上下文組裝 → 回答生成。
    """
    context.active()  # 503 before any work when no build is served
    if req.semantic_only:
        intent = {"type": "semantic_only", "entities": [], "verse_refs": [], "keywords": [],
                  "rejected_refs": []}
    else:
        intent = await classify_intent(req.question)

    results, stats = await retrieve_and_rerank(
        query=req.question, verse_refs=intent["verse_refs"], intent_type=intent["type"],
        entity_names=intent["entities"], top_k=req.top_k, keywords=intent.get("keywords"),
        use_graph=req.use_graph, semantic_only=req.semantic_only,
        fusion_alpha=req.fusion_alpha, graph_strategies=req.graph_strategies,
    )
    answer = "" if req.retrieval_only else await generate_answer(req.question, results)
    return QueryResponse(
        answer=answer,
        sources=_sources(req, results),
        intent=IntentInfo(type=intent["type"], entities=intent["entities"],
                          verse_refs=[ref.display for ref in intent["verse_refs"]],
                          rejected_refs=intent.get("rejected_refs", [])),
        retrieval_stats=RetrievalStats(**stats),
    )

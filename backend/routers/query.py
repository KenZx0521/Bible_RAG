"""
Main RAG query endpoint.
"""

import logging

from fastapi import APIRouter

from ragcommon.regnal import KINGDOM_NAMES

from config import settings
from models.request import QueryRequest
from models.response import AuxCard, QueryResponse, Source, IntentInfo, RetrievalStats
from serving import context
from utils import gen_card
from utils.citations import fix_block_chapters
from utils.intent_classifier import classify_intent
from utils.regnal.card import Card, chronology_card
from utils.regnal.trigger import trigger as regnal_trigger
from utils.retrieval.router import retrieve_and_rerank
from utils.generator import build_context, build_context_blocks, generate_answer

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
        split_passage_ids=list(r.get("split_passage_ids") or []),
        member_ids=list(r.get("member_ids") or []), build_id=build_id,
        **{f: r.get(f) for f in SOURCE_FIELDS},
    )


def _sources(req: QueryRequest, results: list[dict]) -> list[Source]:
    if not req.include_sources:
        return []
    # the exact blocks the generator saw, so an evaluation judge sees the same text
    blocks = build_context_blocks(results) if req.include_context else [None] * len(results)
    build_id = context.active().build.build_id
    return [_source(r, block, build_id) for r, block in zip(results, blocks)]


def _evidence(card: Card | gen_card.Card | None) -> tuple[str, ...]:
    """The verse keys the card's rows rest on."""
    if card is None:
        return ()
    if isinstance(card, gen_card.Card):
        return gen_card.evidence(context.active().gen, card.rows)
    return tuple(card.evidence)


def _aux_card(card: Card | gen_card.Card | None) -> AuxCard | None:
    if card is None:
        return None
    if isinstance(card, gen_card.Card):
        gen = context.active().gen
        return AuxCard(kind="gen", text=card.g_block, seeds=[gen.name[x] for x in card.seeds],
                       kings=list(card.seeds), lines=len(card.lines),
                       evidence=list(_evidence(card)), layer_sha256=gen.gen_layer_sha256,
                       seed_source="rule")
    return AuxCard(text=card.text, seeds=[f"{KINGDOM_NAMES[kd]}｜{nm}" for kd, nm in card.seeds],
                   kings=list(card.kings), lines=card.lines, evidence=list(_evidence(card)),
                   layer_sha256=card.layer_sha256, seed_source=card.seed_source)


async def _answer(req: QueryRequest, results: list[dict], card: Card | gen_card.Card | None) -> str:
    """The generated answer, block numbers cited as chapters put right (utils.citations)."""
    if req.retrieval_only:
        return ""
    answer = await generate_answer(req.question, results, _aux_block(card))
    return fix_block_chapters(answer, results, req.question, _evidence(card))


def _aux_block(card: Card | gen_card.Card | None) -> str | None:
    if isinstance(card, gen_card.Card):
        return card.g_block
    return card.text if card else None


def _on(asked: bool | None, default: bool, req: QueryRequest) -> bool:
    """``asked`` when given; else ``default``, but never in the dense-only or graph-off arms (a
    card is a graph-side operation, so those ablations stay card-free)."""
    if asked is not None:
        return asked
    use_graph = settings.rag_use_graph if req.use_graph is None else req.use_graph
    return default and use_graph and not req.semantic_only


def _card_on(req: QueryRequest) -> bool:
    return _on(req.use_regnal_card, settings.rag_regnal_card, req)


def _gen_card_on(req: QueryRequest) -> bool:
    return _on(req.use_gen_card, settings.rag_gen_card, req)


async def _card(req: QueryRequest, results: list[dict]) -> Card | None:
    """The chronology card when it is on and the question is one it was confirmed for."""
    if not _card_on(req) or req.retrieval_only or not results:
        return None
    return await chronology_card(req.question, build_context(results), context.active().regnal)


def _gen_card(req: QueryRequest, results: list[dict]) -> gen_card.Card | None:
    """The Genesis age card when it is on and its rule takes the question; never where the regnal
    trigger fires, whether or not a chronology card was built (D3: the GEN confirmation set's
    population is the questions it does not take)."""
    active = context.active()
    if active.gen is None or not _gen_card_on(req) or req.retrieval_only or not results:
        return None
    regnal = active.regnal
    if regnal is not None and regnal_trigger(req.question, regnal.names, regnal.blockers).fired:
        return None
    return gen_card.card_of(req.question, active.gen)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="RAG 聖經查詢",
)
async def rag_query(req: QueryRequest):
    """
    主 RAG 查詢端點。

    流程: 經文引用偵測 → 意圖分類 → 路由檢索 → 去重 → 重排序 → 上下文組裝 →
    （王朝年代題）年表卡,（其餘的創世記年歲題）年歲卡 → 回答生成 → 段號誤當章號的引用改正。
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
    card = await _card(req, results) or _gen_card(req, results)
    answer = await _answer(req, results, card)
    return QueryResponse(
        answer=answer,
        sources=_sources(req, results),
        intent=IntentInfo(type=intent["type"], entities=intent["entities"],
                          verse_refs=[ref.display for ref in intent["verse_refs"]],
                          rejected_refs=intent.get("rejected_refs", [])),
        retrieval_stats=RetrievalStats(**stats),
        aux_card=_aux_card(card),
    )

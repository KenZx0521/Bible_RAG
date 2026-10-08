"""
Multi-strategy retrieval router with 6-route signal-driven architecture.

Routes (utils.retrieval.routes):
    R1: Exact verse reference (book+chapter+verse) → SQL direct lookup
    R2: Chapter + dense (book+chapter, no verse) → chapter passages + dense
    R3: ≥2 persons → dense + book anchors + SQL supplement
    R4: Event keyword → dense + book anchors + SQL supplement
    R5: Cross-reference (≥2 books) → dense + chapter passages + book anchors + SQL
    R6: Place name → dense + book anchors + SQL supplement
    Fallback: dense + book anchors

Then rerank (bge-reranker-v2-m3), rank fusion, the chapter and book-anchor pins,
and on R4/R5 the event registry auxiliary lane, which appends one curated anchor
AFTER the finished top-k when use_graph is on and "event_registry" is among the
graph strategies (the default). R1 has no Neo4j-backed strategy (D-09).
"""

import logging
from dataclasses import dataclass

from config import settings
from database import postgres
from serving import context
from utils import reranker as reranker_mod
from utils.retrieval import candidates as cands
from utils.retrieval import event_registry, routes
from utils.retrieval.dense import SEMANTIC_ARM, retrieve_dense
from utils.retrieval.pins import (cap_book_anchor_entries, fuse_and_rank,
                                  pin_book_anchor_candidates, pin_chapter_candidates)
from utils.signal_detector import QuerySignals, detect_signals
from utils.verse_parser import VerseRef

logger = logging.getLogger(__name__)

AUXILIARY_STRATEGIES = frozenset({"event_registry"})
_EVENT_REGISTRY_ROUTES = ("R4", "R5")


def resolve_graph_strategies(requested: list[str] | None) -> frozenset[str]:
    """Graph strategies allowed for one request: None falls back to the settings."""
    names = settings.rag_graph_strategies if requested is None else requested
    unknown = sorted(set(names) - AUXILIARY_STRATEGIES)
    if unknown:
        raise ValueError(f"unknown graph strategies: {unknown}")
    return frozenset(names)


@dataclass(frozen=True)
class Fusion:
    active: bool
    alpha: float

    @property
    def score_key(self) -> str:
        return "fused_score" if self.active else "rerank_score"


@dataclass
class Gathered:
    route: str
    signals: QuerySignals | None
    candidates: list[dict]
    strategies: list[str]
    errors: dict[str, str]

    @property
    def multi_book(self) -> bool:
        return self.signals is not None and len(self.signals.detected_book_names) > 1


async def _semantic_only(query: str) -> Gathered:
    errors: dict[str, str] = {}
    try:
        raw = await retrieve_dense(query, SEMANTIC_ARM)
    except Exception as exc:  # noqa: BLE001 — recorded in strategy_errors
        logger.warning("Semantic-only retrieval failed: %s", exc)
        errors["semantic"] = repr(exc)[:200]
        raw = []
    return Gathered("semantic_only", None, cands.dedup(raw), ["semantic"], errors)


async def _gather(query: str, verse_refs: list[VerseRef], intent_type: str,
                  entity_names: list[str], keywords: list[str] | None,
                  active: context.Active) -> Gathered:
    signals = detect_signals(query=query, verse_refs=verse_refs, intent_type=intent_type,
                             entity_names=entity_names, keywords=keywords,
                             lexicon=active.lexicon, book_ids=active.book_ids)
    handler = routes.ROUTES.get(signals.route, routes.route_fallback)
    pool, strategies, errors = await handler(routes.RouteInput(query, verse_refs, signals))
    return Gathered(signals.route, signals, pool, strategies, errors)


def _rank(query: str, g: Gathered, k: int, fusion: Fusion) -> list[dict]:
    if g.route == "R1":
        return g.candidates[:k]
    if not g.candidates:
        return []
    try:
        if not fusion.active:
            return reranker_mod.rerank(query, g.candidates, top_k=k, text_key="content")
        # score the whole pool, then blend each rerank_score with the strategy prior
        scored = reranker_mod.rerank(query, g.candidates, top_k=len(g.candidates),
                                     text_key="content")
        ranked = fuse_and_rank(scored, top_k=len(scored), alpha=fusion.alpha)
        return (cap_book_anchor_entries(ranked) if g.multi_book else ranked)[:k]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reranker failed, falling back to weight-based sorting: %s", exc)
        g.errors["rerank"] = repr(exc)[:200]
        return sorted(g.candidates, key=lambda x: x.get("weight", 0), reverse=True)[:k]


def _pin(ranked: list[dict], g: Gathered, verse_refs: list[VerseRef], k: int,
         fusion: Fusion) -> list[dict]:
    """Chapter pin (A書N章), then book-anchor pin; not on R1 or semantic_only."""
    if g.route in ("R1", "semantic_only") or not ranked:
        return ranked
    ranked = pin_chapter_candidates(ranked, g.candidates, verse_refs, top_k=k, min_pins=2,
                                    score_key=fusion.score_key)
    return pin_book_anchor_candidates(ranked, g.candidates, top_k=k, max_pins=2,
                                      score_key=fusion.score_key, book_gate=g.multi_book)


async def _aux_candidate(anchor: str, event: tuple[str, str], pool: dict[str, dict],
                         errors: dict[str, str]) -> dict | None:
    try:
        found = await postgres.get_content_by_id(anchor)
    except Exception as exc:  # noqa: BLE001
        errors["event_registry"] = repr(exc)[:200]
        return None
    if found is None:
        errors["event_registry"] = f"anchor {anchor} is not in the build"
        return None
    found_by = list(cands.labels_of(pool[anchor])) if anchor in pool else []
    return {**found, "source_strategy": "event_registry", "via_event_id": event[0],
            "via_event_name": event[1], "found_by": found_by + ["event_registry"]}


async def _append_event_registry(query: str, ranked: list[dict], g: Gathered, slots: int,
                                 active: context.Active) -> tuple[list[dict], list[str]]:
    """Curated event anchors to append after the finished top-k, and the triggered events.

    Triggers are registry words literally in the question (book names masked),
    never LLM keywords. Events are reported by ev id (via_event_id too); their
    legacy ids are only logged. Appended passages carry no rerank/fused score.
    """
    events = event_registry.match_events(query, active.registry, active.book_names)
    if not events:
        return [], []
    core = [c.get("passage_id") or c["id"] for c in ranked]
    names = {e.id: e.name for e in events}
    pool = {c["id"]: c for c in g.candidates}
    aux = [c for event_id, anchor in event_registry.select_aux_anchors(events, core, slots)
           if (c := await _aux_candidate(anchor, (event_id, names[event_id]), pool, g.errors))]
    logger.info("event_registry: triggered %s (legacy %s), appended %s",
                [e.id for e in events], [list(e.legacy_ids) for e in events],
                [c["id"] for c in aux])
    return aux, [e.id for e in events]


def _stats(g: Gathered, total: int, reranked: int, use_graph: bool,
           allowed: frozenset[str], fusion: Fusion, events: list[str]) -> dict:
    return {
        "strategies_used": g.strategies, "total_candidates": total, "reranked_top_k": reranked,
        "route_used": g.route, "strategy_errors": g.errors, "use_graph": use_graph,
        "graph_strategies": (sorted(allowed) if use_graph and g.route != "semantic_only"
                             else []),
        "fusion_alpha": fusion.alpha if (fusion.active and g.route != "R1") else None,
        "event_registry_events": events,
    }


async def retrieve_and_rerank(
    query: str, verse_refs: list[VerseRef], intent_type: str, entity_names: list[str],
    top_k: int | None = None, keywords: list[str] | None = None, use_graph: bool | None = None,
    semantic_only: bool = False, fusion_alpha: float | None = None,
    graph_strategies: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """Route, rerank, pin and (R4/R5) append event anchors; returns (results, stats).

    use_graph / graph_strategies / fusion_alpha override the settings for one
    request (fusion_alpha forces fusion on); semantic_only skips routing.
    """
    active = context.active()
    k = top_k or settings.default_top_k
    use = settings.rag_use_graph if use_graph is None else use_graph
    allowed = resolve_graph_strategies(graph_strategies)
    fusion = Fusion(fusion_alpha is not None or settings.rag_rank_fusion_enabled,
                    settings.rag_rank_fusion_alpha if fusion_alpha is None else fusion_alpha)
    g = (await _semantic_only(query) if semantic_only else
         await _gather(query, verse_refs, intent_type, entity_names, keywords, active))
    for c in g.candidates:
        c.setdefault("found_by", cands.labels_of(c))
    ranked = _pin(_rank(query, g, k, fusion), g, verse_refs, k, fusion)
    reranked, events = len(ranked), []
    if (g.route in _EVENT_REGISTRY_ROUTES and len(ranked) >= k and use
            and "event_registry" in allowed):
        aux, events = await _append_event_registry(query, ranked, g,
                                                   settings.rag_event_registry_slots, active)
        if aux:
            ranked = ranked + aux
            g.strategies.append("event_registry")
    return ranked, _stats(g, len(g.candidates), reranked, use, allowed, fusion, events)

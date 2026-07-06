"""
Multi-strategy retrieval router with 6-route signal-driven architecture.

Routes:
    R1: Exact verse reference (book+chapter+verse) → SQL direct lookup
    R2: Chapter + semantic (book+chapter, no verse) → SQL chapter filter + Semantic
    R3: Person graph (≥2 persons) → Graph(person) + Semantic + SQL supplement
    R4: Event search (event keyword) → Graph(event) + Semantic + SQL supplement
    R5: Cross-reference (≥2 books) → Semantic seed + Cross-Ref ∥ Graph + SQL
    R6: Place search (place name) → Graph(place) + Semantic + SQL supplement
    Fallback: Semantic only
"""

import asyncio
import logging

from utils.verse_parser import VerseRef
from utils.signal_detector import detect_signals, QuerySignals
from utils.retrieval.verse_retriever import retrieve_by_verse_refs
from utils.retrieval.semantic_retriever import retrieve_semantic
from utils.retrieval.graph_retriever import (
    retrieve_by_entities,
    retrieve_by_events,
    retrieve_by_places,
)
from utils.retrieval.cross_ref_retriever import (
    retrieve_cross_references,
    retrieve_via_cross_references,
)
from utils.retrieval.entity_path_retriever import (
    retrieve_by_entity_path,
    retrieve_by_entity_query,
)
from utils import reranker as reranker_mod
from database import neo4j_db, postgres
from config import settings

logger = logging.getLogger(__name__)

# Lazy import for hybrid retriever
_hybrid_retriever = None


def _get_hybrid_retriever():
    """Lazy load hybrid retriever module."""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        from utils.retrieval import hybrid_retriever
        _hybrid_retriever = hybrid_retriever
    return _hybrid_retriever


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def retrieve_and_rerank(
    query: str,
    verse_refs: list[VerseRef],
    intent_type: str,
    entity_names: list[str],
    top_k: int | None = None,
    keywords: list[str] | None = None,
    use_graph: bool | None = None,
    semantic_only: bool = False,
    fusion_alpha: float | None = None,
) -> tuple[list[dict], dict]:
    """
    Signal-driven multi-strategy retrieval with 6 routes.

    Args:
        use_graph: Per-request override for graph retrieval. None falls back to
            settings.rag_use_graph. When False, graph_retriever and
            cross_ref_retriever calls are skipped in R3/R4/R5/R6.
        semantic_only: When True, bypass signal detection + route dispatch and
            run pure semantic (or hybrid) retrieval only. Skips SQL/graph/cross-ref
            and chapter-pinning. Rerank still applies.
        fusion_alpha: Per-request override for the rank-fusion alpha. None
            falls back to settings (fusion enabled/alpha); a float forces
            fusion on with that alpha (0.0 = pure reranker ordering).

    Returns:
        (top_k_results, retrieval_stats)
    """
    k = top_k or settings.default_top_k
    effective_use_graph = use_graph if use_graph is not None else settings.rag_use_graph

    # Rank fusion: a per-request alpha forces fusion on (A/B sweeps without
    # backend restart); otherwise both switch and alpha come from settings.
    fusion_active = fusion_alpha is not None or settings.rag_rank_fusion_enabled
    effective_alpha = fusion_alpha if fusion_alpha is not None else settings.rag_rank_fusion_alpha
    score_key = "fused_score" if fusion_active else "rerank_score"

    if semantic_only:
        # Bypass signal detection + route dispatch: pure semantic baseline.
        # Always use retrieve_semantic() (BGE-M3 + Qdrant) even if hybrid search
        # is enabled elsewhere, so this mode is a clean semantic-only baseline.
        strategy_errors: dict[str, str] = {}
        try:
            raw = await retrieve_semantic(query)
        except Exception as e:
            logger.warning(f"Semantic-only retrieval failed: {e}")
            strategy_errors["semantic"] = repr(e)[:200]
            raw = []
        candidates = _dedup(raw)
        strategies_used = ["semantic"]
        route = "semantic_only"
    else:
        # Detect signals and select route
        signals = detect_signals(
            query=query,
            verse_refs=verse_refs,
            intent_type=intent_type,
            entity_names=entity_names,
            keywords=keywords,
        )

        route = signals.route

        # Dispatch to route handler
        route_handlers = {
            "R1": _route_r1,
            "R2": _route_r2,
            "R3": _route_r3,
            "R4": _route_r4,
            "R5": _route_r5,
            "R6": _route_r6,
            "fallback": _route_fallback,
        }
        handler = route_handlers.get(route, _route_fallback)
        candidates, strategies_used, strategy_errors = await handler(
            query=query,
            verse_refs=verse_refs,
            entity_names=entity_names,
            signals=signals,
            k=k,
            use_graph=effective_use_graph,
        )

    total_candidates = len(candidates)

    # Rerank (skip for R1 which returns direct matches)
    if route == "R1":
        ranked = candidates[:k]
    elif candidates:
        try:
            if fusion_active:
                # Score the whole pool (the cross-encoder computes every pair
                # anyway; only the truncation differs), then blend each
                # rerank_score with the candidate's strategy prior. This is
                # the last-mile fix for BGE literal surface matches erasing
                # graph signals (2026-05 EQ displacement + 2026-07 TSK noise).
                scored = reranker_mod.rerank(
                    query, candidates, top_k=len(candidates), text_key="content"
                )
                ranked = _fuse_and_rank(scored, top_k=k, alpha=effective_alpha)
            else:
                ranked = reranker_mod.rerank(query, candidates, top_k=k, text_key="content")
        except Exception as e:
            logger.warning(f"Reranker failed, falling back to weight-based sorting: {e}")
            strategy_errors["rerank"] = repr(e)[:200]
            ranked = sorted(candidates, key=lambda x: x.get("weight", 0), reverse=True)[:k]
    else:
        ranked = []

    # Chapter-pin: when the user specified A書N章, guarantee ≥min_pins pericopes
    # from that (book_id, chapter) survive in top-k. R1 is skipped because it
    # already returns exact verse matches without rerank; semantic_only is
    # skipped because it bypasses signal detection and has no chapter context.
    if route not in ("R1", "semantic_only") and ranked:
        ranked = _pin_chapter_candidates(
            ranked=ranked,
            candidates=candidates,
            verse_refs=verse_refs,
            top_k=k,
            min_pins=2,
            score_key=score_key,
        )

    # Entity-query pin: predates rank fusion — it existed to push EQ's
    # modern→ancient bridge past a purely lexical final ordering. With fusion
    # active that signal flows through the weight term continuously, and the
    # 2026-07-06 rerun showed the pin's remaining effect is adverse (rr≈0 EQ
    # noise pinned to top-1 on GENERAL_003/020). Legacy (fusion-off) path
    # keeps it. Skipped on R1 and semantic_only for the same reasons as
    # chapter-pin.
    if not fusion_active and route not in ("R1", "semantic_only") and ranked:
        ranked = _pin_entity_query_candidates(
            ranked=ranked,
            candidates=candidates,
            top_k=k,
            max_pins=2,
            score_key=score_key,
        )

    # Graph/book-anchor pin: book_anchor stays unconditional (user literally
    # named the book). The uncertainty-gated graph pin is superseded by rank
    # fusion for the same reason as the EQ pin above — legacy path only.
    if route not in ("R1", "semantic_only") and ranked:
        ranked = _pin_graph_candidates(
            ranked=ranked,
            candidates=candidates,
            top_k=k,
            max_pins=2,
            score_key=score_key,
            include_uncertainty_pins=not fusion_active,
        )

    # Keyword-exact event pin: a dictionary event keyword matched an Event's
    # name/alias EXACTLY (保羅歸主 == alias of 掃羅的轉變 → act:9:0). The
    # keyword is literally part of the user's query, so this is a curated
    # bridge, not a vector guess — and BGE rerank can still zero it out when
    # the narrative uses a different surface form (act:9 tells 保羅歸主
    # entirely as 掃羅, rr=0.07, fused rank 7). Same unconditional rationale
    # as book_anchor pin; hub events excluded.
    if fusion_active and route not in ("R1", "semantic_only") and ranked:
        ranked = _pin_keyword_event_candidates(
            ranked=ranked,
            candidates=candidates,
            top_k=k,
            score_key=score_key,
        )

    stats = {
        "strategies_used": strategies_used,
        "total_candidates": total_candidates,
        "reranked_top_k": len(ranked),
        "route_used": route,
        "strategy_errors": strategy_errors,
        "use_graph": effective_use_graph,
        "fusion_alpha": effective_alpha if (fusion_active and route != "R1") else None,
    }

    return ranked, stats


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

async def _get_semantic(query: str) -> list[dict]:
    """Get semantic/hybrid results based on configuration."""
    if settings.hybrid_search_enabled:
        hybrid_mod = _get_hybrid_retriever()
        return await hybrid_mod.retrieve_hybrid(query)
    return await retrieve_semantic(query)


def _dedup(candidates: list[dict]) -> list[dict]:
    """Deduplicate candidates by ID, keeping highest weight."""
    seen: dict[str, dict] = {}
    for c in candidates:
        cid = c["id"]
        if cid not in seen or c["weight"] > seen[cid]["weight"]:
            seen[cid] = c
    return list(seen.values())


def _fuse_and_rank(candidates: list[dict], top_k: int, alpha: float) -> list[dict]:
    """Blend the cross-encoder score with the retrieval-strategy prior.

    fused = (1 - alpha) * rerank_score + alpha * weight

    Both terms live in [0, 1]: rerank_score is the BGE sigmoid, weight is the
    per-candidate strategy prior (graph anchors 0.85-0.9, semantic 0.7, TSK
    cross-ref 0.5-0.6, sql_supplement 0.5). At alpha=0.3 a graph anchor out-
    prioritises a TSK neighbour unless the neighbour's raw rerank advantage
    exceeds ~0.11 — big lexical gaps still win, coin flips go to the graph.
    """
    a = min(max(alpha, 0.0), 1.0)
    for c in candidates:
        rr = float(c.get("rerank_score") or 0.0)
        prior = min(max(float(c.get("weight") or 0.5), 0.0), 1.0)
        c["fused_score"] = (1 - a) * rr + a * prior
    ranked = sorted(candidates, key=lambda x: x["fused_score"], reverse=True)
    return ranked[:top_k]


def _extract_book_chapters(candidates: list[dict]) -> list[tuple[str, int]]:
    """Extract unique (book_id, chapter_num) pairs from candidates."""
    pairs: set[tuple[str, int]] = set()
    for c in candidates:
        book = c.get("book_name", "")
        ch = c.get("chapter_num")
        if book and ch is not None:
            # Build book_id from candidate id
            parts = c.get("id", "").split(":")
            if parts:
                book_id = parts[0]
                pairs.add((book_id, int(ch)))
    return list(pairs)


def _pin_chapter_candidates(
    ranked: list[dict],
    candidates: list[dict],
    verse_refs: list[VerseRef],
    top_k: int,
    min_pins: int = 2,
    score_key: str = "rerank_score",
) -> list[dict]:
    """Guarantee chapter-specified pericopes survive rerank by pinning them into top-k.

    When a user specifies a chapter (e.g. 馬太福音第6章), SQL retrieval weights the
    matching pericopes at 0.85+ but the reranker can still drop them in favour of
    semantically adjacent chapters. For each chapter-only VerseRef we ensure at
    least min_pins pericopes from that (book_id, chapter) survive in the returned
    top-k, pulling extras from the pre-rerank pool when needed. Only candidates
    with weight >= 0.85 are eligible (floors out semantic noise). Pinned entries
    get a synthetic score (on `score_key`, the final ranking field — fused_score
    when rank fusion is active) just above the current max so routers/query.py
    does not emit null scores.
    """
    targets: set[tuple[str, int]] = {
        (vr.book_id, vr.chapter) for vr in verse_refs if vr.verse_start is None
    }
    if not targets or not ranked:
        return ranked

    effective_min = min(min_pins, top_k)

    def _match(c: dict, book_id: str, chapter: int) -> bool:
        cid = c.get("id", "")
        parts = cid.split(":") if cid else []
        if not parts or parts[0] != book_id:
            return False
        return c.get("chapter_num") == chapter

    result: list[dict] = list(ranked)
    existing_ids: set[str] = {c["id"] for c in result}

    for book_id, chapter in targets:
        present = sum(1 for c in result if _match(c, book_id, chapter))
        if present >= effective_min:
            continue
        needed = effective_min - present
        pool_matches = [
            c for c in candidates
            if c.get("id") not in existing_ids
            and _match(c, book_id, chapter)
            and c.get("weight", 0) >= 0.85
        ]
        pool_matches.sort(key=lambda c: (-c.get("weight", 0), c.get("id", "")))
        to_pin = pool_matches[:needed]
        if not to_pin:
            continue

        existing_scores = [c.get(score_key) for c in result if c.get(score_key) is not None]
        base_score = max(existing_scores) if existing_scores else 1.0
        for c in to_pin:
            c[score_key] = base_score + 0.01
            existing_ids.add(c["id"])

        result = to_pin + result

    if len(result) > top_k:
        protected: list[dict] = []
        evictable: list[dict] = []
        for c in result:
            if any(_match(c, book_id, chapter) for book_id, chapter in targets):
                protected.append(c)
            else:
                evictable.append(c)
        keep_non_protected = max(0, top_k - len(protected))
        result = protected + evictable[:keep_non_protected]
        result = result[:top_k]

    return result


def _pin_entity_query_candidates(
    ranked: list[dict],
    candidates: list[dict],
    top_k: int,
    max_pins: int = 2,
    score_threshold: float = 0.5,
    allowed_types: tuple[str, ...] = ("Event", "Person"),
    rerank_confidence_threshold: float = 0.3,
    score_key: str = "rerank_score",
) -> list[dict]:
    """Guarantee high-confidence entity_query candidates survive rerank,
    but only when the reranker itself is uncertain.

    BGE-reranker is a lexical-semantic surface matcher: when modern Chinese
    question vocabulary (登山寶訓, 王國分裂) does not appear in ancient Bible
    text, the reranker prefers literally-matching but topically-wrong
    pericopes. entity_query is the only retrieval signal that bridges
    modern→ancient via named entity embeddings; this pin keeps its
    high-confidence outputs from being erased downstream.

    Confidence gate: when ranked[0].rerank_score >= rerank_confidence_threshold,
    pin is skipped entirely. Empirical reason — EQ entity matching has
    failure modes ("耶穌受試探" embedding sits close to "耶穌受難" query;
    hub entities like 耶穌/亞伯拉罕 over-recall; OCR-noise entity names
    like "谷歌大"). When the reranker has a strong signal (top1 >= 0.3)
    these EQ false positives reliably hurt; when reranker is uncertain
    (top1 < 0.3) EQ's bridge is the best available signal even with noise.
    100-Q eval (2026-05-15) showed pinned_high_top1 mean AC 0.497 vs
    no_pin mean AC 0.703 — pin without this gate net-negative.

    Eligibility (when gate passes): via_entity_score is not None
    (EQ-specific metadata) AND via_entity_score > score_threshold AND
    via_entity_type in allowed_types AND not already in `ranked`. Note:
    `_expand_via_entity_query` injects these metadata fields back into
    deduped candidates that semantic/graph already retrieved.

    Selection priority: Event-typed entities first (events anchor the
    action), then Person-typed; within a type, sort by via_entity_score
    desc.

    Synthetic rerank_score uses base+0.005 (vs chapter-pin's base+0.01) so
    chapter-pin still wins on conflicts.
    """
    if not ranked or not candidates:
        return ranked

    # Confidence gate stays on the RAW reranker signal: under fusion ranked[0]
    # is the fused top, so probe the max rerank_score across ranked — same
    # semantics as pre-fusion (ranked[0] was the rerank max by construction).
    top1_score = max((c.get("rerank_score") or 0) for c in ranked)
    if top1_score >= rerank_confidence_threshold:
        return ranked

    existing_ids = {c["id"] for c in ranked}
    eligible = [
        c for c in candidates
        if c.get("via_entity_score") is not None
        and c.get("via_entity_score", 0) > score_threshold
        and c.get("via_entity_type") in allowed_types
        and c.get("id") not in existing_ids
    ]
    if not eligible:
        return ranked

    type_priority = {"Event": 0, "Person": 1}
    eligible.sort(key=lambda c: (
        type_priority.get(c.get("via_entity_type", ""), 99),
        -c.get("via_entity_score", 0),
    ))
    to_pin = eligible[:max_pins]
    if not to_pin:
        return ranked

    existing_scores = [c.get(score_key) for c in ranked if c.get(score_key) is not None]
    base_score = max(existing_scores) if existing_scores else 1.0
    for i, c in enumerate(to_pin):
        c[score_key] = base_score + 0.005 * (len(to_pin) - i)

    pinned_via = [(c["id"], c.get("via_entity_name"), c.get("via_entity_type")) for c in to_pin]
    logger.info("entity_pin: pinned %d EQ candidates: %s", len(to_pin), pinned_via)

    result = to_pin + ranked
    return result[:top_k]


async def _resolve_entity_ids(
    names: list[str],
    type_filter: str | None = None,
    per_name_limit: int = 3,
) -> list[str]:
    """Map entity names → entity_ids via Neo4j. Optional `type_filter` keeps
    only entities whose labels include the given type (e.g. 'Person')."""
    if not names:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for name in names:
        try:
            entities = await neo4j_db.find_entity_by_name(name, limit=per_name_limit)
        except Exception as e:  # noqa: BLE001
            logger.warning("entity_path: name lookup failed for %r: %s", name, e)
            continue
        for entity in entities:
            if type_filter and type_filter not in (entity.get("labels") or []):
                continue
            eid = entity.get("entity_id")
            if eid and eid not in seen:
                seen.add(eid)
                ids.append(eid)
    return ids


async def _expand_via_entity_path(
    entity_names: list[str],
    use_graph: bool,
    errors: dict[str, str],
    route_label: str,
    type_filter: str | None = None,
) -> list[dict]:
    """Expand candidate pool via Entity-Entity edges (FATHER_OF, RULED, ...).

    Skipped silently when use_graph=False, settings.rag_use_entity_path=False,
    or when no Entity-Entity edges have been imported yet (the Cypher returns
    empty in that case, costing one query).
    """
    if not use_graph or not settings.rag_use_entity_path or not entity_names:
        return []
    entity_ids = await _resolve_entity_ids(entity_names, type_filter=type_filter)
    if not entity_ids:
        return []
    try:
        return await retrieve_by_entity_path(
            entity_ids,
            max_hops=settings.rag_entity_path_max_hops,
            limit=settings.rag_entity_path_limit,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("%s entity_path expansion failed: %s", route_label, e)
        errors["entity_path"] = repr(e)[:200]
        return []


async def _expand_via_cross_ref_seeds(
    candidates: list[dict],
    existing_ids: set[str],
    use_graph: bool,
    errors: dict[str, str],
    route_label: str,
) -> list[dict]:
    """Expand candidate pool via N-hop CROSS_REFERENCES from a diversified
    set of seed pericopes.

    Seeds are picked round-robin across source_strategy buckets so a single
    high-weight strategy (e.g. book_anchor 0.9) doesn't monopolize all
    seed slots. This is critical for cross-book questions: 受難週 graph_event
    anchors must keep at least one seed slot so triumphal-entry mat:21:0
    can cross-ref to 撒9:9. Otherwise book_anchor's 撒迦利亞書 picks displace
    all NT seeds and no Zechariah→Matthew bridge is traversed.

    Skips silently when use_graph=False, settings.rag_use_cross_ref_expand=False,
    or no pericope-style seeds are available.
    """
    if not use_graph or not settings.rag_use_cross_ref_expand or not candidates:
        return []

    # Bucket candidates by strategy; within each bucket keep weight-desc order.
    by_strategy: dict[str, list[dict]] = {}
    for c in sorted(candidates, key=lambda x: x.get("weight", 0), reverse=True):
        cid = c.get("id", "")
        if not cid or ":" not in cid:
            continue
        by_strategy.setdefault(c.get("source_strategy", "") or "_unknown", []).append(c)

    # Strategy priority for picking the "first" seed in each round.
    strategy_order = [
        "book_anchor", "graph_event", "graph_person", "graph_place", "graph",
        "cross_reference", "cross_ref_expand", "semantic", "hybrid",
        "sql_chapter", "sql_supplement", "entity_query", "entity_path", "_unknown",
    ]
    buckets = [by_strategy.get(s, []) for s in strategy_order if by_strategy.get(s)]

    seed_ids: list[str] = []
    target = settings.rag_cross_ref_top_seeds
    # Round-robin draw from each non-empty bucket until we hit target.
    while buckets and len(seed_ids) < target:
        progressed = False
        for bucket in buckets:
            if not bucket:
                continue
            c = bucket.pop(0)
            cid = c.get("id", "")
            if cid in seed_ids:
                continue
            seed_ids.append(cid)
            progressed = True
            if len(seed_ids) >= target:
                break
        if not progressed:
            break

    if not seed_ids:
        return []

    try:
        return await retrieve_via_cross_references(
            seed_ids,
            max_hops=settings.rag_cross_ref_max_hops,
            limit=settings.rag_cross_ref_expand_limit,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{route_label} cross_ref_expand failed: {e}")
        errors["cross_ref_expand"] = repr(e)[:200]
        return []


_EQ_METADATA_KEYS = (
    "via_entity_id",
    "via_entity_name",
    "via_entity_type",
    "via_entity_score",
    "via_total_mentions",
    "is_hub",
)


async def _expand_via_entity_query(
    query: str,
    existing_ids: set[str],
    use_graph: bool,
    errors: dict[str, str],
    route_label: str,
    deduped: list[dict] | None = None,
) -> list[dict]:
    """Supplement candidate pool via Qdrant bible_entities vector match.

    Runs BGE-M3 query → bible_entities top-K entities → Neo4j MENTIONS pericopes
    (via retrieve_by_entity_query). Returns ONLY pericopes not already in
    `existing_ids`, capped at settings.rag_entity_query_supplement_cap. Purely
    additive — does not displace existing high-weight semantic candidates.

    Recovers EVENT/PERSON failure cases where dense semantic embedding maps to
    wrong topic (e.g. "王國分裂" → 但以理書 instead of 列王紀上12). Skipped
    silently when use_graph=False or settings.rag_use_entity_query=False.

    When `deduped` is provided, EQ metadata (via_entity_score etc.) is also
    injected into already-existing candidates that EQ recognised. This lets
    downstream entity-pin recognise EQ-validated pericopes even when they
    were originally retrieved by semantic/graph and EQ skipped them as
    duplicates. Without this, mat:5:0 (登山寶訓) attached to entity
    "山上寶訓" gets pulled by semantic, EQ skips it as duplicate, and
    entity-pin can no longer see it.
    """
    if not use_graph or not settings.rag_use_entity_query or not query:
        return []
    try:
        results = await retrieve_by_entity_query(
            query,
            top_k_entities=settings.rag_entity_query_top_k,
            score_threshold=settings.rag_entity_query_score_threshold,
            hub_threshold=settings.rag_entity_query_hub_threshold,
            pericopes_per_entity_normal=settings.rag_entity_query_pericopes_per_entity_normal,
            pericopes_per_entity_hub=settings.rag_entity_query_pericopes_per_entity_hub,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{route_label} entity_query failed: {e}")
        errors["entity_query"] = repr(e)[:200]
        return []
    if not results:
        return []

    if deduped is not None:
        existing_index = {c["id"]: c for c in deduped}
        for r in results:
            existing = existing_index.get(r["id"])
            if existing is None:
                continue
            for k in _EQ_METADATA_KEYS:
                if k in r and existing.get(k) is None:
                    existing[k] = r[k]

    cap = settings.rag_entity_query_supplement_cap
    new_candidates = [c for c in results if c["id"] not in existing_ids][:cap]
    return new_candidates


async def _sql_supplement(book_chapters: list[tuple[str, int]], existing_ids: set[str], limit: int = 5) -> list[dict]:
    """Fetch additional pericopes from specific chapters as supplement."""
    supplements: list[dict] = []
    for book_id, chapter_num in book_chapters[:3]:  # limit to 3 chapters
        pericopes = await postgres.search_pericopes_by_verse_ref(
            book_id=book_id, chapter_num=chapter_num, verse_num=None,
        )
        for p in pericopes:
            if p["id"] not in existing_ids and len(supplements) < limit:
                existing_ids.add(p["id"])
                supplements.append({
                    "id": p["id"],
                    "content": p["content"],
                    "title": p["title"],
                    "book_name": p["book_name"],
                    "chapter_num": p["chapter_num"],
                    "verse_range": p.get("verse_range", ""),
                    "source_strategy": "sql_supplement",
                    "weight": 0.5,
                })
    return supplements


def _apply_weights(candidates: list[dict], weight: float) -> list[dict]:
    """Apply a weight to candidates that don't already have a higher weight."""
    for c in candidates:
        if c.get("weight", 0) < weight:
            c["weight"] = weight
    return candidates


async def _expand_via_book_anchor(
    query: str,
    book_names: list[str],
    existing_ids: set[str],
    errors: dict[str, str],
    route_label: str,
    weight: float = 0.9,
    top_k: int = 10,
) -> list[dict]:
    """Pull additional semantic candidates restricted to the user-named book(s).

    BGE-M3 dense embedding routinely misses the canonical chapter when a query
    pairs `<書名>` with a theme word (e.g. 「耶利米書的新約預言」 ranks 耶26/28/32
    above 耶31, even though 耶31:31-34 is the only place defining 新約). This
    helper runs a Qdrant search with `book_name` filter so the named book always
    contributes seed candidates; they're tagged source_strategy='book_anchor'
    and weighted just below cross_ref so the reranker pin can recover them.
    """
    if not book_names or not query:
        return []
    try:
        results = await retrieve_semantic(query, top_k=top_k, book_filter=book_names)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{route_label} book_anchor retrieval failed: {e}")
        errors["book_anchor"] = repr(e)[:200]
        return []
    if not results:
        return []
    new_candidates: list[dict] = []
    for c in results:
        if c["id"] in existing_ids:
            continue
        c["source_strategy"] = "book_anchor"
        if c.get("weight", 0) < weight:
            c["weight"] = weight
        new_candidates.append(c)
    return new_candidates


_GRAPH_STRATEGIES = ("graph", "graph_person", "graph_event", "graph_place")
_BOOK_ANCHOR_STRATEGY = "book_anchor"


def _pin_graph_candidates(
    ranked: list[dict],
    candidates: list[dict],
    top_k: int,
    max_pins: int = 2,
    rerank_confidence_threshold: float = 0.3,
    score_key: str = "rerank_score",
    include_uncertainty_pins: bool = True,
) -> list[dict]:
    """Pin graph and book_anchor candidates when their topical signal would
    otherwise be erased by the BGE reranker.

    Two regimes:

    * `book_anchor`: pinned UNCONDITIONALLY when present and not already in
      ranked. Rationale — the user explicitly named a book; BGE reranker
      will still prefer same-surname decoys (e.g. Luke 1's priest 撒迦利亞
      over 撒迦利亞書 9:9), so we must guarantee at least one chunk from the
      named book(s) survives. Up to `max_pins` book_anchor entries pinned.

    * graph_* (graph_event/graph_person/graph_place/graph): pinned ONLY when
      `ranked[0].rerank_score < rerank_confidence_threshold`. Same EQ-pin
      gate logic — when reranker is confident, trust it; when uncertain,
      let graph traversal anchors win. Up to `max_pins` graph entries pinned.

    Synthetic rerank_score is base+0.003 for graph and base+0.004 for
    book_anchor, so chapter-pin (+0.01) and EQ-pin (+0.005) still win.
    """
    if not ranked or not candidates:
        return ranked

    existing_ids = {c["id"] for c in ranked}
    existing_scores = [c.get(score_key) for c in ranked if c.get(score_key) is not None]
    base_score = max(existing_scores) if existing_scores else 1.0

    pinned_total: list[dict] = []

    # Book-anchor: unconditional
    book_eligible = [
        c for c in candidates
        if c.get("source_strategy") == _BOOK_ANCHOR_STRATEGY
        and c.get("id") not in existing_ids
    ]
    book_eligible.sort(key=lambda c: -c.get("semantic_score", c.get("weight", 0)))
    for i, c in enumerate(book_eligible[:max_pins]):
        c[score_key] = base_score + 0.004 * (max_pins - i)
        existing_ids.add(c["id"])
        pinned_total.append(c)

    # Graph: gated on RAW reranker uncertainty (see _pin_entity_query_candidates
    # for why the probe is max rerank_score, not ranked[0], under fusion).
    # Suppressed entirely under rank fusion (include_uncertainty_pins=False):
    # fusion carries graph priors continuously, so this pin is redundant there.
    top1_score = max((c.get("rerank_score") or 0) for c in ranked)
    if include_uncertainty_pins and top1_score < rerank_confidence_threshold:
        graph_eligible = [
            c for c in candidates
            if c.get("source_strategy") in _GRAPH_STRATEGIES
            and c.get("id") not in existing_ids
        ]
        strategy_priority = {
            "graph_event": 1, "graph_person": 2, "graph_place": 3, "graph": 4,
        }
        graph_eligible.sort(key=lambda c: (
            strategy_priority.get(c.get("source_strategy", ""), 99),
            -c.get("weight", 0),
        ))
        for i, c in enumerate(graph_eligible[:max_pins]):
            c[score_key] = base_score + 0.003 * (max_pins - i)
            existing_ids.add(c["id"])
            pinned_total.append(c)

    if not pinned_total:
        return ranked

    logger.info(
        "graph_pin: pinned %d candidates: %s",
        len(pinned_total),
        [(c["id"], c.get("source_strategy")) for c in pinned_total],
    )

    result = pinned_total + ranked
    return result[:top_k]


def _pin_keyword_event_candidates(
    ranked: list[dict],
    candidates: list[dict],
    top_k: int,
    max_pins: int = 2,
    hub_cap: int = 25,
    score_key: str = "rerank_score",
) -> list[dict]:
    """Pin the first anchor of events whose name/alias EXACTLY equals a
    detected dictionary event keyword.

    Fires unconditionally (same rationale as the book_anchor pin): the
    keyword is literally present in the user's query and the equality match
    against a curated alias is a dictionary bridge, not a vector guess.
    Constraints keep it surgical — hub events excluded (受難週 mc=76 would
    spray passion-week pericopes), only each event's first anchor (Event
    anchors are ordered book/chapter ASC = narrative start), at most
    `max_pins` events, smallest-mention-count (most specific) events first.
    """
    if not ranked or not candidates:
        return ranked

    existing_ids = {c["id"] for c in ranked}
    eligible = [
        c for c in candidates
        if c.get("keyword_exact")
        and (c.get("via_event_mc") or 0) <= hub_cap
        and c.get("anchor_rank", 99) == 0
        and c.get("id") not in existing_ids
    ]
    if not eligible:
        return ranked

    eligible.sort(key=lambda c: (c.get("via_event_mc") or 0, c.get("id", "")))
    to_pin = eligible[:max_pins]

    existing_scores = [c.get(score_key) for c in ranked if c.get(score_key) is not None]
    base_score = max(existing_scores) if existing_scores else 1.0
    for i, c in enumerate(to_pin):
        c[score_key] = base_score + 0.002 * (len(to_pin) - i)

    logger.info(
        "keyword_event_pin: pinned %s",
        [(c["id"], c.get("via_event_name")) for c in to_pin],
    )
    return (to_pin + ranked)[:top_k]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def _route_r1(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R1: Exact verse reference → SQL direct lookup, skip reranking.

    Fallback to R2 if no results found.
    """
    errors: dict[str, str] = {}
    try:
        candidates = await retrieve_by_verse_refs(verse_refs)
    except Exception as e:
        logger.warning(f"R1 verse retrieval failed: {e}")
        errors["verse_direct"] = repr(e)[:200]
        candidates = []

    if candidates:
        return candidates, ["verse_direct"], errors

    # Fallback to R2
    logger.info("R1 empty, falling back to R2")
    r2_candidates, r2_strategies, r2_errors = await _route_r2(
        query, verse_refs, entity_names, signals, k, use_graph
    )
    errors.update(r2_errors)
    return r2_candidates, r2_strategies, errors


async def _route_r2(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R2: Chapter + semantic → SQL chapter filter (0.9) + Semantic (0.6).

    Graph-agnostic route; use_graph has no effect here.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    all_candidates: list[dict] = []
    weights = settings.route_weights.get("R2", {"sql": 0.9, "semantic": 0.6})

    # SQL chapter retrieval
    if verse_refs:
        try:
            chapter_results = await retrieve_by_verse_refs(verse_refs)
            _apply_weights(chapter_results, weights["sql"])
            for c in chapter_results:
                c["source_strategy"] = "sql_chapter"
            all_candidates.extend(chapter_results)
            strategies.append("sql_chapter")
        except Exception as e:
            logger.warning(f"R2 SQL chapter retrieval failed: {e}")
            errors["sql_chapter"] = repr(e)[:200]

    # Semantic retrieval
    try:
        sem_results = await _get_semantic(query)
        _apply_weights(sem_results, weights["semantic"])
        all_candidates.extend(sem_results)
        strategies.append("semantic")
    except Exception as e:
        logger.warning(f"R2 semantic retrieval failed: {e}")
        errors["semantic"] = repr(e)[:200]

    return _dedup(all_candidates), strategies, errors


async def _route_r3(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R3: Person graph (≥2 persons) → Graph(0.9) + Semantic(0.7) + SQL(0.5).

    When use_graph=False, graph_person is skipped; falls back to semantic + SQL supplement.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights.get("R3", {"graph": 0.9, "semantic": 0.7, "sql": 0.5})

    # Use detected persons for graph retrieval, fall back to entity_names
    person_names = signals.detected_persons or entity_names
    graph_enabled = bool(use_graph and person_names)

    # Parallel: graph (if enabled) + semantic. Placeholder keeps index[0] stable.
    if graph_enabled:
        tasks = [
            asyncio.create_task(retrieve_by_entities(person_names)),
            asyncio.create_task(_get_semantic(query)),
        ]
    else:
        tasks = [
            asyncio.create_task(asyncio.sleep(0)),
            asyncio.create_task(_get_semantic(query)),
        ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates: list[dict] = []

    # Graph results (only when graph_enabled)
    if graph_enabled:
        if not isinstance(results[0], Exception) and results[0]:
            _apply_weights(results[0], weights["graph"])
            for c in results[0]:
                c["source_strategy"] = "graph_person"
            all_candidates.extend(results[0])
            strategies.append("graph_person")
        elif isinstance(results[0], Exception):
            logger.warning(f"R3 graph retrieval failed: {results[0]}")
            errors["graph_person"] = repr(results[0])[:200]

    # Semantic results
    if not isinstance(results[1], Exception) and results[1]:
        _apply_weights(results[1], weights["semantic"])
        all_candidates.extend(results[1])
        strategies.append("semantic")
    elif isinstance(results[1], Exception):
        logger.warning(f"R3 semantic retrieval failed: {results[1]}")
        errors["semantic"] = repr(results[1])[:200]

    deduped = _dedup(all_candidates)

    # Book-anchor: when the query names a book, pull per-book filtered semantic
    # so the reranker pin can later guarantee the named book is represented.
    existing_ids = {c["id"] for c in deduped}
    if signals.detected_book_names:
        anchor = await _expand_via_book_anchor(
            query, signals.detected_book_names, existing_ids, errors, "R3",
        )
        if anchor:
            existing_ids.update(c["id"] for c in anchor)
            deduped.extend(anchor)
            strategies.append("book_anchor")

    # Entity-path expansion: walk Person-relations to find pericopes about
    # related family members or allies. No-op until Entity-Entity edges are
    # imported.
    if person_names:
        entity_expand = await _expand_via_entity_path(
            person_names, use_graph, errors, "R3", type_filter="Person",
        )
        if entity_expand:
            new_entity = [c for c in entity_expand if c["id"] not in existing_ids]
            existing_ids.update(c["id"] for c in new_entity)
            deduped.extend(new_entity)
            strategies.append("entity_path")

    # Cross-ref 2-hop expansion: surface neighbouring pericopes along
    # CROSS_REFERENCES edges from the strongest seeds. Activates the 916
    # hand-curated cross-book edges in the pre-rerank candidate pool.
    expand = await _expand_via_cross_ref_seeds(
        deduped, existing_ids, use_graph, errors, "R3"
    )
    if expand:
        new_expand = [c for c in expand if c["id"] not in existing_ids]
        existing_ids.update(c["id"] for c in new_expand)
        deduped.extend(new_expand)
        strategies.append("cross_ref_expand")

    # Entity-query supplement: BGE-M3 query → bible_entities → Neo4j MENTIONS.
    # Adds pericopes that graph_person + semantic missed, e.g. recovers
    # 出埃及記6 摩西亞倫族譜 for PERSON_QUESTION_004 when entity_path noise
    # otherwise displaces it. Supplement-only; weight 0.6 stays below semantic.
    eq_supplement = await _expand_via_entity_query(query, existing_ids, use_graph, errors, "R3", deduped=deduped)
    if eq_supplement:
        _apply_weights(eq_supplement, weights.get("entity_query", 0.6))
        existing_ids.update(c["id"] for c in eq_supplement)
        deduped.extend(eq_supplement)
        strategies.append("entity_query")

    # SQL supplement from relevant chapters
    book_chapters = _extract_book_chapters(deduped)
    if book_chapters:
        try:
            supplements = await _sql_supplement(book_chapters, existing_ids, limit=3)
            _apply_weights(supplements, weights["sql"])
            deduped.extend(supplements)
            if supplements:
                strategies.append("sql_supplement")
        except Exception as e:
            logger.warning(f"R3 sql_supplement failed: {e}")
            errors["sql_supplement"] = repr(e)[:200]

    return deduped, strategies, errors


async def _route_r4(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R4: Event search → Graph_Event(0.85) + Semantic(0.7) + EntityQuery(0.6) + SQL(0.5).

    graph_event runs whenever event keywords are detected. entity_query runs as
    a separate supplement step (see _expand_via_entity_query) so it never
    displaces semantic top-K. Earlier exclusive design (entity_query OR
    graph_event) was reverted because simulation showed supplement-only
    captures unique recoveries (e.g. EVENT_008 王國分裂) without breaking
    EVENT_014 / 020 where graph_event/semantic already work.

    When use_graph=False, both graph_event and entity_query are skipped.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights.get("R4", {"graph": 0.85, "semantic": 0.7, "sql": 0.5})

    event_keywords = signals.detected_events
    graph_enabled = bool(use_graph and event_keywords)

    # Parallel: graph_event + semantic
    tasks = [asyncio.create_task(_get_semantic(query))]
    if graph_enabled:
        tasks.insert(0, asyncio.create_task(retrieve_by_events(event_keywords)))
    else:
        tasks.insert(0, asyncio.create_task(asyncio.sleep(0)))  # placeholder

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates: list[dict] = []

    # Graph_event results
    if graph_enabled and not isinstance(results[0], Exception) and results[0]:
        _apply_weights(results[0], weights["graph"])
        all_candidates.extend(results[0])
        strategies.append("graph_event")
    elif graph_enabled and isinstance(results[0], Exception):
        logger.warning(f"R4 graph_event retrieval failed: {results[0]}")
        errors["graph_event"] = repr(results[0])[:200]

    # Semantic results
    if not isinstance(results[1], Exception) and results[1]:
        _apply_weights(results[1], weights["semantic"])
        all_candidates.extend(results[1])
        strategies.append("semantic")
    elif isinstance(results[1], Exception):
        logger.warning(f"R4 semantic retrieval failed: {results[1]}")
        errors["semantic"] = repr(results[1])[:200]

    deduped = _dedup(all_candidates)

    # Book-anchor: when query names a book (e.g. 撒迦利亞書 in EVENT context),
    # pull per-book filtered semantic before cross-ref expansion so seeds skew
    # toward the named book.
    existing_ids = {c["id"] for c in deduped}
    if signals.detected_book_names:
        anchor = await _expand_via_book_anchor(
            query, signals.detected_book_names, existing_ids, errors, "R4",
        )
        if anchor:
            existing_ids.update(c["id"] for c in anchor)
            deduped.extend(anchor)
            strategies.append("book_anchor")

    # Cross-ref 2-hop expansion (see _route_r3 for rationale).
    expand = await _expand_via_cross_ref_seeds(
        deduped, existing_ids, use_graph, errors, "R4"
    )
    if expand:
        new_expand = [c for c in expand if c["id"] not in existing_ids]
        existing_ids.update(c["id"] for c in new_expand)
        deduped.extend(new_expand)
        strategies.append("cross_ref_expand")

    # Entity-query supplement: BGE-M3 query → bible_entities → Neo4j MENTIONS.
    # Critical for EVENT cases where dense embedding misses the right book —
    # e.g. "王國分裂" semantically maps to 但以理書 "破裂", but entity
    # 「北方的支派反叛」→ 列王紀上12 is recovered here. Supplement-only.
    eq_supplement = await _expand_via_entity_query(query, existing_ids, use_graph, errors, "R4", deduped=deduped)
    if eq_supplement:
        _apply_weights(eq_supplement, weights.get("entity_query", 0.6))
        existing_ids.update(c["id"] for c in eq_supplement)
        deduped.extend(eq_supplement)
        strategies.append("entity_query")

    # SQL supplement
    book_chapters = _extract_book_chapters(deduped)
    if book_chapters:
        try:
            supplements = await _sql_supplement(book_chapters, existing_ids, limit=3)
            _apply_weights(supplements, weights["sql"])
            deduped.extend(supplements)
            if supplements:
                strategies.append("sql_supplement")
        except Exception as e:
            logger.warning(f"R4 sql_supplement failed: {e}")
            errors["sql_supplement"] = repr(e)[:200]

    return deduped, strategies, errors


async def _route_r5(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R5: Cross-reference → Semantic + SQL_Chapter(0.85) + Cross-Ref(0.85) ∥ Graph(0.75) + SQL(0.4).

    When verse_refs has chapter-only refs (e.g. multi-book query with 哥林多前書15章),
    the specified chapter is pulled via sql_chapter BEFORE the parallel cross-ref/graph
    block so it wins dedup ties and is eligible for chapter-pin in retrieve_and_rerank.

    When use_graph=False, both cross_reference and graph are skipped;
    route degrades to pure semantic + sql_chapter (if any) + SQL supplement.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights.get(
        "R5", {"cross_ref": 0.85, "graph": 0.75, "semantic": 0.65, "sql_chapter": 0.85, "sql": 0.4}
    )

    all_candidates: list[dict] = []

    # First: get semantic seed results
    try:
        sem_results = await _get_semantic(query)
        _apply_weights(sem_results, weights["semantic"])
        all_candidates.extend(sem_results)
        strategies.append("semantic")
    except Exception as e:
        logger.warning(f"R5 semantic retrieval failed: {e}")
        errors["semantic"] = repr(e)[:200]
        sem_results = []

    # SQL chapter retrieval for chapter-only verse_refs. Runs before cross-ref/graph
    # so dedup (strict-greater weight) keeps the sql_chapter entry on ties.
    if verse_refs and any(vr.verse_start is None for vr in verse_refs):
        try:
            chapter_results = await retrieve_by_verse_refs(verse_refs)
            sql_chapter_weight = weights.get("sql_chapter", 0.85)
            _apply_weights(chapter_results, sql_chapter_weight)
            for c in chapter_results:
                c["source_strategy"] = "sql_chapter"
            all_candidates.extend(chapter_results)
            if chapter_results:
                strategies.append("sql_chapter")
        except Exception as e:
            logger.warning(f"R5 SQL chapter retrieval failed: {e}")
            errors["sql_chapter"] = repr(e)[:200]

    deduped = _dedup(all_candidates)

    # Book-anchor: for multi-book queries this is critical — the cross-ref
    # graph only finds Hebrews 8 from Jeremiah 31 if 耶31 is a seed, but BGE
    # semantic routinely picks 耶26/28/32 instead. Pull per-book filtered
    # semantic so each named book contributes seeds.
    existing_ids = {c["id"] for c in deduped}
    if signals.detected_book_names:
        anchor = await _expand_via_book_anchor(
            query, signals.detected_book_names, existing_ids, errors, "R5",
        )
        if anchor:
            existing_ids.update(c["id"] for c in anchor)
            deduped.extend(anchor)
            strategies.append("book_anchor")
            all_candidates.extend(anchor)

    # Parallel: cross-reference from seed + graph (if entities). Both gated on use_graph.
    parallel_tasks = []

    if use_graph:
        # Cross-reference expansion from top semantic seeds. Upgraded to
        # multi-hop when settings.rag_use_cross_ref_expand is True; falls back
        # to legacy 1-hop retrieve_cross_references otherwise (preserves
        # behaviour for callers that explicitly disable the expand flag).
        seed_count = settings.rag_cross_ref_top_seeds
        source_ids = [c["id"] for c in deduped[:seed_count] if ":" in c["id"]]
        if source_ids:
            if settings.rag_use_cross_ref_expand:
                parallel_tasks.append(("cross_ref", asyncio.create_task(
                    retrieve_via_cross_references(
                        source_ids,
                        max_hops=settings.rag_cross_ref_max_hops,
                        limit=settings.rag_cross_ref_expand_limit,
                    )
                )))
            else:
                parallel_tasks.append(("cross_ref", asyncio.create_task(
                    retrieve_cross_references(source_ids, top_k=10)
                )))

        # Graph retrieval if entities available
        if entity_names:
            parallel_tasks.append(("graph", asyncio.create_task(
                retrieve_by_entities(entity_names)
            )))

        # Graph_event for detected event keywords (e.g. 大使命 in a multi-book
        # creation→great-commission→revelation query). R5 by default only walks
        # cross-ref + entity graph; without this branch, new Events like 大使命
        # are never reached even though they exist as graph anchors.
        if signals.detected_events:
            parallel_tasks.append(("graph_event", asyncio.create_task(
                retrieve_by_events(signals.detected_events)
            )))

    if parallel_tasks:
        task_results = await asyncio.gather(
            *[t[1] for t in parallel_tasks], return_exceptions=True
        )
        for (label, _), result in zip(parallel_tasks, task_results):
            if isinstance(result, Exception):
                logger.warning(f"R5 {label} retrieval failed: {result}")
                errors[label if label != "cross_ref" else "cross_reference"] = repr(result)[:200]
                continue
            if result:
                if label == "cross_ref" and settings.rag_use_cross_ref_expand:
                    # Multi-hop expansion candidates already carry votes-aware
                    # per-candidate weights (curated 0.75 / TSK 0.5-0.6).
                    # Blanket-raising them to the route's 0.85 was what let
                    # TSK topical neighbours outrank narrative-correct seeds
                    # (GENERAL_013, 2026-07-06 eval).
                    pass
                else:
                    w = weights.get(label, weights.get("cross_ref", 0.85))
                    _apply_weights(result, w)
                all_candidates.extend(result)
                strategies.append(label if label != "cross_ref" else "cross_reference")

    deduped = _dedup(all_candidates)

    # Entity-query supplement: helps cross-book theology queries by surfacing
    # pericopes via shared Theme/Event entities (e.g. theme:xinyue 連結 耶利米書31
    # 與 希伯來書8). Supplement-only after the parallel cross_ref/graph block so
    # it never displaces semantic seeds.
    existing_ids = {c["id"] for c in deduped}
    eq_supplement = await _expand_via_entity_query(query, existing_ids, use_graph, errors, "R5", deduped=deduped)
    if eq_supplement:
        _apply_weights(eq_supplement, weights.get("entity_query", 0.6))
        existing_ids.update(c["id"] for c in eq_supplement)
        deduped.extend(eq_supplement)
        strategies.append("entity_query")

    # SQL supplement
    book_chapters = _extract_book_chapters(deduped)
    if book_chapters:
        try:
            supplements = await _sql_supplement(book_chapters, existing_ids, limit=3)
            _apply_weights(supplements, weights["sql"])
            deduped.extend(supplements)
            if supplements:
                strategies.append("sql_supplement")
        except Exception as e:
            logger.warning(f"R5 sql_supplement failed: {e}")
            errors["sql_supplement"] = repr(e)[:200]

    return deduped, strategies, errors


async def _route_r6(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """R6: Place search → Graph_Place(0.85) + Semantic(0.7) + SQL(0.5).

    When use_graph=False, graph_place is skipped.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights.get("R6", {"graph": 0.85, "semantic": 0.7, "sql": 0.5})

    place_names = signals.detected_places
    graph_enabled = bool(use_graph and place_names)

    # Parallel: graph place (if enabled) + semantic
    tasks = [asyncio.create_task(_get_semantic(query))]
    if graph_enabled:
        tasks.insert(0, asyncio.create_task(retrieve_by_places(place_names)))
    else:
        tasks.insert(0, asyncio.create_task(asyncio.sleep(0)))  # placeholder

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates: list[dict] = []

    # Graph place results
    if graph_enabled and not isinstance(results[0], Exception) and results[0]:
        _apply_weights(results[0], weights["graph"])
        all_candidates.extend(results[0])
        strategies.append("graph_place")
    elif graph_enabled and isinstance(results[0], Exception):
        logger.warning(f"R6 graph place retrieval failed: {results[0]}")
        errors["graph_place"] = repr(results[0])[:200]

    # Semantic results
    if not isinstance(results[1], Exception) and results[1]:
        _apply_weights(results[1], weights["semantic"])
        all_candidates.extend(results[1])
        strategies.append("semantic")
    elif isinstance(results[1], Exception):
        logger.warning(f"R6 semantic retrieval failed: {results[1]}")
        errors["semantic"] = repr(results[1])[:200]

    deduped = _dedup(all_candidates)

    # Book-anchor: catches single-book queries (e.g. 撒迦利亞書 在受難週應驗)
    # that route to R6 via a place mention; without this, only place-graph
    # candidates would represent the named book.
    existing_ids = {c["id"] for c in deduped}
    if signals.detected_book_names:
        anchor = await _expand_via_book_anchor(
            query, signals.detected_book_names, existing_ids, errors, "R6",
        )
        if anchor:
            existing_ids.update(c["id"] for c in anchor)
            deduped.extend(anchor)
            strategies.append("book_anchor")

    # Entity-path expansion (Place-rooted): walk LOCATED_IN, NEAR, RULED-by-Person, etc.
    if place_names:
        entity_expand = await _expand_via_entity_path(
            place_names, use_graph, errors, "R6", type_filter="Place",
        )
        if entity_expand:
            new_entity = [c for c in entity_expand if c["id"] not in existing_ids]
            existing_ids.update(c["id"] for c in new_entity)
            deduped.extend(new_entity)
            strategies.append("entity_path")

    # Cross-ref 2-hop expansion (see _route_r3 for rationale).
    expand = await _expand_via_cross_ref_seeds(
        deduped, existing_ids, use_graph, errors, "R6"
    )
    if expand:
        new_expand = [c for c in expand if c["id"] not in existing_ids]
        existing_ids.update(c["id"] for c in new_expand)
        deduped.extend(new_expand)
        strategies.append("cross_ref_expand")

    # Entity-query supplement: e.g. mis-routed PERSON_QUESTION_005 葉忒羅 题
    # ended up here (R6 place route) due to 米甸 → R6. EQ supplement recovers
    # 出埃及記3/4/18 via Person/Theme entities the place graph misses.
    eq_supplement = await _expand_via_entity_query(query, existing_ids, use_graph, errors, "R6", deduped=deduped)
    if eq_supplement:
        _apply_weights(eq_supplement, weights.get("entity_query", 0.6))
        existing_ids.update(c["id"] for c in eq_supplement)
        deduped.extend(eq_supplement)
        strategies.append("entity_query")

    # SQL supplement
    book_chapters = _extract_book_chapters(deduped)
    if book_chapters:
        try:
            supplements = await _sql_supplement(book_chapters, existing_ids, limit=3)
            _apply_weights(supplements, weights["sql"])
            deduped.extend(supplements)
            if supplements:
                strategies.append("sql_supplement")
        except Exception as e:
            logger.warning(f"R6 sql_supplement failed: {e}")
            errors["sql_supplement"] = repr(e)[:200]

    return deduped, strategies, errors


async def _route_fallback(
    query: str,
    verse_refs: list[VerseRef],
    entity_names: list[str],
    signals: QuerySignals,
    k: int,
    use_graph: bool,
) -> tuple[list[dict], list[str], dict[str, str]]:
    """Fallback: Semantic + book-anchor (when book named). Graph-agnostic.

    Single-book questions like 「撒迦利亞書...在受難週應驗?」 land here when no
    chapter/event/person/place signal fires. Book-anchor ensures the named
    book is represented even though no other strategy ran.
    """
    strategy_name = "hybrid" if settings.hybrid_search_enabled else "semantic"
    strategies: list[str] = []
    errors: dict[str, str] = {}
    try:
        candidates = await _get_semantic(query)
        strategies.append(strategy_name)
    except Exception as e:
        logger.warning(f"Fallback semantic retrieval failed: {e}")
        errors[strategy_name] = repr(e)[:200]
        candidates = []

    deduped = _dedup(candidates)
    existing_ids = {c["id"] for c in deduped}
    if signals.detected_book_names:
        anchor = await _expand_via_book_anchor(
            query, signals.detected_book_names, existing_ids, errors, "fallback",
        )
        if anchor:
            deduped.extend(anchor)
            strategies.append("book_anchor")

    return deduped, strategies, errors

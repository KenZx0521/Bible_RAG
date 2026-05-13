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

    Returns:
        (top_k_results, retrieval_stats)
    """
    k = top_k or settings.default_top_k
    effective_use_graph = use_graph if use_graph is not None else settings.rag_use_graph

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
        )

    stats = {
        "strategies_used": strategies_used,
        "total_candidates": total_candidates,
        "reranked_top_k": len(ranked),
        "route_used": route,
        "strategy_errors": strategy_errors,
        "use_graph": effective_use_graph,
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
) -> list[dict]:
    """Guarantee chapter-specified pericopes survive rerank by pinning them into top-k.

    When a user specifies a chapter (e.g. 馬太福音第6章), SQL retrieval weights the
    matching pericopes at 0.85+ but the reranker can still drop them in favour of
    semantically adjacent chapters. For each chapter-only VerseRef we ensure at
    least min_pins pericopes from that (book_id, chapter) survive in the returned
    top-k, pulling extras from the pre-rerank pool when needed. Only candidates
    with weight >= 0.85 are eligible (floors out semantic noise). Pinned entries
    get a synthetic rerank_score just above the current max so routers/query.py
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

        existing_scores = [c.get("rerank_score") for c in result if c.get("rerank_score") is not None]
        base_score = max(existing_scores) if existing_scores else 1.0
        for c in to_pin:
            c["rerank_score"] = base_score + 0.01
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
    """Expand candidate pool via N-hop CROSS_REFERENCES from top-N seeds.

    Picks the highest-weight pericope candidates as seeds, traverses
    CROSS_REFERENCES up to settings.rag_cross_ref_max_hops, and returns the
    neighbouring pericopes as new candidates. Caller is responsible for
    merging into the dedup pool.

    Skips silently when use_graph=False, settings.rag_use_cross_ref_expand=False,
    or no pericope-style seeds are available.
    """
    if not use_graph or not settings.rag_use_cross_ref_expand or not candidates:
        return []

    # Pericope IDs follow "<book>:<chapter>:<pericope>" pattern; chunks/verse
    # IDs include extra segments. Filter to entries that look like pericopes.
    sorted_candidates = sorted(candidates, key=lambda c: c.get("weight", 0), reverse=True)
    seed_ids: list[str] = []
    for c in sorted_candidates:
        cid = c.get("id", "")
        if cid and ":" in cid and cid not in seed_ids:
            seed_ids.append(cid)
        if len(seed_ids) >= settings.rag_cross_ref_top_seeds:
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

    # Entity-path expansion: walk Person-relations to find pericopes about
    # related family members or allies. No-op until Entity-Entity edges are
    # imported.
    existing_ids = {c["id"] for c in deduped}
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
    """R4: Event search → Graph_Event(0.85) + Semantic(0.7) + SQL(0.5).

    When settings.rag_use_entity_query=True, retrieve_by_events is replaced by
    retrieve_by_entity_query (BGE-M3 vector match against bible_entities, no
    type filter). Rationale: Event entity canonical_names are fine-grained
    action descriptions that fail substring match against textbook-level
    keywords like 巴別塔/登山寶訓, causing 52.9% R4 graph_event miss rate.

    When use_graph=False, graph branch is skipped regardless of flag.
    """
    strategies: list[str] = []
    errors: dict[str, str] = {}
    weights = settings.route_weights.get("R4", {"graph": 0.85, "semantic": 0.7, "sql": 0.5})

    event_keywords = signals.detected_events
    graph_enabled = bool(use_graph and event_keywords)
    use_entity_query = settings.rag_use_entity_query

    # Parallel: graph (entity_query or graph_event) + semantic
    tasks = [asyncio.create_task(_get_semantic(query))]
    if graph_enabled and use_entity_query:
        tasks.insert(0, asyncio.create_task(retrieve_by_entity_query(
            query,
            top_k_entities=settings.rag_entity_query_top_k,
            score_threshold=settings.rag_entity_query_score_threshold,
            hub_threshold=settings.rag_entity_query_hub_threshold,
            pericopes_per_entity_normal=settings.rag_entity_query_pericopes_per_entity_normal,
            pericopes_per_entity_hub=settings.rag_entity_query_pericopes_per_entity_hub,
        )))
        graph_strategy_label = "entity_query"
    elif graph_enabled:
        tasks.insert(0, asyncio.create_task(retrieve_by_events(event_keywords)))
        graph_strategy_label = "graph_event"
    else:
        tasks.insert(0, asyncio.create_task(asyncio.sleep(0)))  # placeholder
        graph_strategy_label = None

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates: list[dict] = []

    # Graph results (entity_query when flag is on, otherwise graph_event)
    if graph_enabled and not isinstance(results[0], Exception) and results[0]:
        _apply_weights(results[0], weights["graph"])
        all_candidates.extend(results[0])
        strategies.append(graph_strategy_label)
    elif graph_enabled and isinstance(results[0], Exception):
        logger.warning(f"R4 {graph_strategy_label} retrieval failed: {results[0]}")
        errors[graph_strategy_label] = repr(results[0])[:200]

    # Semantic results
    if not isinstance(results[1], Exception) and results[1]:
        _apply_weights(results[1], weights["semantic"])
        all_candidates.extend(results[1])
        strategies.append("semantic")
    elif isinstance(results[1], Exception):
        logger.warning(f"R4 semantic retrieval failed: {results[1]}")
        errors["semantic"] = repr(results[1])[:200]

    deduped = _dedup(all_candidates)

    # Cross-ref 2-hop expansion (see _route_r3 for rationale).
    existing_ids = {c["id"] for c in deduped}
    expand = await _expand_via_cross_ref_seeds(
        deduped, existing_ids, use_graph, errors, "R4"
    )
    if expand:
        new_expand = [c for c in expand if c["id"] not in existing_ids]
        existing_ids.update(c["id"] for c in new_expand)
        deduped.extend(new_expand)
        strategies.append("cross_ref_expand")

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
                w = weights.get(label, weights.get("cross_ref", 0.85))
                _apply_weights(result, w)
                all_candidates.extend(result)
                strategies.append(label if label != "cross_ref" else "cross_reference")

    deduped = _dedup(all_candidates)

    # SQL supplement
    existing_ids = {c["id"] for c in deduped}
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

    # Entity-path expansion (Place-rooted): walk LOCATED_IN, NEAR, RULED-by-Person, etc.
    existing_ids = {c["id"] for c in deduped}
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
    """Fallback: Semantic only. Graph-agnostic."""
    strategy_name = "hybrid" if settings.hybrid_search_enabled else "semantic"
    errors: dict[str, str] = {}
    try:
        candidates = await _get_semantic(query)
    except Exception as e:
        logger.warning(f"Fallback semantic retrieval failed: {e}")
        errors[strategy_name] = repr(e)[:200]
        candidates = []

    return _dedup(candidates), [strategy_name], errors

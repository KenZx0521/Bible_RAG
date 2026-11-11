"""The graph side of a request's retrieval: the walk and the kinship card, on the gathered pool.

Runs after a route gathered its pool and before ranking, on the routes that have no written reference
to look up (R3-R6 and fallback), with the graph on and the strategy allowed, on a build with a graph.
Everywhere else it sends no Cypher. Nothing here can fail a request: Neo4j not answering, and any bug
below, becomes a ``skip_reason`` in the stats and the question goes on without the graph.

The kinship card leaves a question to the chronology and Genesis cards when their own rule claims it,
whether or not they then give a card: the regnal trigger fired (its card can still abstain), or the
Genesis rule found its chain pair (a fired trigger, or one abstaining after that, from step 6 on; its
steps 2-5 say the question is not its own). This checks their triggers and not their cards: those
run later, and only when generating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import settings
from database import neo4j_db
from serving import context
from serving import graph as serving_graph
from utils import gencard
from utils.kg import kin_card
from utils.kg.kin_card import KinCard
from utils.regnal.trigger import trigger as regnal_trigger
from utils.retrieval import graph_walk
from utils.retrieval.graph_walk import Walk

logger = logging.getLogger(__name__)

ROUTES = frozenset({"R3", "R4", "R5", "R6", "fallback"})
WALK, KIN = "graph_walk", "kin_card"
KIN_EVIDENCE = "kin_evidence"
ERROR = "error"
_GEN_CHAIN_STEP = 6     # gencard's step 6 on read a question with exactly one chain pair


@dataclass(frozen=True)
class GraphSide:
    walk: Walk | None = None
    kin: KinCard | None = None


def other_card_claims(question: str, active: context.Active) -> bool:
    """Whether the chronology or the Genesis card's rule claims the question."""
    regnal = active.regnal
    if regnal is not None and regnal_trigger(question, regnal.names, regnal.blockers).fired:
        return True
    if active.gen is None:
        return False
    hit = gencard.trigger(question, active.gen)
    return hit.fired or hit.step >= _GEN_CHAIN_STEP


async def _walk(query: str, pool: list[dict], strategies: list[str], errors: dict[str, str],
                active: context.Active) -> Walk:
    try:
        walk = await graph_walk.walk(graph_walk.seed_passages(pool), graph_walk.seed_names(query, active.lexicon),
                                     active.build.build_id)
    except Exception as exc:  # noqa: BLE001 — the question goes on without the graph
        logger.warning("graph_walk failed: %r", exc)
        return Walk(skip_reason=ERROR)
    weights = graph_walk.walk_weights(walk.passages)
    if weights:
        await graph_walk.absorb(pool, weights, graph_walk.LABEL, errors)
        strategies.append(graph_walk.LABEL)
    return walk


async def _kin(query: str, pool: list[dict], strategies: list[str], errors: dict[str, str],
               active: context.Active) -> KinCard:
    try:
        card = await kin_card.build(query, pool, active.lexicon, active.build.build_id)
    except Exception as exc:  # noqa: BLE001 — the question goes on without the card
        logger.warning("kin_card failed: %r", exc)
        return kin_card.skipped(ERROR)
    if card.passages:
        await graph_walk.absorb(pool, {pid: settings.kin_evidence_weight for pid in card.passages},
                                KIN_EVIDENCE, errors)
        strategies.append(KIN_EVIDENCE)
    return card


async def _ready_or_skip() -> str | None:
    """None when the graph can be read, else why not."""
    status = await serving_graph.usable()
    return None if status.ready else status.state


async def run(query: str, pool: list[dict], strategies: list[str], errors: dict[str, str],
              allowed: frozenset[str], active: context.Active) -> GraphSide:
    """What the graph adds to ``pool`` (in place) and the card it found for the prompt. Never raises."""
    try:
        return await _run(query, pool, strategies, errors, allowed, active)
    except Exception as exc:  # noqa: BLE001 — the question goes on without the graph
        logger.warning("graph side failed: %r", exc)
        return GraphSide(Walk(skip_reason=ERROR) if WALK in allowed else None,
                         kin_card.skipped(ERROR) if KIN in allowed else None)


async def _run(query: str, pool: list[dict], strategies: list[str], errors: dict[str, str],
               allowed: frozenset[str], active: context.Active) -> GraphSide:
    walks = WALK in allowed
    asks = (KIN in allowed and kin_card.wants(query, active.lexicon)
            and not other_card_claims(query, active))
    if not walks and not asks:
        return GraphSide()
    not_ready = await _ready_or_skip()
    if not_ready:
        return GraphSide(Walk(skip_reason=not_ready) if walks else None,
                         kin_card.skipped(not_ready) if asks else None)
    walk = await _walk(query, pool, strategies, errors, active) if walks else None
    if not asks:
        return GraphSide(walk)
    if walk is not None and walk.skip_reason == neo4j_db.TIMEOUT:      # one timeout skips the whole question
        return GraphSide(walk, kin_card.skipped(neo4j_db.TIMEOUT))
    return GraphSide(walk, await _kin(query, pool, strategies, errors, active))

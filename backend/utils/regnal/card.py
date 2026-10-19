"""The chronology card of one question: trigger, seed call, engine (experiment A's G-auto arm).

``chronology_card`` returns None, and the answer is generated the ordinary way, whenever the
trigger does not take the question, there are no passages, the seed call fails or names no
king the layer resolves, or the engine writes no derivation line. Otherwise the card's text is
the auxiliary block the generator gets, exactly as experiment A built it.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from config import settings
from utils.llm import get_llm_client
from utils.regnal import engine
from utils.regnal.layer import RegnalLayer
from utils.regnal.seeds import SEED_SYSTEM, parse_seeds, seed_user
from utils.regnal.trigger import trigger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Card:
    text: str                                # the auxiliary block (rows, then derivation lines)
    seeds: tuple[tuple[str, str], ...]       # (kingdom, name) as the seed call named them
    kings: tuple[str, ...]                   # the layer nodes the seeds resolved to
    lines: int                               # derivation lines in the card
    evidence: tuple[str, ...]                # verse keys of the rows' layer evidence
    layer_sha256: str


async def seed_call(question: str, context: str) -> str:
    llm = get_llm_client()
    return await llm.chat(
        messages=[{"role": "system", "content": SEED_SYSTEM},
                  {"role": "user", "content": seed_user(context, question)}],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    ) or ""


def card_from_seeds(layer: RegnalLayer, question: str, seed_text: str) -> Card | None:
    """The card of a seed call's output (arms_a.item_arms, G-auto); None when it abstains."""
    return card_from_parsed(layer, question, parse_seeds(seed_text))


def card_from_parsed(layer: RegnalLayer, question: str, seeds: list[tuple[str, str]]) -> Card | None:
    V = layer.view
    ids = list(dict.fromkeys(x for x in (engine.resolve(V, kd, nm, question) for kd, nm in seeds) if x))
    if not ids:
        return None
    built = engine.cards(V, ids)
    if built["g_block"] is None:
        return None
    evidence = dict.fromkeys(v for y in built["rows"] for v in V.nodes[y]["evidence"])
    return Card(built["g_block"], tuple(seeds), tuple(ids), len(built["lines"]), tuple(evidence),
                layer.sha256)


def _qhash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


async def chronology_card(question: str, context: str, layer: RegnalLayer | None) -> Card | None:
    """``context``: the generator's passage blocks (``generator.build_context``)."""
    if layer is None or not context:
        return None
    hit = trigger(question, layer.names)
    if not hit.fired:
        return None
    try:
        seed_text = await seed_call(question, context)
    except Exception as exc:  # noqa: BLE001 — no card, the ordinary answer still comes
        logger.warning("regnal card q=%s: seed call failed: %r", _qhash(question), exc)
        return None
    seeds = parse_seeds(seed_text)
    card = card_from_parsed(layer, question, seeds)
    logger.info("regnal card q=%s cues=%s kings=%s seeds=%s card=%s", _qhash(question),
                list(hit.cues), list(hit.kings), seeds, f"{card.lines} lines" if card else "none")
    return card

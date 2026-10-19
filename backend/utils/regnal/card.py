"""The chronology card of one question: trigger, seeds, engine.

The seeds come from the rules first (``seeds.rule_seeds``: chain node ids read from the
question, no LLM call, ``Card.seed_source`` "rule"). Only when the rules abstain does
experiment A's G-auto seed path run, unchanged: the gemma seed call, ``parse_seeds`` and
``engine.resolve`` (seed_source "gemma"). The confirmed arm used the gemma seeds alone, so a
rule-seeded card can differ from the card experiment A built for the same question.

``chronology_card`` returns None, and the answer is generated the ordinary way, whenever the
trigger does not take the question (a question whose king names are all blocked, such as
押沙龍, is not taken), there are no passages, the engine writes no derivation line, or, on
the fallback, the seed call fails or names no king the layer resolves. Otherwise the card's
text is the auxiliary block the generator gets.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from config import settings
from utils.llm import get_llm_client
from utils.regnal import engine
from utils.regnal.layer import RegnalLayer
from utils.regnal.seeds import SEED_SYSTEM, parse_seeds, rule_seeds, seed_user
from utils.regnal.trigger import trigger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Card:
    text: str                                # the auxiliary block (rows, then derivation lines)
    seeds: tuple[tuple[str, str], ...]       # (kingdom, name): the seed call's, or the rule nodes'
    kings: tuple[str, ...]                   # the layer nodes the seeds resolved to
    lines: int                               # derivation lines in the card
    evidence: tuple[str, ...]                # verse keys of the rows' layer evidence
    layer_sha256: str
    seed_source: str                         # "rule" (rule_seeds) or "gemma" (the seed call)


async def seed_call(question: str, context: str) -> str:
    llm = get_llm_client()
    return await llm.chat(
        messages=[{"role": "system", "content": SEED_SYSTEM},
                  {"role": "user", "content": seed_user(context, question)}],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    ) or ""


def _card(layer: RegnalLayer, ids: list[str], seeds: list[tuple[str, str]], seed_source: str) -> Card | None:
    V = layer.view
    built = engine.cards(V, ids)
    if built["g_block"] is None:
        return None
    evidence = dict.fromkeys(v for y in built["rows"] for v in V.nodes[y]["evidence"])
    return Card(built["g_block"], tuple(seeds), tuple(ids), len(built["lines"]), tuple(evidence),
                layer.sha256, seed_source)


def card_from_seeds(layer: RegnalLayer, question: str, seed_text: str) -> Card | None:
    """The card of a seed call's output (arms_a.item_arms, G-auto); None when it abstains."""
    return card_from_parsed(layer, question, parse_seeds(seed_text))


def card_from_parsed(layer: RegnalLayer, question: str, seeds: list[tuple[str, str]]) -> Card | None:
    V = layer.view
    ids = list(dict.fromkeys(x for x in (engine.resolve(V, kd, nm, question) for kd, nm in seeds) if x))
    return _card(layer, ids, seeds, "gemma") if ids else None


def card_from_rule(layer: RegnalLayer, ids: tuple[str, ...]) -> Card | None:
    """The card of rule seeds (chain node ids); its seeds are the nodes' (kingdom, name)."""
    V = layer.view
    seeds = [(V.nodes[x]["kingdom"], V.nodes[x]["name"]) for x in ids]
    return _card(layer, list(ids), seeds, "rule") if ids else None


def _qhash(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


async def chronology_card(question: str, context: str, layer: RegnalLayer | None) -> Card | None:
    """``context``: the generator's passage blocks (``generator.build_context``)."""
    if layer is None or not context:
        return None
    hit = trigger(question, layer.names, layer.blockers)
    if not hit.fired:
        return None
    rule = rule_seeds(layer, question)
    if rule.ids:
        card, seeds = card_from_rule(layer, rule.ids), list(rule.ids)
    else:
        try:
            seed_text = await seed_call(question, context)
        except Exception as exc:  # noqa: BLE001 — no card, the ordinary answer still comes
            logger.warning("regnal card q=%s rule=%r: seed call failed: %r", _qhash(question),
                           rule.reason, exc)
            return None
        seeds = parse_seeds(seed_text)
        card = card_from_parsed(layer, question, seeds)
    logger.info("regnal card q=%s cues=%s kings=%s seed_source=%s rule=%r seeds=%s card=%s",
                _qhash(question), list(hit.cues), list(hit.kings), "rule" if rule.ids else "gemma",
                rule.reason, seeds, f"{card.lines} lines" if card else "none")
    return card

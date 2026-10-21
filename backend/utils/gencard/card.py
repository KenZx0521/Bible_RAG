"""The Genesis age card (prereg §4.1 arm G, §5.1): ``card(question, L)`` and ``card_for_seeds(seeds, L)``.

``card`` is G: the rule seeds (``seeds.rule_seeds``) and, on them, stage-0's G block, exactly as
engine_x.card's Genesis branch builds it (``engine.gen_parts``, ``engine.fit`` to 900 characters,
``engine.render``); None when the rule abstains (no fallback). ``Card.t_block`` is T-rows, the same kept
rows without the derived lines. ``card_for_seeds`` builds the card of given seeds: G-ref on the gold pair,
and the equivalence test with engine_x.card. ``Card.covers(gold)`` is engine.covered: some derived line
holds the gold in a unit the key accepts (ages or years, as stage-0's F1/F5 keys). Standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import engine
from .names import Layer
from .seeds import OK, rule_seeds

GIVEN = "given"
ARITH_CLASSES = ("A", "Y")                   # items_x.arith_key(gold, ["A", "Y"], …) of F1 and F5


@dataclass(frozen=True)
class Card:
    seeds: tuple[str, ...]                   # layer ids in chain order
    reason: str                              # seeds.OK (rule seeds) or GIVEN
    g_block: str                             # arm G: kept rows, A's header, the derived lines
    t_block: str                             # arm T-rows: the same kept rows only
    rows: tuple[str, ...]                    # kept row ids
    lines: tuple[tuple[str, str], ...]       # (head, payload) of the kept derived lines
    tags: tuple[tuple, ...]                  # (kind, seeds, k, value, unit) of each kept line
    dropped_rows: int
    dropped_lines: int

    @property
    def chars_g(self) -> int:
        return len(self.g_block)

    @property
    def chars_t(self) -> int:
        return len(self.t_block)

    def covers(self, gold: int, classes: tuple[str, ...] = ARITH_CLASSES) -> bool:
        """Some kept derived line holds the gold (engine.covered, stage-0's definition)."""
        kept = [{"kind": k, "seeds": list(s), "k": kk, "value": v, "unit": u, "payload": p}
                for (k, s, kk, v, u), (_h, p) in zip(self.tags, self.lines)]
        return engine.covered({"gold": gold, "keys": [{"type": "arith", "classes": list(classes)}]}, kept)


def card_for_seeds(seeds, L: Layer, cap: int = engine.CAP_CHARS, reason: str = GIVEN) -> Card:
    """The card of one or two same-chapter layer ids (ValueError otherwise, as engine.gen_window)."""
    window, core, texts, lines = engine.gen_parts(L.gen, list(seeds))
    rows, kept, dropped_rows, dropped_lines = engine.fit(texts, window, core, lines, cap)
    pairs, row_texts = tuple((ln["head"], ln["payload"]) for ln in kept), [texts[y] for y in rows]
    return Card(seeds=tuple(engine.gen_window(L.gen, list(seeds))[0]), reason=reason,
                g_block=engine.render(row_texts, pairs), t_block=engine.render(row_texts, []),
                rows=tuple(rows), lines=pairs,
                tags=tuple((ln["kind"], tuple(ln["seeds"]), ln["k"], ln["value"], ln["unit"]) for ln in kept),
                dropped_rows=dropped_rows, dropped_lines=dropped_lines)


def card(question: str, L: Layer) -> Card | None:
    """Arm G's card on the rule seeds, or None when the rule abstains."""
    seeds, _why = rule_seeds(question, L)
    return None if seeds is None else card_for_seeds(seeds, L, reason=OK)

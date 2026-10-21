"""gencard: the Genesis age card of the GEN confirmation set (prereg §5), standard library only.

``L = parse(gen_layer_json, gen_names_json)``; ``trigger(question, L)``, ``rule_seeds(question, L)`` and
``card(question, L)`` run prereg §5.2's rule (no LLM, no fallback); ``card_for_seeds(seeds, L)`` is the
card of given seeds (G-ref). ``CUE_LITERALS`` are every cue word of §5.2 rules 7 and 10 (the writers'
banned list imports them). The package is written to move into the backend byte for byte: relative
imports only, nothing outside the standard library, no file or network access.
"""
from .card import Card, card, card_for_seeds
from .names import Layer, parse
from .seeds import rule_seeds
from .trigger import CUE_LITERALS, Trigger, trigger

__all__ = ["CUE_LITERALS", "Card", "Layer", "Trigger", "card", "card_for_seeds", "parse", "rule_seeds", "trigger"]

"""Cards of the rule-seed regression (prereg.md §2–§3): CPU only, the backend's own card path.

Per question, after the backend's trigger (``trigger.trigger`` with the layer's blockers; a question it
does not take gets no card in either arm, as the backend makes none):

- rule arm: ``seeds.rule_seeds`` -> ``card.card_from_rule`` (the backend's rule path). Where the rules
  abstain, the backend falls back to the gemma seed call; here that fallback is the recorded gemma seeds
  replayed on the layer, i.e. the reference arm's card of the same rep (``seed_label``).
- gemma reference arm: each recorded seed set replayed on the layer, never a new seed call. A raw seed
  call output (G-auto's gen_seed.jsonl ``content``) goes through ``card.card_from_seeds`` (parse_seeds +
  engine.resolve); a staging A4 record's ``aux_card.seeds`` (「國別｜王名」 strings, the parse the
  backend made of its seed call) through ``card.card_from_parsed``. A truncated seed call is no seeds
  (experiment A's rule); an A4 record without aux_card is no seeds (that run's backend made no card).

The engine runs with its default S4 guard (on). A slot is one (set, item, arm, rep); its card text
stays in the store (cards.json), the jobs carry its sha256.
"""
from __future__ import annotations

from typing import NamedTuple

import rs_common as C
from rs_common import ARMS, REPS

KD_OF = {name: kd for kd, name in {"I": "以色列", "J": "猶大"}.items()}


class SetSpec(NamedTuple):
    items: list[dict]                 # questions in run order: id, question, sources (+ unit for confirm)
    seed_sets: dict[str, dict]        # label -> {item: recorded seeds}; rep r takes label r (cyclic)
    only_fired: bool                  # dev: only the questions the trigger takes


# ---------------------------------------------------------------- recorded seeds
def raw_seeds(path) -> dict:
    """gen_seed.jsonl answer lines -> {item: {"kind": "raw", "text", "truncated"}}."""
    out = {}
    for r in C.jsonl(path):
        if r.get("type") != "answer":
            continue
        trunc = r.get("done_reason") == "length"
        out[r["item"]] = {"kind": "raw", "text": "" if trunc else (r.get("content") or ""), "truncated": trunc}
    return out


def parse_aux(seeds: list[str]) -> list[list[str]]:
    """aux_card.seeds 「國別｜王名」 -> [[kingdom, name]]; ValueError on another kingdom word."""
    out = []
    for s in seeds:
        kd_name, _, name = s.partition("｜")
        if kd_name not in KD_OF or not name:
            raise ValueError(f"not a 「國別｜王名」 seed: {s!r}")
        out.append([KD_OF[kd_name], name])
    return out


def aux_seeds(path) -> dict:
    """A4 responses.jsonl -> {item: {"kind": "parsed", "pairs", "no_aux_card"}}."""
    out = {}
    for r in C.jsonl(path):
        aux = r.get("aux_card")
        out[r["item"]] = {"kind": "parsed", "pairs": parse_aux(aux["seeds"]) if aux else [], "no_aux_card": aux is None}
    return out


def replay(layer, question: str, recorded: dict):
    """The backend's gemma path on recorded seeds (None = no card)."""
    B = C.backend()
    if recorded["kind"] == "raw":
        return B.card.card_from_seeds(layer, question, recorded["text"])
    return B.card.card_from_parsed(layer, question, [tuple(p) for p in recorded["pairs"]])


# ---------------------------------------------------------------- slots
def seed_label(labels: tuple[str, ...], rep: int) -> str:
    return labels[(rep - 1) % len(labels)]


def card_fields(layer, card) -> dict:
    """What a slot records of a card (None = no card): text and sha, the seeds, the S4 guard, the cap."""
    if card is None:
        return {"card": False, "text": None, "text_sha256": None, "chars": 0, "lines": 0, "seeds": [], "kings": [],
                "guard_blocked": [], "rows_dropped": 0}
    B = C.backend()
    on = B.engine.cards(layer.view, list(card.kings))
    off = B.engine.cards(layer.view, list(card.kings), guard=False)
    if on["g_block"] != card.text:
        raise SystemExit(f"card path is not the guarded engine for kings {card.kings}")
    blocked = [t[1] for t in off["tags"] if t[0] == "born" and t not in on["tags"]]
    names = B.regnal.KINGDOM_NAMES
    return {"card": True, "text": card.text, "text_sha256": C.sha256_text(card.text), "chars": len(card.text),
            "lines": card.lines, "seeds": [f"{names[kd]}｜{nm}" for kd, nm in card.seeds], "kings": list(card.kings),
            "guard_blocked": blocked, "rows_dropped": len(on["rows_dropped"])}


def _pins(info: dict) -> dict:
    return {"layer_sha256": info["layer_sha256"], "lexicon_sha256": info["lexicon_sha256"],
            "backend_sha256": C.backend().sha256}


def item_slots(layer, info: dict, set_name: str, it: dict, spec: SetSpec, fired: bool) -> tuple[list[dict], dict]:
    """The item's 2 × REPS slots and its rule-seed record {"ids", "reason"}."""
    B, q = C.backend(), it["question"]
    labels = tuple(spec.seed_sets)
    rule = B.seeds.rule_seeds(layer, q) if fired else B.seeds.RuleSeeds((), "not taken")
    ref = {lb: (replay(layer, q, spec.seed_sets[lb][it["id"]]) if fired else None) for lb in labels}
    rule_card = B.card.card_from_rule(layer, rule.ids) if rule.ids else None
    base = {"set": set_name, "item": it["id"], "fired": fired, "rule_ids": list(rule.ids),
            "rule_reason": rule.reason, **_pins(info)}
    slots = []
    for rep in range(1, REPS + 1):
        lb = seed_label(labels, rep)
        recorded = spec.seed_sets[lb][it["id"]]
        for arm in ARMS:
            if arm == "rule" and rule.ids:
                src, card = "rule", rule_card
            else:
                src, card = f"gemma:{lb}", ref[lb]
            slots.append({**base, "arm": arm, "rep": rep, "seed_source": src,
                          "recorded": None if src == "rule" else recorded, **card_fields(layer, card)})
    return slots, {"ids": list(rule.ids), "reason": rule.reason}


def build_cards(layer, info: dict, sets: dict[str, SetSpec]) -> dict:
    """{"header", "items": {set: [ids]}, "not_fired", "rule": {set: {item: {ids, reason}}}, "slots"}."""
    B = C.backend()
    doc = {"header": {**info, "backend_sha256": B.sha256, "backend_files_sha256": B.files_sha256,
                      "experiment_files_sha256": C.experiment_files_sha256(), "guard": "engine default (on)",
                      "reps": REPS, "arms": list(ARMS), "seed_sets": {s: list(sp.seed_sets) for s, sp in sets.items()}},
           "items": {}, "not_fired": {}, "rule": {}, "slots": []}
    for set_name, spec in sets.items():
        doc["items"][set_name], doc["not_fired"][set_name], doc["rule"][set_name] = [], [], {}
        for it in spec.items:
            fired = B.trigger.trigger(it["question"], layer.names, layer.blockers).fired
            if not fired:
                doc["not_fired"][set_name].append(it["id"])
                if spec.only_fired:
                    continue
            slots, rule = item_slots(layer, info, set_name, it, spec, fired)
            doc["items"][set_name].append(it["id"])
            doc["rule"][set_name][it["id"]] = rule
            doc["slots"] += slots
    return doc


def slot_map(doc: dict) -> dict:
    return {(s["set"], s["item"], s["arm"], s["rep"]): s for s in doc["slots"]}


# ---------------------------------------------------------------- the store's sets
def store_items() -> dict[str, list[dict]]:
    return {"confirm": C.read_json(C.A_CONFIRM / "items.json")["items"],
            "dev": C.read_json(C.A_DEV / "items.json")["items"]}


def store_sets() -> dict[str, SetSpec]:
    items = store_items()
    load = {"a": raw_seeds, "b": aux_seeds, "c": aux_seeds, "dev": raw_seeds}
    seeds = {lb: load[lb](C.SEED_SOURCES[lb]) for lb in load}
    for name, labels in (("confirm", C.CONFIRM_LABELS), ("dev", C.DEV_LABELS)):
        for lb in labels:
            missing = [it["id"] for it in items[name] if it["id"] not in seeds[lb]]
            if missing:
                raise SystemExit(f"seed set {lb} ({C.SEED_SOURCES[lb]}) has no record for {missing}")
    return {"confirm": SetSpec(items["confirm"], {lb: seeds[lb] for lb in C.CONFIRM_LABELS}, only_fired=False),
            "dev": SetSpec(items["dev"], {lb: seeds[lb] for lb in C.DEV_LABELS}, only_fired=True)}

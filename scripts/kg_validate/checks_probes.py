"""W (label/relationship histogram warning) and the config/kg_probes.yaml facts."""

from __future__ import annotations

from collections import Counter

from .model import KG, has_tsk_evidence, is_curated_xref
from .registry import CheckResult, Context, check

# A probe of any kind may be in the file, so PROBES reads every edge family.
_PROBE_FILES = ("mentions.jsonl", "relations.jsonl", "cross_references.jsonl", "chunks.jsonl", "books.jsonl")


@check("W", needs=("relations.jsonl", "mentions.jsonl", "cross_references.jsonl"))
def check_w(kg: KG, ctx: Context) -> CheckResult:
    labels = Counter(kg.label(eid) or "(untyped)" for eid in kg.entities)
    labels["Entity"] = sum(1 for r in kg.entities.values() if r["is_entity"])
    rels = Counter(r["type"] for r in kg.relations)
    rels["MENTIONS"] = len(kg.mentions)
    rels["CROSS_REFERENCES"] = len(kg.xrefs)
    return CheckResult({"histogram": {"labels": dict(sorted(labels.items())),
                                      "relationships": dict(sorted(rels.items()))}})


def _probe_present(fact: dict, kg: KG) -> bool | int:
    kind = fact["kind"]
    if kind == "relation":
        return (fact["head"], fact["rel"], fact["tail"]) in kg.relation_keys
    if kind == "mention":
        label = "Chunk" if fact["source"] in kg.chunk_parent else "Pericope"
        keys = {(label, fact["source"])}
        if fact.get("rollup"):
            keys |= {("Chunk", c) for c in kg.chunks_of.get(fact["source"], [])}
        return any((lab, sid, fact["entity"]) in kg.mention_keys for lab, sid in keys)
    if kind == "event_anchor":   # export_event_registry's anchor rule: chunk -> parent pericope
        return fact["pericope"] in kg.anchors.get(fact["event"], ())
    if kind == "alias":
        aliases = (kg.entities.get(fact["entity"]) or {}).get("aliases")
        return isinstance(aliases, list) and fact["alias"] in aliases
    if kind == "xref":
        wanted = fact.get("provenance", "any")
        return any(x.src == fact["source"] and x.tgt == fact["target"] and
                   (wanted == "any" or (wanted == "curated" and is_curated_xref(x)) or
                    (wanted == "tsk" and has_tsk_evidence(x)))
                   for x in kg.xrefs)
    return sum(1 for m in kg.book_region_edges if m["entity_id"] == fact["entity"])  # book_region


def evaluate_probes(kg: KG, ctx: Context) -> list[dict]:
    out = []
    for fact in ctx.probes.get("facts", []):
        found = _probe_present(fact, kg)
        if fact["kind"] == "book_region":
            passed = found <= fact.get("max", 0)
        else:
            passed = found == (fact["expect"] == "present")
        out.append({"id": fact["id"], "check": fact.get("check"), "passed": passed})
    return out


@check("PROBES", needs=_PROBE_FILES)
def check_probes(kg: KG, ctx: Context) -> CheckResult:
    # `failing` is the gate: the baseline holds the failing ids, so a must-hold
    # probe that breaks while a known failure heals is still a regression
    # (the count alone stays flat). `failures` is the readable total.
    results = evaluate_probes(kg, ctx)
    failing = sorted(p["id"] for p in results if not p["passed"])
    return CheckResult({"failures": len(failing), "failing": failing}, {"probes": len(results)}, failing)

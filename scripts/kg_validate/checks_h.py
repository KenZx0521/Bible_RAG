"""H checks (plan §3.6): H1–H11, H11 being batch 1A's relation provenance.
Which are hard, and from which batch, is the baseline's call (severity,
hard_from in config/kg_quality_baseline/h.json; listed in validate_kg.py).

D1 (export_event_registry --check) is registered by scripts/validate_kg.py,
which owns the subprocess it runs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Callable

from check_identity import DIFF_KINDS, TYPE_LABELS, run as run_identity, type_of
from relation_extraction.models import derive_source

from .model import KG, PPG
from .registry import CheckResult, Context, check

ID_PREFIX_LABEL = {label.lower(): label for label in TYPE_LABELS}
# Sources whose rows carry no pericope of their own: a prior's source_pericope_id
# is empty or a verse ref, a curated overlay has none.
UNANCHORED_SOURCES = ("prior", "curated")


def effective_source(r: dict) -> str | None:
    """The relation row's source; a row written before the property existed
    (every prod edge until W1) gets the one its phase implies."""
    return r["source"] or derive_source(r["extraction_phase"], r["notes"], r["backfilled"])


# ---------------------------------------------------------------------------
# Hard checks (batch 0)
# ---------------------------------------------------------------------------

@check("H1")
def check_h1(kg: KG, ctx: Context) -> CheckResult:
    counts = Counter(r["entity_id"] for r in kg.entity_rows)
    dups = sorted(eid for eid, n in counts.items() if n > 1)
    constraints = kg.manifest.get("constraints")
    present = constraints is not None and any(
        c["label"] == "Entity" and c["property"] == "entity_id" and c["type"] in ("UNIQUENESS", "NODE_KEY")
        for c in constraints)
    na = {} if constraints is not None else {"missing_constraint": "the snapshot manifest declares no constraints"}
    return CheckResult({"duplicate_ids": len(dups),
                        "missing_constraint": None if constraints is None else int(not present)},
                       {"constraints_declared": constraints is not None}, dups[:10], not_applicable=na)


@check("H2")
def check_h2(kg: KG, ctx: Context) -> CheckResult:
    bad = [r["entity_id"] for r in kg.entity_rows if r["is_entity"] and len(r["labels"]) != 1]
    unlabeled = [r["entity_id"] for r in kg.entity_rows if not r["is_entity"]]
    return CheckResult({"bad_type_labels": len(bad), "missing_entity_label": len(unlabeled)},
                       {}, (bad + unlabeled)[:10])


@check("H7")
def check_h7(kg: KG, ctx: Context) -> CheckResult:
    # No sha (no manifest value, no file) stays None: unmeasured, so a hard fail.
    queue = Path(ctx.embedding_queue)
    file_sha = hashlib.sha256(queue.read_bytes()).hexdigest() if queue.exists() else None
    sha = kg.manifest.get("embedding_queue_sha256") or file_sha
    allow = ctx.params("H7").get("id_prefix_allowlist", {})
    mismatched, allowed = [], []
    for r in kg.entity_rows:
        if len(r["labels"]) != 1:
            continue  # H2's failure, not a prefix question
        expected = ID_PREFIX_LABEL.get(r["entity_id"].split(":", 1)[0])
        if expected != r["labels"][0]:
            (allowed if allow.get(r["entity_id"]) == r["labels"][0] else mismatched).append(
                f"{r['entity_id']} :{r['labels'][0]}")
    return CheckResult({"embedding_queue_sha256": sha, "prefix_mismatch": len(mismatched)},
                       {"allowlisted": allowed, "texts_file_sha256": file_sha}, mismatched[:10])


# ---------------------------------------------------------------------------
# H3–H10: record checks until their batch (hard_from) hardens them
# ---------------------------------------------------------------------------

def _h3_exempt(r: dict) -> bool:
    source = effective_source(r)
    if source in UNANCHORED_SOURCES or r["curated"]:
        return True
    # inverse of a prior: priors carry no pericope, so neither does this
    return source == "inverse" and not r["source_pericope_id"] and r["notes"].startswith("derived_from=")


@check("H3", needs=("relations.jsonl", "mentions.jsonl", "chunks.jsonl"))
def check_h3(kg: KG, ctx: Context) -> CheckResult:
    support = {(kg.pericope_of(m), m["entity_id"]) for m in kg.mentions}
    by_type: Counter = Counter()
    no_provenance, samples = 0, []
    for r in kg.relations:
        if _h3_exempt(r):
            continue
        pid = r["source_pericope_id"]
        if not pid:
            no_provenance += 1
        elif (pid, r["head"]) in support and (pid, r["tail"]) in support:
            continue
        by_type[r["type"]] += 1
        if len(samples) < 10:
            samples.append(f"{r['head']} -{r['type']}-> {r['tail']} @{pid or '∅'}")
    return CheckResult({"unsupported": sum(by_type.values())},
                       {"by_type": dict(by_type.most_common()), "no_provenance": no_provenance}, samples)


@check("H4")
def check_h4(kg: KG, ctx: Context) -> CheckResult:
    names = [r["entity_id"] for r in kg.entities.values()
             if (r["canonical_name"] or "") != (r["canonical_name"] or "").strip()]
    ids = sum(1 for eid in kg.entities if any(ch.isspace() for ch in eid))
    return CheckResult({"whitespace_names": len(names)}, {"ids_with_whitespace": ids}, names[:10])


@check("H5", external=True)
def check_h5(kg: KG, ctx: Context) -> CheckResult:
    names = ["neo4j_aliases_not_list"] + [f"{s}_{k}" for s in ("pg", "qdrant") for k in DIFF_KINDS]
    if kg.mode != "live":
        return CheckResult(dict.fromkeys(names), {"skipped": "compares the live stores"},
                           not_applicable={"*": "snapshot mode: H5 compares the live stores"})
    if ctx.target is None:
        return CheckResult(dict.fromkeys(names), {"skipped": "no live target to compare"})
    reference = {eid: {"type": type_of(r["labels"]), "canonical_name": r["canonical_name"],
                       "aliases": r["aliases"], "description": r["description"]}
                 for eid, r in kg.entities.items()}
    report = run_identity(ctx.target, sample_size=3, reference=reference)
    metrics = {"neo4j_aliases_not_list": report["reference_aliases_not_list"]}
    # A skipped store (staging without QDRANT_ENTITY_COLLECTION) leaves its
    # metrics None and NOT declared n/a: the gate reports them unmeasured.
    for store, body in report["stores"].items():
        for kind in DIFF_KINDS:
            metrics[f"{store}_{kind}"] = body["counts"][kind] if "counts" in body else None
    return CheckResult(metrics, {s: b.get("skipped") or b["store"] for s, b in report["stores"].items()},
                       [{s: b["samples"]} for s, b in report["stores"].items() if "samples" in b])


@check("H6", needs=("mentions.jsonl",))
def check_h6(kg: KG, ctx: Context) -> CheckResult:
    edges = [m for m in kg.mentions if kg.label(m["entity_id"]) in PPG and not m["curated"]]
    missing = [m for m in edges if not m["source_region"] or m["start_pos"] is None]
    return CheckResult({"missing_region_or_pos": len(missing)},
                       {"ppg_mentions": len(edges), "no_start_pos": sum(m["start_pos"] is None for m in edges)},
                       [f"{m['source_id']}->{m['entity_id']}" for m in missing[:10]])


@check("H8", needs=("cross_references.jsonl",))
def check_h8(kg: KG, ctx: Context) -> CheckResult:
    # Today curated edges are recognised only by having no votes (backend coalesce(votes, 999)).
    bare = [x for x in kg.xrefs if x.curated is None and x.votes is None]
    return CheckResult({"no_provenance": len(bare)}, {"by_source": dict(Counter(x.source for x in bare))},
                       [f"{x.src}->{x.tgt}" for x in bare[:10]])


@check("H9", needs=("relations.jsonl",))
def check_h9(kg: KG, ctx: Context) -> CheckResult:
    violations: Counter = Counter()
    unknown: Counter = Counter()
    for r in kg.relations:
        entry = ctx.schema.get(r["type"])
        if entry is None:
            unknown[r["type"]] += 1
            continue
        head, tail = kg.label(r["head"]), kg.label(r["tail"])
        if not entry.accepts_pair(head, tail):
            violations[f"{r['type']} {head}->{tail}"] += 1
    return CheckResult({"domain_range_violations": sum(violations.values()),
                        "unknown_relation_types": sum(unknown.values())},
                       {"violations": dict(violations.most_common()), "unknown": dict(unknown)})


@check("H10", needs=("mentions.jsonl",))
def check_h10(kg: KG, ctx: Context) -> CheckResult:
    keys = sorted(f"{m['source_label']}|{m['source_id']}|{m['entity_id']}"
                  for m in kg.mentions if kg.label(m["entity_id"]) == "Event")
    fingerprint = hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
    return CheckResult({"event_mentions": len(keys), "fingerprint": fingerprint})


# ---------------------------------------------------------------------------
# Hard check (batch 1A): H11
# ---------------------------------------------------------------------------

def _h11_row_tests(kg: KG, id_order: frozenset[str]) -> dict[str, Callable[[dict], bool]]:
    """H11's per-edge metrics, in report order: name -> does this edge count.

    6.05 stamps a source on every row and retires the R5 inverses, the R2
    rule edges (anchored_rule replaces them), 10.3's co-occurrence edges and
    the LLM's Event–Event edges; an LLM row of an id-order relation (only its
    head/tail order gives a direction) must carry direction_verified false.
    """
    return {
        "source_null": lambda r: not r["source"],
        "inverse_edges": lambda r: effective_source(r) == "inverse",
        "cooccurrence_edges": lambda r: effective_source(r) == "cooccurrence" or r["backfilled"] is True,
        "rule_edges": lambda r: effective_source(r) == "rule",
        "llm_event_event_edges": lambda r: (effective_source(r) == "llm"
                                            and kg.label(r["head"]) == kg.label(r["tail"]) == "Event"),
        "unflagged_id_order_edges": lambda r: (r["type"] in id_order
                                               and effective_source(r) not in UNANCHORED_SOURCES
                                               and r["direction_verified"] is not False),
    }


def _undirected_duplicates(relations: list[dict], schema) -> dict[tuple[str, frozenset], int]:
    """(relation, {head, tail}) -> rows beyond the first, for each pair of an
    undirected relation stated more than once (either way round)."""
    undirected = {e.name for e in schema.iter_entries() if e.direction == "undirected"}
    pairs = Counter((r["type"], frozenset((r["head"], r["tail"]))) for r in relations if r["type"] in undirected)
    return {key: n - 1 for key, n in pairs.items() if n > 1}


@check("H11", needs=("relations.jsonl",))
def check_h11(kg: KG, ctx: Context) -> CheckResult:
    tests = _h11_row_tests(kg, ctx.schema.id_order_relations())
    hits = {name: [r for r in kg.relations if counts(r)] for name, counts in tests.items()}
    dups = _undirected_duplicates(kg.relations, ctx.schema)
    metrics = {name: len(rows) for name, rows in hits.items()}
    metrics["undirected_pair_duplicates"] = sum(dups.values())
    by_type = {name: dict(Counter(r["type"] for r in rows).most_common()) for name, rows in hits.items() if rows}
    dup_types: Counter = Counter()
    for (relation, _), extra in dups.items():
        dup_types[relation] += extra
    if dup_types:
        by_type["undirected_pair_duplicates"] = dict(dup_types.most_common())
    samples = [f"{name}: {r['head']} -{r['type']}-> {r['tail']}" for name, rows in hits.items() for r in rows[:2]]
    samples += [f"undirected_pair_duplicates: {' ~ '.join(sorted(pair))} {relation}"
                for relation, pair in list(dups)[:2]]
    return CheckResult(metrics, {"by_type": by_type}, samples)

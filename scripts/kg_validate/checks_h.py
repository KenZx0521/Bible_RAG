"""H checks (plan §3.6): batch-0 hard gates H1, H2, H7 and the H3–H10 records.

D1 (export_event_registry --check) is registered by scripts/validate_kg.py,
which owns the subprocess it runs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from check_identity import DIFF_KINDS, TYPE_LABELS, run as run_identity, type_of

from .model import KG, PPG, XRef
from .registry import CheckResult, Context, check

ID_PREFIX_LABEL = {label.lower(): label for label in TYPE_LABELS}
PRIOR_PHASE = 3      # ExtractionPhase.DOMAIN_PRIOR: source_pericope_id is empty or a verse ref
INVERSE_PHASE = 5    # ExtractionPhase.INVERSE_DERIVED (also reused by 10.3 co-occurrence)


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
# Record checks: H3–H10
# ---------------------------------------------------------------------------

@check("H3", needs=("relations.jsonl", "mentions.jsonl", "chunks.jsonl"))
def check_h3(kg: KG, ctx: Context) -> CheckResult:
    support = {(kg.pericope_of(m), m["entity_id"]) for m in kg.mentions}
    by_type: Counter = Counter()
    no_provenance, samples = 0, []
    for r in kg.relations:
        if r["extraction_phase"] == PRIOR_PHASE or r["curated"]:
            continue
        pid = r["source_pericope_id"]
        if not pid:
            if r["extraction_phase"] == INVERSE_PHASE and r["notes"].startswith("derived_from="):
                continue  # inverse of a prior: priors carry no pericope, so neither does this
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


def _flag_mismatch(x: XRef) -> bool:
    # A set flag must agree with the evidence it summarises: curated with
    # curated_sources (1B Step 5), tsk with votes (Step 9).
    return ((x.curated is not None and bool(x.curated) != bool(x.curated_sources))
            or (x.tsk is not None and bool(x.tsk) != (x.votes is not None)))


H8_RULES = {
    # Before 1B curated edges are recognised only by having no votes (backend coalesce(votes, 999)).
    "no_provenance": lambda x: x.curated is None and x.votes is None,
    # From 1B every edge carries both flags; prod before W1 carries neither.
    "unflagged": lambda x: x.curated is None or x.tsk is None,
    "flag_mismatch": _flag_mismatch,
}


@check("H8", needs=("cross_references.jsonl",))
def check_h8(kg: KG, ctx: Context) -> CheckResult:
    hits = {name: [x for x in kg.xrefs if rule(x)] for name, rule in H8_RULES.items()}
    return CheckResult({name: len(xs) for name, xs in hits.items()},
                       {"by_source": {name: dict(Counter(x.source for x in xs)) for name, xs in hits.items()}},
                       [{name: [f"{x.src}->{x.tgt}" for x in xs[:10]]} for name, xs in hits.items() if xs])


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

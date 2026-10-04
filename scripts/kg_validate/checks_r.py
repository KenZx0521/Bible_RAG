"""R checks (plan §3.6): ratcheted records R1–R11."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .checks_probes import evaluate_probes
from .model import KG, PPG
from .registry import CheckResult, Context, check

# FATHER_OF/MOTHER_OF point parent -> child; SON_OF/DAUGHTER_OF point child -> parent.
PARENT_HEAD = {"FATHER_OF", "MOTHER_OF"}
PARENT_TAIL = {"SON_OF", "DAUGHTER_OF"}
# R8 (the baseline's R8 query documents these same rules): synoptic
# cross-reference remnants start with （ ( ＊ * or hold a verse ref
# (「（太26‧26－30；可…」, 「*王下18‧13…」); sentence tails the title miner turned
# into E/O/T names END in 。，！？；」 (的君」。, 風，). A comma inside a real
# title (復活在我，生命在我) does not count, and neither do dash-led subtitles
# such as －蛙災 (15 Events; whether they are junk is undecided, which is why
# the plan's 27 excludes them).
_XREF_REMNANT = re.compile(r"^[（(＊*]|\d+‧\d+")
_FRAGMENT_END = re.compile(r"[。，！？；」]$")


@check("R1", needs=("mentions.jsonl", "books.jsonl"))
def check_r1(kg: KG, ctx: Context) -> CheckResult:
    edges = kg.book_region_edges
    by_entity = Counter(m["entity_id"] for m in edges)
    return CheckResult({"book_region_mentions": len(edges)},
                       {"by_source_label": dict(Counter(m["source_label"] for m in edges)),
                        "at_position_0": sum(m["start_pos"] == 0 for m in edges),
                        "top_entities": dict(by_entity.most_common(10))})


@check("R2", needs=("mentions.jsonl",))
def check_r2(kg: KG, ctx: Context) -> CheckResult:
    probes = ctx.probes.get("substring_probes") or {}
    contaminated: Counter = Counter()
    unresolved, samples = 0, []
    for m in kg.mentions:
        span = m["text_span"]
        if span not in probes or kg.label(m["entity_id"]) not in PPG:
            continue
        body = ctx.body(m["source_label"], m["source_id"])
        if body is None:
            unresolved += 1
            continue
        left, right = set(probes[span].get("left") or ""), set(probes[span].get("right") or "")
        hits, i = [], body.find(span)
        while i >= 0:
            hits.append(i)
            i = body.find(span, i + 1)
        # No body occurrence = header/book-only evidence, which R1 measures.
        if hits and all((i > 0 and body[i - 1] in left) or
                        (i + len(span) < len(body) and body[i + len(span)] in right) for i in hits):
            contaminated[span] += 1
            if len(samples) < 10:
                samples.append(f"{m['source_id']}->{m['entity_id']}")
    return CheckResult({"contaminated": sum(contaminated.values())},
                       {"by_span": dict(contaminated.most_common()), "unresolved_anchor_text": unresolved},
                       samples)


_R3_ALL_FORMS = ("all_forms_entities", "all_forms_person")


def _foreign_surfaces(kg: KG, rows: list[dict]) -> dict[str, set[str]]:
    """entity_id -> stripped spans that are neither its canonical name nor an alias."""
    foreign: dict[str, set[str]] = defaultdict(set)
    for m in rows:
        span = (m["text_span"] or "").strip()
        ent = kg.entities.get(m["entity_id"])
        if not span or ent is None:
            continue
        aliases = ent["aliases"] if isinstance(ent["aliases"], list) else []
        if span not in {(ent["canonical_name"] or "").strip(), *(a.strip() for a in aliases)}:
            foreign[m["entity_id"]].add(span)
    return foreign


@check("R3", needs=("mentions.jsonl",))
def check_r3(kg: KG, ctx: Context) -> CheckResult:
    # Two readings, two metric pairs, two baselines. Sharing one baseline made
    # every full snapshot "regress" against the live value (268 vs 264).
    #   foreign_surface_entities, person: the span each MENTIONS edge keeps (its
    #     first row, as live Neo4j stores it); the same number live and offline.
    #     It can move with row order (1C sorts rows by start_pos).
    #   all_forms_entities, all_forms_person: every occurrence row, the plan's
    #     definition (169 Person / 268 all); n/a without occurrence rows (live, a
    #     --dump-snapshot of live), so only a full snapshot fills its baseline.
    edge = _foreign_surfaces(kg, kg.mentions)
    by_type = Counter(kg.label(eid) for eid in edge)
    metrics = {"foreign_surface_entities": len(edge), "person": by_type.get("Person", 0)}
    detail: dict = {"by_type": dict(by_type)}
    shown, na = edge, {}
    if kg.mention_rows is None:
        metrics.update(dict.fromkeys(_R3_ALL_FORMS))
        na = dict.fromkeys(_R3_ALL_FORMS, "no occurrence rows: live Neo4j and its dump keep one span per edge")
    else:
        shown = _foreign_surfaces(kg, kg.mention_rows)
        all_types = Counter(kg.label(eid) for eid in shown)
        metrics.update(zip(_R3_ALL_FORMS, (len(shown), all_types.get("Person", 0))))
        detail["all_forms_by_type"] = dict(all_types)
    return CheckResult(metrics, detail, [f"{eid} {sorted(s)}" for eid, s in sorted(shown.items())[:10]],
                       not_applicable=na)


def _verses(spec: str | None) -> list[int] | None:
    """'5' / '8-9' / '10-12, 14' -> verse numbers; None when unparseable."""
    out: list[int] = []
    for part in (spec or "").replace("，", ",").split(","):
        bounds = [b for b in part.strip().split("-") if b]
        if not bounds or not all(b.isdigit() for b in bounds):
            return None
        out.extend(range(int(bounds[0]), int(bounds[-1]) + 1))
    return out or None


@check("R4", needs=("cross_references.jsonl", "pericopes.jsonl"))
def check_r4(kg: KG, ctx: Context) -> CheckResult:
    misaligned, unparsed, samples = 0, 0, []
    supplementary = [x for x in kg.xrefs if x.source == "supplementary"]
    for x in supplementary:
        ends = []
        for pid, spec in ((x.src, x.source_verses), (x.tgt, x.target_verses)):
            wanted = _verses(spec)
            have = _verses((kg.pericopes.get(pid) or {}).get("verse_range"))
            ends.append(None if wanted is None or have is None else wanted[0] in have)
        if None in ends:
            unparsed += 1
        elif not all(ends):
            misaligned += 1
            if len(samples) < 10:
                samples.append(f"{x.src}[{x.source_verses}] -> {x.tgt}[{x.target_verses}]")
    return CheckResult({"misaligned": misaligned},
                       {"supplementary": len(supplementary), "unparsed": unparsed}, samples)


@check("R5")
def check_r5(kg: KG, ctx: Context) -> CheckResult:
    types: dict[str, set[str]] = defaultdict(set)
    for r in kg.entities.values():
        if r["canonical_name"] and len(r["labels"]) == 1:
            types[r["canonical_name"].strip()].add(r["labels"][0])
    shared = sorted(name for name, labels in types.items() if len(labels) > 1)
    return CheckResult({"cross_type_names": len(shared)}, {}, shared[:10])


@check("R6", needs=("relations.jsonl",))
def check_r6(kg: KG, ctx: Context) -> CheckResult:
    parent_of = set()
    for r in kg.relations:
        if r["type"] in PARENT_HEAD:
            parent_of.add((r["head"], r["tail"]))
        elif r["type"] in PARENT_TAIL:
            parent_of.add((r["tail"], r["head"]))
    fathers = [(r["head"], r["tail"]) for r in kg.relations if r["type"] == "FATHER_OF"]
    contradictions = [f"{h}->{t}" for h, t in fathers if (t, h) in parent_of]
    female = set(ctx.probes.get("female_persons") or [])
    female_head = [f"{h}->{t}" for h, t in fathers if h in female]
    children: dict[str, set[str]] = defaultdict(set)
    for h, t in fathers:
        children[t].add(h)
    multi = sum(1 for heads in children.values() if len(heads) > 1)
    failing = sorted(p["id"] for p in evaluate_probes(kg, ctx) if p["check"] == "R6" and not p["passed"])
    return CheckResult(
        {"probe_failures": len(failing), "failing_probes": failing, "contradictions": len(contradictions),
         "female_head": len(female_head),
         "functional_violation_rate": round(multi / len(children), 4) if children else 0.0},
        {"failing_probes": failing, "children": len(children), "children_with_2plus_fathers": multi},
        (contradictions + female_head)[:10])


@check("R7", needs=("mentions.jsonl", "chunks.jsonl"))
def check_r7(kg: KG, ctx: Context) -> CheckResult:
    events = [eid for eid in kg.entities if kg.label(eid) == "Event"]
    single = sum(1 for eid in events if len(kg.anchors.get(eid, ())) == 1)
    return CheckResult({"single_pericope_events": single},
                       {"events": len(events), "unanchored": sum(1 for e in events if not kg.anchors.get(e))})


def _is_junk_name(name: str | None) -> bool:
    # Padded E/O/T names (「 驢」, 「 押沙龍」) come from pos_extractor matching
    # before strip; they are junk twins, not just an H4 cosmetic issue.
    text = name or ""
    core = text.strip()
    return not core or text != core or bool(_XREF_REMNANT.search(core) or _FRAGMENT_END.search(core))


@check("R8")
def check_r8(kg: KG, ctx: Context) -> CheckResult:
    allow = set(ctx.params("R8").get("allow_names", []))
    junk: dict[str, list[str]] = {"Event": [], "Theme": [], "Object": []}
    for eid, r in kg.entities.items():
        label = kg.label(eid)
        if label in junk and (r["canonical_name"] or "").strip() not in allow and _is_junk_name(r["canonical_name"]):
            junk[label].append(r["canonical_name"])
    return CheckResult({f"junk_{k.lower()}": len(v) for k, v in junk.items()}, {},
                       [n for names in junk.values() for n in names[:4]])


@check("R9", needs=("mentions.jsonl",))
def check_r9(kg: KG, ctx: Context) -> CheckResult:
    names = ("duplicate_positions", "span_mismatch")
    rows = [r for r in (kg.mention_rows or []) if r["text_id"] and r["start_pos"] is not None]
    if not rows:
        # Nothing to score is n/a in both modes, so live and its snapshot agree;
        # the reason is printed, so a compile that dropped text_id stays visible.
        reason = ("live Neo4j keeps one position per edge and no text_id" if kg.mode == "live" else
                  "a dump of live: one row per edge, no text_id" if kg.mention_rows is None else
                  "no occurrence row carries text_id and start_pos")
        return CheckResult(dict.fromkeys(names), {"skipped": reason}, not_applicable={"*": reason})
    seen = Counter((r["text_id"], r["entity_id"], r["start_pos"]) for r in rows)
    body_base = kg.manifest.get("position_base") == "body"
    mismatch, unresolved, samples = 0, 0, []
    for r in rows:
        text = ctx.texts.get(r["text_id"])
        if text is None:
            unresolved += 1
            continue
        if body_base:
            text = text[text.find("：") + 1:]
        if text[r["start_pos"]:r["end_pos"]] != r["text_span"]:
            mismatch += 1
            if len(samples) < 10:
                samples.append(f"{r['text_id']}@{r['start_pos']} {r['text_span']!r}")
    return CheckResult({"duplicate_positions": sum(n - 1 for n in seen.values()), "span_mismatch": mismatch},
                       {"positioned_rows": len(rows), "unresolved_text_id": unresolved}, samples)


@check("R10")
def check_r10(kg: KG, ctx: Context) -> CheckResult:
    owners: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, set[str]] = defaultdict(set)
    for eid, r in kg.entities.items():
        canonical[(r["canonical_name"] or "").strip()].add(eid)
        for alias in r["aliases"] if isinstance(r["aliases"], list) else []:
            owners[alias.strip()].add(eid)
    conflicts = sorted(a for a, who in owners.items() if len(who) > 1 or canonical.get(a, set()) - who)
    return CheckResult({"conflicting_aliases": len(conflicts)}, {},
                       [f"{a}: {sorted(owners[a] | canonical.get(a, set()))}" for a in conflicts[:10]])


@check("R11", needs=("cross_references.jsonl",))
def check_r11(kg: KG, ctx: Context) -> CheckResult:
    return CheckResult({"tsk_votes_edges": sum(1 for x in kg.xrefs if x.votes is not None)})

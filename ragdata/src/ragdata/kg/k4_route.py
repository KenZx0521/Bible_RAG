"""K4, R2: the routing lexicon is the PDF-based union of design §5.2.

One term per surface, unique across the lexicon:
- names: every kg0 name (its norm_key) and, by rt.dotless, the spelling of a ‧ name
  without the ‧ (one term with every name it spells, unless the string is already a term);
- divine: every divine_refs span pattern the PDF prints; its coordinate is its first
  divine_rule span in kg0, its target the pattern of the person it names (the titles of
  Jesus share 耶穌's);
- aliases: ``query_aliases.yaml``, each standing for a kg0 name or a divine surface;
- events: every trigger of the events layer (pdf_terms, then external_aliases), each
  standing for its event;
- books: the rt.book_forms the router masks and matches.

Every term lists every target it stands for and its provenance. K4 resolves the route
types the router counts (rt.untyped_place, rt.divine_person) and marks the terms the
matcher must not see (rt.min_len, rt.common_word); the exclusion contexts go with them
(rt.exclude_context). Categories list their terms by surface (books in router order). A
registry that clashes with the layers (an alias that is already a term or points at
nothing, an unclassified divine surface, kg0 built with other registries) is a StageError.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ragcommon import books, routing
from ragdata.contract.kg import ROUTE_CATEGORIES, ROUTE_KINDS
from ragdata.gates.base import Snapshot
from ragdata.kg import k4_rules
from ragdata.kg.k4_aliases import (
    Exclusion, QueryAlias, QueryAliases, lexicon_exclusions, load_query_aliases,
)
from ragdata.kg.registries import (
    DIVINE, NORMALIZATION, DivineRefs, Normalization, RegistryError, load_divine,
    load_normalization,
)
from ragdata.stages.errors import StageError

REPORT_SCHEMA = "ragdata.route_report.v2"
KG0_SOURCE = "kg0 names.jsonl"
DIVINE_SOURCE = "config/registries/divine_refs.yaml"
EVENTS_SOURCE = "config/registries/events.yaml"
BOOKS_SOURCE = "packages/ragcommon/data/books.json"
TERM_FIELDS = ("surface", "kind", "targets", "routable", "unroutable_rule", "provenance_class",
               "source", "evidence_span_id", "rule_id", "norm_rule_ids", "at", "decided_by",
               "note", "alias_id", "book_id", "full_name")
NAMED = ("name", "divine")   # what an alias may stand for
Term = dict[str, Any]


@dataclass(frozen=True)
class RouteInputs:
    """What K4 compiles: the text, kg0 and events records and the registries."""

    snapshot: Snapshot
    versions: Mapping[str, str]          # text, kg0 and events layer versions
    normalization: Normalization
    divine: DivineRefs
    aliases: QueryAliases
    exclusions: tuple[Exclusion, ...]    # name_normalization's, then the question ones
    books_version: str


@dataclass(frozen=True)
class Compiled:
    lexicon: dict[str, Any]              # routing_lexicon.json
    records: list[Term]                  # routing_terms.jsonl
    query_aliases: dict[str, Any]        # query_aliases.json
    report: dict[str, Any]               # route_report.json


def books_version() -> str:
    return f"books@{hashlib.sha256(books.DATA_PATH.read_bytes()).hexdigest()[:12]}"


def _check_bound(snapshot: Snapshot, normalization: str, divine: str) -> None:
    """kg0 was built with these registries (its rule spans carry their versions)."""
    want = {"divine_rule": divine, "lexicon": normalization}
    found = sorted({s.registry_version for s in snapshot.of("extra_spans")
                    if s.source in want and s.registry_version != want[s.source]})
    if found:
        raise RegistryError(f"kg0 was built with {found}; the registries are {divine} and "
                            f"{normalization}")


def route_inputs(snapshot: Snapshot, versions: Mapping[str, str], registries: Path | str
                 ) -> RouteInputs:
    """Read the registries and check they are the ones kg0 was built with."""
    directory = Path(registries)
    normalization, divine = load_normalization(directory), load_divine(directory)
    _check_bound(snapshot, normalization.version, divine.version)
    aliases = load_query_aliases(directory)
    return RouteInputs(snapshot, dict(versions), normalization, divine, aliases,
                       lexicon_exclusions(directory) + aliases.exclusions, books_version())


# ------------------------------------------------------------------ terms


def _target(ref: str, label: str, candidates: Sequence[Mapping[str, str]],
            route_types: Sequence[str]) -> dict[str, Any]:
    return {"ref": ref, "label": label, "type_candidates": [dict(c) for c in candidates],
            "route_types": list(route_types)}


def _term(surface: str, kind: str, targets: Iterable[Mapping[str, Any]], provenance_class: str,
          source: str, **fields: Any) -> Term:
    unknown = set(fields) - set(TERM_FIELDS)
    if unknown:
        raise ValueError(f"unknown term fields {sorted(unknown)}")
    return {**dict.fromkeys(TERM_FIELDS), "norm_rule_ids": [], **fields, "surface": surface,
            "kind": kind, "routable": True, "provenance_class": provenance_class,
            "source": source,
            "targets": sorted((dict(t) for t in targets), key=lambda t: t["ref"])}


def _name_target(name: Any) -> dict[str, Any]:
    candidates = [{"type": c.type, "rule": c.rule} for c in name.type_candidates]
    return _target(name.name_id, name.norm_key, candidates,
                   k4_rules.name_route_types(c["type"] for c in candidates))


def _names(names: Sequence[Any]) -> list[Term]:
    return [_term(n.norm_key, "name", [_name_target(n)], n.provenance_class, KG0_SOURCE,
                  evidence_span_id=n.evidence_span_id, norm_rule_ids=list(n.norm_rule_ids))
            for n in names]


def _divine_target(surface: str, rule_of: Mapping[str, str]) -> dict[str, Any]:
    """rt.divine_person: the target is the pattern of the person the surface names, so the
    titles of one person (救主, 耶穌) count once."""
    person, types = k4_rules.divine_person(surface), k4_rules.divine_route_types(surface)
    if person not in rule_of:
        raise StageError(f"rt.divine_person: {surface} names {person}, which is no "
                         "divine_refs pattern")
    candidates = [{"type": t, "rule": "rt.divine_person"} for t in types]
    return _target(rule_of[person], person, candidates, types)


def _divine(divine: DivineRefs, extra_spans: Iterable[Any]) -> tuple[list[Term], list[str]]:
    """The patterns the PDF prints, and the others (no coordinate, so no term). Each term
    keeps its own pattern as rule_id and its own first span as coordinate."""
    first: dict[str, str] = {}
    for span in extra_spans:
        if span.source == "divine_rule":
            first.setdefault(span.surface, span.span_id)
    rule_of = {surface: rule_id for rule_id, surface in divine.patterns}
    terms = [_term(surface, "divine", [_divine_target(surface, rule_of)], "pdf_rule",
                   DIVINE_SOURCE, evidence_span_id=first[surface], rule_id=rule_id)
             for rule_id, surface in divine.patterns if surface in first]
    return terms, [s for _, s in divine.patterns if s not in first]


def _events(events: Iterable[Any]) -> list[Term]:
    terms = []
    for event in events:
        target = [_target(event.event_id, event.name, [], [])]
        terms += [_term(t.text, "event", target, t.provenance_class, EVENTS_SOURCE, at=t.at,
                        decided_by=t.decided_by) for t in event.pdf_terms]
        terms += [_term(a.text, "event", target, a.provenance_class, a.source, note=a.note)
                  for a in event.external_aliases]
    return terms


def _books() -> list[Term]:
    return [_term(f.surface, "book", [], "curated_metadata", BOOKS_SOURCE, book_id=f.book_id,
                  full_name=books.get_book(f.book_id).name) for f in k4_rules.book_forms()]


def _by_surface(terms: Iterable[Term]) -> dict[str, Term]:
    found: dict[str, Term] = {}
    for term in terms:
        if term["surface"] in found:
            raise StageError(f"routing term {term['surface']} appears twice "
                             f"({found[term['surface']]['kind']}, {term['kind']})")
        found[term["surface"]] = term
    return found


def _dotless(names: Sequence[Any], mark: str, taken: Mapping[str, Term]
             ) -> tuple[list[Term], list[dict[str, Any]]]:
    """rt.dotless: (the terms, the spellings that already are a term)."""
    groups: dict[str, list[Any]] = {}
    for name in names:
        if mark in name.norm_key:
            groups.setdefault(name.norm_key.replace(mark, ""), []).append(name)
    terms, skipped = [], []
    for surface, spelled in groups.items():
        if surface in taken:
            skipped.append({"surface": surface, "of": sorted(n.norm_key for n in spelled),
                            "already": taken[surface]["kind"]})
            continue
        first = min(spelled, key=lambda n: n.name_id)
        terms.append(_term(surface, "dotless", [_name_target(n) for n in spelled], "pdf_rule",
                           KG0_SOURCE, evidence_span_id=first.evidence_span_id,
                           rule_id="rt.dotless"))
    return terms, skipped


def _alias(alias: QueryAlias, taken: Mapping[str, Term]) -> Term:
    if alias.surface in taken:
        raise StageError(f"query alias {alias.alias_id}: {alias.surface} is already a term "
                         f"({taken[alias.surface]['kind']})")
    target = taken.get(alias.target)
    if target is None or target["kind"] not in NAMED:
        raise StageError(f"query alias {alias.alias_id}: target {alias.target} is not a kg0 "
                         "name or a divine surface the PDF prints")
    return _term(alias.surface, "alias", target["targets"], "external_query", alias.source,
                 note=alias.note, alias_id=alias.alias_id)


def _routability(term: Term, common: Mapping[str, Any]) -> Term:
    rule = k4_rules.unroutable_rule(term["surface"], term["kind"], common)
    return term if rule is None else {**term, "routable": False, "unroutable_rule": rule}


# ------------------------------------------------------------------ documents


def _categories(terms: Iterable[Term]) -> dict[str, list[Term]]:
    found: dict[str, list[Term]] = {c: [] for c in ROUTE_CATEGORIES}
    for term in terms:
        found[ROUTE_KINDS[term["kind"]]].append(term)
    return {c: rows if c == "books" else sorted(rows, key=lambda t: t["surface"])
            for c, rows in found.items()}


def term_records(categories: Mapping[str, Sequence[Term]]) -> list[Term]:
    return [{"term_key": f"{c}/{i:04d}", **t} for c in ROUTE_CATEGORIES
            for i, t in enumerate(categories[c])]


def join_lexicon(rest: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
                 ) -> dict[str, Any]:
    """The lexicon document: ``rest`` (schema, header, exclusions) and the records' terms,
    each category in term_key order."""
    ordered = sorted(records, key=lambda r: r["term_key"])
    return {**rest, **{c: [{k: v for k, v in r.items() if k != "term_key"} for r in ordered
                           if r["term_key"].partition("/")[0] == c] for c in ROUTE_CATEGORIES}}


def _exclusions(rows: Iterable[Exclusion]) -> list[dict[str, str]]:
    return [{"surface": r.surface, "context": r.context, "why": r.why, "source": r.source}
            for r in sorted(rows, key=lambda r: (r.surface, r.context, r.source))]


def _header(inputs: RouteInputs) -> dict[str, Any]:
    v = inputs.versions
    registries = {DIVINE: inputs.divine.version, NORMALIZATION: inputs.normalization.version,
                  "query_aliases": inputs.aliases.version}
    return {"inputs": {"text": v["text"], "kg0": v["kg0"], "events": v["events"],
                       "registries": registries, "books": inputs.books_version},
            "rules": dict(k4_rules.RULES)}


def _aliases_doc(inputs: RouteInputs, terms: Sequence[Term]) -> dict[str, Any]:
    by_id = {a.alias_id: a for a in inputs.aliases.aliases}
    rows = [{"alias_id": t["alias_id"], "surface": t["surface"],
             "target": by_id[t["alias_id"]].target, "target_ref": t["targets"][0]["ref"],
             "provenance_class": t["provenance_class"], "source": t["source"], "note": t["note"]}
            for t in sorted(terms, key=lambda t: t["alias_id"])]
    return {"schema": routing.QUERY_ALIASES_SCHEMA, "kg0": inputs.versions["kg0"],
            "registry": inputs.aliases.version, "aliases": rows}


def _report(header: Mapping[str, Any], records: Sequence[Term], common: Mapping[str, Any],
            skipped: Sequence[Any], unprinted: Sequence[str]) -> dict[str, Any]:
    unroutable = {rule: sorted(r["surface"] for r in records if r["unroutable_rule"] == rule)
                  for rule in ("rt.min_len", "rt.common_word")}
    return {"schema": REPORT_SCHEMA, "inputs": header["inputs"],
            "terms": dict(sorted(Counter(r["kind"] for r in records).items())),
            "routable": sum(r["routable"] for r in records), "unroutable": unroutable,
            "common_words": {k: dict(common[k]) for k in sorted(common)},
            "dotless_skipped": list(skipped), "divine_unprinted": list(unprinted),
            "place_typed": sum(1 for r in records if r["kind"] == "name" and any(
                c["type"] == "Place" for t in r["targets"] for c in t["type_candidates"]))}


def compile_route(inputs: RouteInputs) -> Compiled:
    """The lexicon, its records, the query-alias contract and the report."""
    snap = inputs.snapshot
    names = list(snap.of("names"))
    divine, unprinted = _divine(inputs.divine, snap.of("extra_spans"))
    taken = _by_surface([*_names(names), *divine, *_events(snap.of("events")), *_books()])
    dotless, skipped = _dotless(names, inputs.normalization.interpunct, taken)
    taken = {**taken, **_by_surface(dotless)}
    aliases = [_alias(a, taken) for a in inputs.aliases.aliases]
    _by_surface([*taken.values(), *aliases])
    text = k4_rules.verses(list(snap.of("verse_units")), snap.of("name_spans"))
    common = k4_rules.common_words((n.norm_key for n in names), text)
    categories = _categories(_routability(t, common) for t in (*taken.values(), *aliases))
    header, records = _header(inputs), term_records(categories)
    lexicon = join_lexicon({"schema": routing.SCHEMA, "variant": routing.VARIANT,
                            "header": header, "exclusions": _exclusions(inputs.exclusions)},
                           records)
    return Compiled(lexicon, records, _aliases_doc(inputs, aliases),
                    _report(header, records, common, skipped, unprinted))

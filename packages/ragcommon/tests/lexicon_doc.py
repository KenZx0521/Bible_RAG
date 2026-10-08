"""Small routing-lexicon v2 documents for tests (ragcommon's and the backend's).

The shapes follow the R2 contract spec (§3.2): every term has the full key set and
the provenance of its kind; a field that does not apply is null or []. The values
are made up; only the shape is the contract's.
"""

from __future__ import annotations

from typing import Any, Iterable

from ragcommon import routing

PROVENANCE = {"name": "pdf_deterministic", "dotless": "pdf_rule", "divine": "pdf_rule",
              "alias": "external_query", "event": "curated_human", "book": "curated_metadata"}


def target(ref: str, label: str, *route_types: str) -> dict[str, Any]:
    candidates = [{"type": t, "rule": "test"} for t in route_types]
    return {"ref": ref, "label": label, "type_candidates": candidates,
            "route_types": sorted(route_types)}


def term(surface: str, kind: str, targets: Iterable[dict] = (), routable: bool = True,
         **fields: Any) -> dict[str, Any]:
    base = {key: None for key in routing.TERM_KEYS}
    rule = None if routable else ("rt.min_len" if len(surface) < 2 else "rt.common_word")
    return {**base, "surface": surface, "kind": kind, "targets": list(targets),
            "routable": routable, "unroutable_rule": rule, "provenance_class": PROVENANCE[kind],
            "source": "test", "norm_rule_ids": [], **fields}


def name(surface: str, ref: str, *route_types: str, label: str | None = None,
         kind: str = "name", routable: bool = True) -> dict[str, Any]:
    return term(surface, kind, [target(ref, label or surface, *route_types)], routable)


def event(surface: str, event_id: str, label: str) -> dict[str, Any]:
    return term(surface, "event", [target(event_id, label)])


def book(surface: str, book_id: str, full_name: str, routable: bool = True) -> dict[str, Any]:
    return term(surface, "book", routable=routable, book_id=book_id, full_name=full_name)


def exclusion(surface: str, context: str) -> dict[str, Any]:
    return {"surface": surface, "context": context, "why": "test", "source": "test"}


def document(names=(), divine=(), aliases=(), events=(), books=(),
             exclusions=()) -> dict[str, Any]:
    return {"schema": routing.SCHEMA, "variant": routing.VARIANT,
            "header": {"inputs": {}, "rules": {}},
            "names": list(names), "divine": list(divine), "aliases": list(aliases),
            "events": list(events), "books": list(books), "exclusions": list(exclusions)}

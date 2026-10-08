"""KG-layer record contracts: kg0 (names, extra spans, parallel links, design §2.17),
events (§2.21, the R2 registry: curated anchors, pdf_terms and external_aliases) and route
(the R2 routing lexicon terms, §5.2: kg0 names, divine surfaces, query aliases, event
triggers and book names).

Content rules that are policy rather than shape (an anchor's evidence is its pericope's
heading, a pdf_term lies inside an anchor, a trigger has one owner) are G-EVENT's and
G-ROUTE's.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ragcommon import ids
from ragdata.contract.fields import (
    Record, boolean, id_of, integer, legacy_key, list_of, nested, one_of, optional, parsed,
    require, spec, string, verse_order,
)

SPAN_SOURCES = ("pdf_underline", "divine_rule", "lexicon", "curated_underline")
EXTRA_SOURCES = SPAN_SOURCES[1:]
NAME_TYPES = ("Person", "Place", "Group")
# region of a span -> the id kinds its container may have
REGION_CONTAINERS = MappingProxyType({
    "body": ("slot", "unit"), "superscription": ("superscription",), "heading": ("heading",),
    "footnote": ("footnote",),
})
# a routing term's kind -> the lexicon category that lists it (design §5.2, R2)
ROUTE_KINDS = MappingProxyType({"name": "names", "dotless": "names", "divine": "divine",
                                "alias": "aliases", "event": "events", "book": "books"})
ROUTE_CATEGORIES = ("names", "divine", "aliases", "events", "books")
ROUTE_TYPES = ("Person", "Place")
UNROUTABLE_RULES = ("rt.min_len", "rt.common_word")


def _sorted_unique(values: tuple, what: str) -> None:
    require(list(values) == sorted(set(values)), f"{what} must be sorted and unique")


# ------------------------------------------------------------------ kg0


@dataclass(frozen=True)
class TypeCandidate(Record):
    type: str = spec(one_of(*NAME_TYPES))
    rule: str = spec(string())


@dataclass(frozen=True)
class Name(Record):
    """A normalized name (``norm_key``) and the surfaces the PDF prints it with."""

    name_id: str = spec(id_of("name"))
    norm_key: str = spec(string())
    surfaces: tuple = spec(list_of(string(), min_len=1))
    body_occurrences: int = spec(integer(0))
    span_sources: tuple = spec(list_of(one_of(*SPAN_SOURCES), min_len=1))
    type_candidates: tuple = spec(list_of(nested(TypeCandidate)))
    norm_rule_ids: tuple = spec(list_of(string()))
    evidence_span_id: str = spec(id_of("name_span"))
    provenance_class: str = spec(one_of("pdf_deterministic", "pdf_rule"))

    def check(self) -> None:
        require(self.name_id == ids.name_id(self.norm_key), "name_id must be nm:sha1(norm_key)")
        _sorted_unique(self.surfaces, "surfaces")
        _sorted_unique(self.span_sources, "span_sources")
        _sorted_unique(self.norm_rule_ids, "norm_rule_ids")
        ruled = self.provenance_class == "pdf_rule"
        require(ruled == bool(self.norm_rule_ids), "pdf_rule iff a normalization rule applied")


@dataclass(frozen=True)
class ExtraSpan(Record):
    """A name span the PDF does not underline: a divine name or title (divine_rule), a
    name in a region without underlines (lexicon) or a missed underline (curated)."""

    span_id: str = spec(id_of("name_span"))
    container_id: str = spec(string())
    region: str = spec(one_of(*REGION_CONTAINERS))
    start: int = spec(integer(0))
    end: int = spec(integer(1))
    surface: str = spec(string())
    source: str = spec(one_of(*EXTRA_SOURCES))
    rule_id: str | None = spec(optional(string()))
    registry_version: str = spec(string())
    decision_ref: str | None = spec(optional(string()))
    decided_by: str | None = spec(optional(string()))
    provenance_class: str = spec(one_of("pdf_rule", "curated_human"))

    def check(self) -> None:
        require(self.span_id == ids.name_span_id(self.container_id, self.start),
                "span_id must be ns:{container_id}@{start}")
        require(self.end - self.start == len(self.surface), "end - start must equal len(surface)")
        require(parsed(self.container_id).kind in REGION_CONTAINERS[self.region],
                f"a {self.region} span cannot sit in {self.container_id}")
        curated = self.source == "curated_underline"
        require(curated == (self.provenance_class == "curated_human"),
                "curated_underline spans (and only they) are curated_human")
        require(curated == (self.rule_id is None), "rule spans name their rule; curated ones not")
        require(curated == (self.decision_ref is not None) == (self.decided_by is not None),
                "curated spans (and only they) carry decision_ref and decided_by")


@dataclass(frozen=True)
class ParallelLink(Record):
    """One pericope pair a printed parallel reference (kind=parallel) draws."""

    link_key: str = spec(string())
    pr_id: str = spec(id_of("parallel_ref"))
    from_pericope: str = spec(id_of("pericope"))
    to_pericope: str = spec(id_of("pericope"))
    target_start_slot: str = spec(id_of("slot"))
    target_end_slot: str = spec(id_of("slot"))
    provenance_class: str = spec(one_of("pdf_deterministic"))

    def check(self) -> None:
        require(self.link_key == f"{self.pr_id}|{self.to_pericope}", "link_key must be pr_id|to")
        require(self.from_pericope != self.to_pericope, "a parallel link joins two pericopes")
        require(parsed(self.target_start_slot).book_id == parsed(self.target_end_slot).book_id
                and verse_order(self.target_start_slot) <= verse_order(self.target_end_slot),
                "target range must ascend within one book")


# ------------------------------------------------------------------ events


def _anchor_keys_check(a: Anchor) -> None:
    require(a.passage_id == ids.passage_id(a.start_key), "passage_id must be ps:{start_key}")
    for key, slot in ((a.start_key, a.start_slot), (a.end_key, a.end_slot)):
        p = parsed(key)
        require(slot == ids.slot_key(p.book_id, p.chapter, p.verse), f"{slot} is not {key}'s slot")
    s, e = parsed(a.start_key), parsed(a.end_key)
    require((s.book_id, s.chapter) == (e.book_id, e.chapter), "an anchor stays in one chapter")
    require(verse_order(a.start_key) <= verse_order(a.end_key), "anchor range descends")


@dataclass(frozen=True)
class Quote(Record):
    unit_key: str = spec(id_of("unit"))
    text: str = spec(string())


@dataclass(frozen=True)
class Evidence(Record):
    """Why an anchor is the event: its pericope's heading, or a quote from one of its units."""

    heading_id: str | None = spec(optional(id_of("heading")))
    quote: Quote | None = spec(optional(nested(Quote)))

    def check(self) -> None:
        require((self.heading_id is None) != (self.quote is None),
                "evidence is a heading_id or a quote, exactly one")


@dataclass(frozen=True)
class Anchor(Record):
    """One passage of a pericope the registry declares (passage level, design D6)."""

    pericope_id: str = spec(id_of("pericope"))
    passage_id: str = spec(id_of("passage"))
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    start_slot: str = spec(id_of("slot"))
    end_slot: str = spec(id_of("slot"))
    evidence: Evidence = spec(nested(Evidence))
    provenance_class: str = spec(one_of("curated_human"))
    decided_by: str = spec(string())

    def check(self) -> None:
        _anchor_keys_check(self)


def _location(value: Any) -> str:
    """A pdf_term's ``at``: a heading id or a unit key."""
    require(isinstance(value, str) and (ids.is_valid(value, "heading")
                                        or ids.is_valid(value, "unit")),
            f"expected a heading id or a unit key, got {value!r}")
    return value


@dataclass(frozen=True)
class PdfTerm(Record):
    text: str = spec(string())
    at: str = spec(_location)
    decided_by: str = spec(string())
    provenance_class: str = spec(one_of("curated_human"))


@dataclass(frozen=True)
class ExternalAlias(Record):
    text: str = spec(string())
    source: str = spec(string())
    note: str = spec(string())
    provenance_class: str = spec(one_of("external_event_alias"))


@dataclass(frozen=True)
class MergedEvent(Record):
    """A retired event id, merged into the event that lists it."""

    event_id: str = spec(id_of("event"))
    legacy_ids: tuple = spec(list_of(legacy_key(), min_len=1))


@dataclass(frozen=True)
class Event(Record):
    event_id: str = spec(id_of("event"))
    legacy_ids: tuple = spec(list_of(legacy_key(), min_len=1))
    name: str = spec(string())
    name_source: str = spec(one_of("pdf_heading", "curated"))
    name_heading_id: str | None = spec(optional(id_of("heading")))
    anchors: tuple = spec(list_of(nested(Anchor), min_len=1))
    pdf_terms: tuple = spec(list_of(nested(PdfTerm)))
    external_aliases: tuple = spec(list_of(nested(ExternalAlias)))
    merged_from: tuple = spec(list_of(nested(MergedEvent)))
    decided_by: str = spec(string())
    provenance_class: str = spec(one_of("curated_human"))

    @property
    def triggers(self) -> tuple[str, ...]:
        return tuple(t.text for t in (*self.pdf_terms, *self.external_aliases))

    def check(self) -> None:
        passages = [a.passage_id for a in self.anchors]
        require(len(set(passages)) == len(passages), "an event anchors a passage once")
        require(len(set(self.triggers)) == len(self.triggers), "trigger texts repeat")
        require((self.name_source == "pdf_heading") == (self.name_heading_id is not None),
                "name_heading_id iff name_source is pdf_heading")
        require(len(set(self.legacy_ids)) == len(self.legacy_ids), "legacy_ids repeat")
        merged = {i for m in self.merged_from for i in m.legacy_ids}
        require(merged <= set(self.legacy_ids), "a merged event's legacy ids are the event's")


# ------------------------------------------------------------------ route


@dataclass(frozen=True)
class RouteTarget(Record):
    """One candidate a routing term stands for: a kg0 name, a divine pattern or an event.
    ``route_types`` is the only type the router counts (K4 resolves it, design §5.2)."""

    ref: str = spec(string())
    label: str = spec(string())
    type_candidates: tuple = spec(list_of(nested(TypeCandidate)))
    route_types: tuple = spec(list_of(one_of(*ROUTE_TYPES)))

    def check(self) -> None:
        _sorted_unique(self.route_types, "route_types")


@dataclass(frozen=True)
class RouteTerm(Record):
    """One term of the routing lexicon: its surface, every candidate it stands for, whether
    the matcher sees it and its provenance. A field that does not apply to the kind is null
    or empty; the lexicon lists the same object without ``term_key``."""

    term_key: str = spec(string())
    surface: str = spec(string())
    kind: str = spec(one_of(*ROUTE_KINDS))
    targets: tuple = spec(list_of(nested(RouteTarget)))
    routable: bool = spec(boolean())
    unroutable_rule: str | None = spec(optional(one_of(*UNROUTABLE_RULES)))
    provenance_class: str = spec(one_of("pdf_deterministic", "pdf_rule", "curated_human",
                                        "curated_metadata", "external_query",
                                        "external_event_alias"))
    source: str = spec(string())
    evidence_span_id: str | None = spec(optional(id_of("name_span")))
    rule_id: str | None = spec(optional(string()))
    norm_rule_ids: tuple = spec(list_of(string()))
    at: str | None = spec(optional(string()))
    decided_by: str | None = spec(optional(string()))
    note: str | None = spec(optional(string()))
    alias_id: str | None = spec(optional(string()))
    book_id: str | None = spec(optional(id_of("book")))
    full_name: str | None = spec(optional(string()))

    def check(self) -> None:
        category, _, position = self.term_key.partition("/")
        require(category == ROUTE_KINDS[self.kind] and len(position) == 4
                and position.isdigit(), "term_key must be {category}/{position:04d}")
        require(self.routable == (self.unroutable_rule is None),
                "unroutable_rule is set iff the term is not routable")
        refs = [t.ref for t in self.targets]
        require(refs == sorted(set(refs)), "targets must be sorted by ref and unique")
        book = self.kind == "book"
        require(book == (self.book_id is not None) == (self.full_name is not None)
                and book != bool(self.targets),
                "a book carries book_id and full_name and no target; every other kind a target")

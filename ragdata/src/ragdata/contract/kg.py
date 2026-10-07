"""KG-layer record contracts: kg0 (names, extra spans, parallel links, design §2.17),
events (§2.21, R1 frozen version) and route (the routing lexicon terms, §5.2, D-12(a)).

R1 content rules that are policy rather than shape (anchors are ``legacy_tuned``,
triggers retire by R2, no ``pdf_terms`` yet) are G-EVENT's and G-ROUTE's; the
contracts here accept what R2 will also write.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ragcommon import ids
from ragdata.contract.fields import (
    Record, id_of, integer, json_object, legacy_key, list_of, nested, one_of, optional, parsed,
    require, spec, string, verse_order,
)
from ragdata.contract.provenance import RETIRE_RELEASES

SPAN_SOURCES = ("pdf_underline", "divine_rule", "lexicon", "curated_underline")
EXTRA_SOURCES = SPAN_SOURCES[1:]
NAME_TYPES = ("Person", "Place", "Group")
# region of a span -> the id kinds its container may have
REGION_CONTAINERS = MappingProxyType({
    "body": ("slot", "unit"), "superscription": ("superscription",), "heading": ("heading",),
    "footnote": ("footnote",),
})
ANCHOR_CHANGES = ("same", "narrowed", "widened")
ROUTE_CATEGORIES = ("persons", "places", "events", "books")


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


@dataclass(frozen=True)
class Anchor(Record):
    passage_id: str = spec(id_of("passage"))
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    start_slot: str = spec(id_of("slot"))
    end_slot: str = spec(id_of("slot"))
    change: str = spec(one_of(*ANCHOR_CHANGES))
    legacy_anchor: str = spec(legacy_key())
    provenance_class: str = spec(one_of("legacy_tuned", "curated_human"))

    def check(self) -> None:
        require(self.passage_id == ids.passage_id(self.start_key), "passage_id must be ps:{start_key}")
        for key, slot in ((self.start_key, self.start_slot), (self.end_key, self.end_slot)):
            p = parsed(key)
            require(slot == ids.slot_key(p.book_id, p.chapter, p.verse), f"{slot} is not {key}'s slot")
        s, e = parsed(self.start_key), parsed(self.end_key)
        require((s.book_id, s.chapter) == (e.book_id, e.chapter), "an anchor stays in one chapter")
        require(verse_order(self.start_key) <= verse_order(self.end_key), "anchor range descends")


@dataclass(frozen=True)
class LegacyTrigger(Record):
    text: str = spec(string())
    provenance_class: str = spec(one_of("external_legacy"))
    source: str = spec(string())
    note: str = spec(string())
    retire_by: str = spec(one_of(*RETIRE_RELEASES))


@dataclass(frozen=True)
class Event(Record):
    event_id: str = spec(id_of("event"))
    legacy_id: str = spec(legacy_key())
    name: str = spec(string())
    legacy_provenance: str = spec(string())
    anchors: tuple = spec(list_of(nested(Anchor), min_len=1))
    legacy_triggers: tuple = spec(list_of(nested(LegacyTrigger)))
    pdf_terms: tuple = spec(list_of(json_object()))
    external_aliases: tuple = spec(list_of(json_object()))
    provenance_class: str = spec(one_of("legacy_tuned", "curated_human"))

    def check(self) -> None:
        passages = [a.passage_id for a in self.anchors]
        require(len(set(passages)) == len(passages), "an event anchors a passage once")
        texts = [t.text for t in self.legacy_triggers]
        require(len(set(texts)) == len(texts), "legacy_triggers repeat")


@dataclass(frozen=True)
class AnchorChange(Record):
    """An anchor whose verses changed when its legacy pericope became a passage (§3.3)."""

    change_key: str = spec(string())
    event_id: str = spec(id_of("event"))
    legacy_anchor: str = spec(legacy_key())
    passage_id: str = spec(id_of("passage"))
    change: str = spec(one_of("narrowed", "widened"))
    legacy_start_slot: str = spec(id_of("slot"))
    legacy_end_slot: str = spec(id_of("slot"))
    start_key: str = spec(id_of("key"))
    end_key: str = spec(id_of("key"))
    removed_slots: tuple = spec(list_of(id_of("slot")))
    added_keys: tuple = spec(list_of(id_of("key")))
    provenance_class: str = spec(one_of("external_legacy"))
    source: str = spec(string())
    note: str = spec(string())
    retire_by: str = spec(one_of(*RETIRE_RELEASES))

    def check(self) -> None:
        require(self.change_key == f"{self.event_id}|{self.legacy_anchor}",
                "change_key must be event_id|legacy_anchor")
        narrowed = self.change == "narrowed"
        require(narrowed == bool(self.removed_slots) and narrowed != bool(self.added_keys),
                "a narrowed anchor lists removed slots, a widened one added keys")


# ------------------------------------------------------------------ route


@dataclass(frozen=True)
class RouteTerm(Record):
    """One entry of the routing lexicon, at its position in the frozen file."""

    term_key: str = spec(string())
    category: str = spec(one_of(*ROUTE_CATEGORIES))
    position: int = spec(integer(0))
    term: str = spec(string())
    aliases: tuple = spec(list_of(string()))
    book_id: str | None = spec(optional(id_of("book")))
    full_name: str | None = spec(optional(string()))
    provenance_class: str = spec(one_of("external_legacy", "external_query",
                                        "external_event_alias", "pdf_rule"))
    source: str = spec(string())
    note: str = spec(string())
    retire_by: str | None = spec(optional(one_of(*RETIRE_RELEASES)))

    def check(self) -> None:
        require(self.term_key == f"{self.category}/{self.position:04d}",
                "term_key must be {category}/{position:04d}")
        named = self.category in ("persons", "places")
        require(named == bool(self.aliases), "persons and places (only) list aliases")
        book = self.category == "books"
        require(book == (self.book_id is not None) == (self.full_name is not None),
                "books (only) carry book_id and full_name")

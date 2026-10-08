"""The closed provenance enumeration and the evidence each class needs (design §9.1, G-PROV).

Every record of the KG layers (and every nested fact with its own
``provenance_class``: an event anchor, a trigger) names one class. A class
needs evidence fields:

- ``coordinate``: a PDF coordinate — one of ``COORDINATE_KEYS`` set, or anchors that each
  carry one (an event row);
- ``rule``: the rule that produced it (``rule_id``, or a non-empty ``norm_rule_ids``);
- ``slot_range``: ``start_slot`` and ``end_slot``, or anchors that each carry both;
- any other name: that field, set (non-empty).
"""

from __future__ import annotations

from types import MappingProxyType

PROVENANCE_CLASSES = (
    "pdf_deterministic", "pdf_rule", "curated_human", "curated_ai_accepted", "curated_metadata",
    "legacy_tuned", "external_event_alias", "external_query", "external_legacy",
    "external_reference", "external_dataset",
)
COORDINATE_KEYS = ("span_id", "evidence_span_id", "pr_id", "heading_id", "container_id",
                   "passage_id", "start_slot", "at")
EVIDENCE = MappingProxyType({
    "pdf_deterministic": ("coordinate",),
    "pdf_rule": ("coordinate", "rule"),
    "curated_human": ("coordinate", "decided_by"),
    "curated_ai_accepted": ("coordinate", "cache_keys", "audit_ref"),
    "curated_metadata": ("source",),
    "legacy_tuned": ("slot_range",),
    "external_event_alias": ("source", "note"),
    "external_query": ("source", "note"),
    "external_legacy": ("source", "note", "retire_by"),
    "external_reference": ("source", "note", "target"),
    "external_dataset": ("source", "note"),
})
RETIRE_RELEASES = ("R2",)

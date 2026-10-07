"""Structured refs and gold slots of one GT reference (design §11.3, §2.12).

The v1 ``reference`` string is parsed once with ``ragcommon.refs`` in strict
mode (external verse numbers go through ref_aliases) and expanded into the
slots of the text layer. Slots with status present or merged are gold; omitted
slots (``omitted_variant``: the verse exists only in a variant footnote) are
listed apart, explicitly, and are never gold. A reference whose slots are all
omitted, or that names a slot the layer does not have, raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ragcommon.refs import expand_slots, parse_refs
from ragcommon.versification import Versification
from ragdata.gt.corpus import GOLD_STATUSES, OMITTED_STATUS, ServiceText

REF_KEYS = ("book_id", "ch", "v_start", "v_end", "ch_end")


class GoldError(ValueError):
    """A reference that yields no usable gold."""


@dataclass(frozen=True)
class GoldRefs:
    refs: tuple[dict[str, Any], ...]
    gold_slots: tuple[str, ...]
    omitted_slots: tuple[str, ...]
    aliases_applied: tuple[str, ...]


def derive_gold(reference: str, corpus: ServiceText, vers: Versification) -> GoldRefs:
    parsed = parse_refs(reference, strict=True, versification=vers)
    slots: dict[str, None] = {}
    for ref in parsed.refs:
        for key in expand_slots(ref, vers):
            slots.setdefault(key, None)
    gold, omitted = [], []
    for key in slots:
        status = corpus.slot_status.get(key)
        if status in GOLD_STATUSES:
            gold.append(key)
        elif status == OMITTED_STATUS:
            omitted.append(key)
        else:
            raise GoldError(f"{reference!r}: {key} is not a slot of {corpus.version}")
    if not gold:
        raise GoldError(f"{reference!r}: no gold slot (omitted: {omitted})")
    refs = tuple({k: ref.to_dict()[k] for k in REF_KEYS} for ref in parsed.refs)
    return GoldRefs(refs, tuple(gold), tuple(omitted), parsed.aliases_applied)

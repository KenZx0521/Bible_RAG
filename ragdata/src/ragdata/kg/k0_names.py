"""K0 names: underline strokes (and curated underlines) become mentions, mentions become names.

A mention is one name occurrence: a single underline span, a merge group of them
(鹽＋海 → 鹽海, rule ``merge``) or a curated underline. Its ``norm_key`` is what
the PDF underlines — never a truncated form (rule ``truncation``) and never with
the suffix drawn outside the line (``suffix_outside``); a generic noun drawn
inside the line stays part of the name (``generic_inside``) and a ``‧`` name is
not split (``interpunct``). Spans declared ``not_entity`` make no mention but
stay in the text layer (and still block the other span sources).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.kg.registries import Normalization, RegistryError, UnderlineFixes

BODY = "body"


@dataclass(frozen=True)
class Mention:
    norm_key: str
    surface: str
    region: str
    source: str            # pdf_underline | curated_underline | lexicon
    span_ids: tuple[str, ...]
    rules: tuple[str, ...]
    after: str             # the character printed right after it ("" at the end)


def _is_han(char: str) -> bool:
    return unicodedata.name(char, "").startswith(("CJK UNIFIED", "CJK COMPATIBILITY"))


def _rules(surface: str, norm: Normalization, merged: bool) -> tuple[str, ...]:
    odd = sorted({c for c in surface if not _is_han(c)} - {norm.interpunct})
    if odd:
        raise RegistryError(f"name {surface!r}: unknown interpunct or symbol {odd} "
                            f"(only {norm.interpunct!r} is declared)")
    found = [norm.rule_ids["merge"]] if merged else []
    if norm.generic(surface):
        found.append(norm.rule_ids["generic_inside"])
    if norm.interpunct in surface:
        found.append(norm.rule_ids["interpunct"])
    return tuple(sorted(found))


def _check_not_entity(spans: Sequence[Any], fixes: UnderlineFixes) -> None:
    by_id = {s.span_id: s for s in spans}
    for span_id, fix in fixes.not_entity.items():
        span = by_id.get(span_id)
        if span is None:
            raise RegistryError(f"underline_fixes {fix.fix_id}: no underline span {span_id}")
        if span.surface != fix.surface:
            raise RegistryError(f"underline_fixes {fix.fix_id}: {span_id} has surface "
                                f"{span.surface!r}, not {fix.surface!r}")


def _merged(members: Sequence[Any], texts: Mapping[str, str], norm: Normalization) -> Mention:
    first, last = members[0], members[-1]
    contiguous = all(a.container_id == b.container_id and a.end == b.start
                     for a, b in zip(members, members[1:]))
    surface = "".join(m.surface for m in members)
    if not contiguous or surface not in norm.merges:
        raise RegistryError(f"merge group {first.merge_group} ({surface!r}) is not a contiguous "
                            f"group listed in merge.groups {list(norm.merges)}")
    text = texts[first.container_id]
    return Mention(surface, surface, first.region, "pdf_underline",
                   tuple(m.span_id for m in members), _rules(surface, norm, True),
                   text[last.end:last.end + 1])


def underline_mentions(spans: Sequence[Any], texts: Mapping[str, str], norm: Normalization,
                       fixes: UnderlineFixes) -> list[Mention]:
    """One mention per underline span or merge group, in span order (``not_entity`` dropped)."""
    _check_not_entity(spans, fixes)
    kept = [s for s in spans if s.span_id not in fixes.not_entity]
    groups: dict[str, list[Any]] = defaultdict(list)
    for span in kept:
        if span.merge_group is not None:
            groups[span.merge_group].append(span)
    mentions = []
    for span in kept:
        if span.merge_group is not None:
            if groups[span.merge_group][0] is span:
                mentions.append(_merged(groups[span.merge_group], texts, norm))
            continue
        text = texts[span.container_id]
        mentions.append(Mention(span.surface, span.surface, span.region, "pdf_underline",
                                (span.span_id,), _rules(span.surface, norm, False),
                                text[span.end:span.end + 1]))
    return mentions


def curated_mentions(fixes: UnderlineFixes, texts: Mapping[str, str],
                     underlines: Mapping[str, Sequence[tuple[int, int]]],
                     norm: Normalization) -> list[Mention]:
    """Curated underlines must read their surface in a verse unit and miss every underline."""
    mentions = []
    for fix in fixes.curated:
        end = fix.start + len(fix.surface)
        text = texts.get(fix.container_id) if ids.is_valid(fix.container_id, "unit") else None
        if text is None or text[fix.start:end] != fix.surface:
            raise RegistryError(f"underline_fixes {fix.fix_id}: {fix.container_id}@{fix.start} "
                                f"does not read {fix.surface!r}")
        if any(fix.start < b and a < end for a, b in underlines.get(fix.container_id, ())):
            raise RegistryError(f"underline_fixes {fix.fix_id}: overlaps a PDF underline")
        mentions.append(Mention(fix.surface, fix.surface, BODY, "curated_underline",
                                (ids.name_span_id(fix.container_id, fix.start),),
                                _rules(fix.surface, norm, False), text[end:end + 1]))
    return mentions


def _name_row(key: str, mentions: Sequence[Mention], norm: Normalization) -> dict[str, Any]:
    rules = sorted({r for m in mentions for r in m.rules})
    types = [{"type": norm.generic_type, "rule": norm.rule_ids["generic_inside"]}] \
        if norm.generic(key) else []
    return {
        "name_id": ids.name_id(key), "norm_key": key,
        "surfaces": sorted({m.surface for m in mentions}),
        "body_occurrences": sum(1 for m in mentions
                                if m.region == BODY and m.source != "lexicon"),
        "span_sources": sorted({m.source for m in mentions}),
        "type_candidates": types, "norm_rule_ids": rules,
        "evidence_span_id": mentions[0].span_ids[0],
        "provenance_class": "pdf_rule" if rules else "pdf_deterministic",
    }


def name_rows(mentions: Sequence[Mention], norm: Normalization) -> list[dict[str, Any]]:
    """One name per norm_key, in order of first mention."""
    by_key: dict[str, list[Mention]] = {}
    for mention in mentions:
        by_key.setdefault(mention.norm_key, []).append(mention)
    return [_name_row(key, group, norm) for key, group in by_key.items()]

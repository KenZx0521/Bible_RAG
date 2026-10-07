"""K0: the kg0 layer's rows from the text and struct records and the K0 registries.

``kg0_rows`` returns ``names``, ``extra_spans`` and ``parallel_links`` and a report of
what every rule did; ``kg0_counts`` turns them into the per-source, per-surface
counts G-KG0 checks against ``expectations/kg0_counts.yaml`` (``ragdata expect kg0``
writes that file from the same function).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata.contract.kg import EXTRA_SOURCES
from ragdata.gates.base import Snapshot
from ragdata.kg import k0_names, k0_parallel, k0_spans
from ragdata.kg.k0_names import Mention
from ragdata.kg.registries import K0Registries, Normalization

COUNTS_SCHEMA = "ragdata.kg0_counts.v1"
REPORT_SCHEMA = "ragdata.kg0_report.v1"
CONTAINER_SOURCES = {"superscription": ("chapter_texts", "id"), "heading": ("headings", "heading_id"),
                     "footnote": ("footnotes", "fn_id")}


@dataclass(frozen=True)
class K0Result:
    rows: Mapping[str, list[dict[str, Any]]]
    report: Mapping[str, Any]
    versions: Mapping[str, str]


def _texts(snapshot: Snapshot) -> dict[str, str]:
    texts = {u.unit_key: u.text_pdf for u in snapshot.of("verse_units")}
    texts.update({f.fn_id: f.text_pdf for f in snapshot.of("footnotes")})
    return texts


def _underlines(snapshot: Snapshot) -> dict[str, list[tuple[int, int]]]:
    blocked: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for span in snapshot.of("name_spans"):
        blocked[span.container_id].append((span.start, span.end))
    return blocked


def _region_containers(snapshot: Snapshot, regions: Sequence[str]) -> list[tuple[str, str, str]]:
    found = []
    for region in regions:
        type_name, pk = CONTAINER_SOURCES[region]
        found += [(getattr(r, pk), region, r.text_pdf) for r in snapshot.of(type_name)
                  if region != "superscription" or r.kind == "superscription"]
    return found


def _lexicon_mentions(rows: Sequence[dict[str, Any]]) -> list[Mention]:
    return [Mention(r["surface"], r["surface"], r["region"], "lexicon", (r["span_id"],), (), "")
            for r in rows]


def _normalization_report(mentions: Sequence[Mention], norm: Normalization) -> dict[str, Any]:
    body = [m for m in mentions if m.region == "body" and m.source == "pdf_underline"]
    generic = [m for m in body if len(m.span_ids) == 1 and norm.generic(m.surface)]
    by_noun: dict[str, Counter] = defaultdict(Counter)
    for m in generic:
        by_noun[m.surface[-1]][m.surface] += 1
    keys = {m.norm_key for m in mentions}
    return {
        "suffix_outside": {s: sum(1 for m in body if m.after == s) for s in norm.suffixes},
        "generic_inside": {"types": len({m.surface for m in generic}), "occurrences": len(generic),
                           "by_noun": {n: {"types": len(c), "occurrences": sum(c.values())}
                                       for n, c in sorted(by_noun.items())}},
        "merge": dict(Counter(m.norm_key for m in mentions if len(m.span_ids) > 1)),
        "interpunct": {"names": len({k for k in keys if norm.interpunct in k}),
                       "occurrences": sum(1 for m in body if norm.interpunct in m.norm_key)},
        "truncation": [{"truncated": t, "full": f, "full_is_name": f in keys,
                        "truncated_is_name": t in keys} for t, f in norm.truncations],
    }


def kg0_rows(snapshot: Snapshot, regs: K0Registries) -> K0Result:
    norm, texts, underlines = regs.normalization, _texts(snapshot), _underlines(snapshot)
    mentions = [*k0_names.underline_mentions(snapshot.of("name_spans"), texts, norm, regs.fixes),
                *k0_names.curated_mentions(regs.fixes, texts, underlines, norm)]
    curated = k0_spans.curated_spans(regs.fixes)
    blocked = defaultdict(list, {k: list(v) for k, v in underlines.items()})
    for row in curated:
        blocked[row["container_id"]].append((row["start"], row["end"]))
    divine, excluded = k0_spans.divine_spans(snapshot.of("verse_units"), regs.divine, blocked)
    lexicon, skipped = k0_spans.lexicon_spans(
        _region_containers(snapshot, norm.lexicon.regions), {m.norm_key for m in mentions},
        norm.lexicon, norm.version, underlines)
    rows = {"names": k0_names.name_rows([*mentions, *_lexicon_mentions(lexicon)], norm),
            "extra_spans": [*divine, *lexicon, *curated],
            "parallel_links": k0_parallel.parallel_links(snapshot)}
    report = {
        "schema": REPORT_SCHEMA, "registries": regs.versions(),
        "normalization": _normalization_report(mentions, norm),
        "divine": {"excluded": dict(sorted(excluded.items()))},
        "lexicon": {"skipped": dict(skipped),
                    "short_words": sorted({m.norm_key for m in mentions
                                           if len(m.norm_key) < norm.lexicon.min_len})},
        "not_entity": sorted(regs.fixes.not_entity),
    }
    return K0Result(MappingProxyType(rows), MappingProxyType(report),
                    MappingProxyType(regs.versions()))


def _tally(spans: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"total": len(spans),
            "by_region": dict(sorted(Counter(s["region"] for s in spans).items())),
            "by_surface": dict(sorted(Counter(s["surface"] for s in spans).items()))}


def kg0_counts(result: K0Result, text_version: str, struct_version: str) -> dict[str, Any]:
    spans = result.rows["extra_spans"]
    return {
        "schema": COUNTS_SCHEMA, "registries": dict(sorted(result.versions.items())),
        "inputs": {"struct": struct_version, "text": text_version},
        "names": len(result.rows["names"]), "parallel_links": len(result.rows["parallel_links"]),
        "extra_spans": {source: _tally([s for s in spans if s["source"] == source])
                        for source in EXTRA_SOURCES},
    }

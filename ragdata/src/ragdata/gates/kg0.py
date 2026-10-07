"""G-KG0: the kg0 layer agrees with the text it was built from and with its expectations
(design §8; ``expectations/kg0_counts.yaml``, written by ``ragdata expect kg0``).

- every extra span is the slice of its container's PDF text, touches no underline span
  and no other extra span; divine spans sit in verse text, lexicon spans outside it and
  only on a name;
- the names are exactly the underline spans (less the registry's ``not_entity`` ones,
  merge groups as one) plus the curated underlines, with their body occurrence counts,
  no stray interpunct and a real evidence span;
- every parallel link comes from a ``kind=parallel`` reference, leaves the pericope that
  carries its heading and reaches a pericope its target overlaps (never a section_range);
- the counts per source, region and surface, the name and link counts, the registry
  versions and the input layers equal the expectation file.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from typing import Any, Mapping

from ragcommon import ids
from ragdata.gates.base import GateResult, Snapshot, violations_result
from ragdata.kg.k0_parallel import slot_order

NAME = "G-KG0"
INTERPUNCT = "‧"
CONTAINERS = {"slot": ("verse_units", "unit_key"), "unit": ("verse_units", "unit_key"),
              "heading": ("headings", "heading_id"), "footnote": ("footnotes", "fn_id"),
              "superscription": ("chapter_texts", "id")}


def _texts(snapshot: Snapshot) -> dict[str, str]:
    texts = {}
    for type_name, pk in set(CONTAINERS.values()):
        texts.update({getattr(r, pk): r.text_pdf for r in snapshot.of(type_name)})
    return texts


def _overlap(spans: list[tuple[int, int, str]]) -> list[str]:
    ordered = sorted(spans)
    return [f"{b[2]} overlaps {a[2]}" for a, b in zip(ordered, ordered[1:]) if b[0] < a[1]]


def _span_checks(snapshot: Snapshot, names: set[str]) -> list[str]:
    texts, out = _texts(snapshot), []
    by_container: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for span in snapshot.of("name_spans"):
        by_container[span.container_id].append((span.start, span.end, span.span_id))
    for span in snapshot.of("extra_spans"):
        text = texts.get(span.container_id)
        if text is None or text[span.start:span.end] != span.surface:
            out.append(f"{span.span_id}: {span.surface!r} is not the text of {span.container_id}")
        if (span.source == "divine_rule") != (span.region == "body") and span.source != \
                "curated_underline":
            out.append(f"{span.span_id}: a {span.source} span cannot sit in {span.region}")
        if span.source == "lexicon" and span.surface not in names:
            out.append(f"{span.span_id}: lexicon span {span.surface!r} is not a name")
        by_container[span.container_id].append((span.start, span.end, span.span_id))
    for spans in by_container.values():
        out += _overlap(spans)
    return out


def _expected_names(snapshot: Snapshot, not_entity: set[str]) -> Counter:
    """norm_key -> body occurrences, recomputed from the text layer's spans."""
    found: Counter = Counter()
    groups: dict[str, list[Any]] = defaultdict(list)
    for span in snapshot.of("name_spans"):
        if span.span_id in not_entity:
            continue
        if span.merge_group is not None:
            groups[span.merge_group].append(span)
            continue
        found[span.surface] += span.region == "body"
    for members in groups.values():
        found["".join(m.surface for m in members)] += members[0].region == "body"
    for span in snapshot.of("extra_spans"):
        if span.source == "curated_underline":
            found[span.surface] += 1
    return found


def _stray(text: str) -> bool:
    return any(c != INTERPUNCT and not unicodedata.name(c, "").startswith("CJK") for c in text)


def _name_checks(snapshot: Snapshot, not_entity: set[str]) -> list[str]:
    expected, out = _expected_names(snapshot, not_entity), []
    names = {n.norm_key: n for n in snapshot.of("names")}
    out += [f"names: {k!r} is underlined but has no name"
            for k in sorted(set(expected) - set(names))]
    out += [f"names: {k!r} is no underline" for k in sorted(set(names) - set(expected))]
    spans = {s.span_id for s in snapshot.of("name_spans")} | \
        {s.span_id for s in snapshot.of("extra_spans")}
    for key, name in names.items():
        if key in expected and name.body_occurrences != expected[key]:
            out.append(f"names {key!r}: body_occurrences {name.body_occurrences}, "
                       f"spans give {expected[key]}")
        if _stray(key):
            out.append(f"names {key!r}: stray interpunct or symbol")
        if name.evidence_span_id not in spans:
            out.append(f"names {key!r}: evidence span {name.evidence_span_id} not found")
    return out


def _link_checks(snapshot: Snapshot) -> list[str]:
    order, out = slot_order(snapshot), []
    refs = snapshot.index("parallel_refs")
    pericopes = snapshot.index("pericopes")
    for link in snapshot.of("parallel_links"):
        pr, src, dst = refs.get(link.pr_id), pericopes.get(link.from_pericope), \
            pericopes.get(link.to_pericope)
        if pr is None or src is None or dst is None or pr.kind != "parallel":
            out.append(f"{link.link_key}: not a parallel reference between two pericopes")
            continue
        if pr.heading_id not in (src.heading_id, src.section_heading_id):
            out.append(f"{link.link_key}: {src.pericope_id} does not carry {pr.heading_id}")
        target = (link.target_start_slot, link.target_end_slot)
        lo, hi = (order.get(s) for s in target)
        if target not in {(t.start_slot, t.end_slot) for t in pr.targets} or None in (lo, hi) \
                or not (order[dst.start_slot] <= hi and lo <= order[dst.end_slot]):
            out.append(f"{link.link_key}: {dst.pericope_id} is not inside target {target}")
    return out


def _tally(snapshot: Snapshot) -> dict[str, Any]:
    spans: dict[str, list[Any]] = defaultdict(list)
    for span in snapshot.of("extra_spans"):
        spans[span.source].append(span)
    return {"names": len(snapshot.of("names")),
            "parallel_links": len(snapshot.of("parallel_links")),
            "extra_spans": {source: {"total": len(rows),
                                     "by_region": dict(Counter(r.region for r in rows)),
                                     "by_surface": dict(Counter(r.surface for r in rows))}
                            for source, rows in spans.items()}}


def _count_checks(snapshot: Snapshot, report: Mapping[str, Any], expected: Mapping[str, Any],
                  depends_on: Mapping[str, str]) -> list[str]:
    out = []
    if dict(report.get("registries", {})) != dict(expected["registries"]):
        out.append(f"registries {report.get('registries')} are not the expected "
                   f"{expected['registries']}")
    if dict(expected["inputs"]) != {k: depends_on.get(k) for k in expected["inputs"]}:
        out.append(f"inputs {expected['inputs']} are not the layer's {dict(depends_on)}")
    observed = _tally(snapshot)
    for key in ("names", "parallel_links"):
        if observed[key] != expected[key]:
            out.append(f"{key}: observed {observed[key]}, expected {expected[key]}")
    sources = set(observed["extra_spans"]) | set(expected["extra_spans"])
    empty = {"total": 0, "by_region": {}, "by_surface": {}}
    for source in sorted(sources):
        got, want = observed["extra_spans"].get(source, empty), expected["extra_spans"].get(source)
        for key in ("total", "by_region", "by_surface"):
            if want is None or got[key] != want[key]:
                out.append(f"extra_spans.{source}.{key} differs from the expectation")
    return out


def check_kg0(snapshot: Snapshot, report: Mapping[str, Any], expected: Mapping[str, Any],
              depends_on: Mapping[str, str]) -> GateResult:
    """``snapshot`` holds the text, struct and kg0 records; ``report`` is the layer's
    kg0_report.json and ``expected`` the loaded kg0_counts.yaml."""
    names = {n.norm_key for n in snapshot.of("names")}
    violations = [] if names else ["kg0 holds no names"]
    violations += _span_checks(snapshot, names)
    violations += _name_checks(snapshot, set(report.get("not_entity", ())))
    violations += _link_checks(snapshot)
    violations += _count_checks(snapshot, report, expected, depends_on)
    return violations_result(NAME, violations)

"""G-GRAPH: a graph layer's rows hold together, and hold to the layers it was built on.

- every node id is unique within its kind and every edge's ends exist and are of the kinds its
  type allows;
- the structure counts equal the layers': books, chapters, pericopes, passages, verses, names,
  events, and each structural edge type;
- every body mention is counted once, from its verse and from its passage;
- a kinship edge comes from the PDF (``provenance_class``), once per (type, source, target),
  SPOUSE_OF and SIBLING_OF run from the smaller id, and both ends' names are written in its evidence
  verses;
- PARENT_OF has no cycle;
- ``kg_meta.json`` tells the truth about the rows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from ragcommon import ids
from ragdata.gates.base import GateResult, Snapshot, violations_result
from ragdata.kg.graph_schema import (
    EDGE_ENDS, KIN_TYPES, META_KEYS, NODE_KINDS, PARENT, PDF_CLASSES, meta_doc,
)

NAME = "G-GRAPH"
Row = Mapping[str, Any]
Rows = Sequence[Row]
PARENT_ROLES = frozenset({"M", "P"})
NO_ROLE = "-"


def _node_problems(nodes: Rows) -> list[str]:
    out = [f"unknown node kind {r['kind']}" for r in nodes if r["kind"] not in NODE_KINDS]
    twice = Counter((r["kind"], r["id"]) for r in nodes)
    return out + [f"node id {key[1]} of {key[0]} appears {n} times" for key, n in twice.items() if n > 1]


def _edge_problems(edges: Rows, known: set[tuple[str, str]]) -> list[str]:
    out = []
    for r in edges:
        ends = EDGE_ENDS.get(r["type"])
        if ends is None:
            out.append(f"unknown edge type {r['type']}")
        elif (r["src_kind"], r["dst_kind"]) not in ends:
            out.append(f"{r['type']} cannot run from {r['src_kind']} to {r['dst_kind']}")
        for kind, node_id in ((r["src_kind"], r["src"]), (r["dst_kind"], r["dst"])):
            if (kind, node_id) not in known:
                out.append(f"{r['type']} end {kind} {node_id} does not exist")
    return out


def _expected_counts(snap: Snapshot) -> dict[tuple[str, ...], int]:
    passages = snap.of("passages")
    pericopes = snap.of("pericopes")
    return {
        ("Book",): len(snap.of("books")), ("Chapter",): len(snap.of("chapters")),
        ("Pericope",): len(pericopes), ("Passage",): len(passages),
        ("Verse",): len(snap.of("verse_units")), ("Name",): len(snap.of("names")),
        ("Event",): len(snap.of("events")),
        ("HAS_CHAPTER",): len(snap.of("chapters")),
        ("HAS_PASSAGE", "Chapter"): len(passages), ("HAS_PASSAGE", "Pericope"): len(passages),
        ("HAS_VERSE",): sum(len(p.unit_refs) for p in passages),
        ("NEXT", "Pericope"): sum(1 for p in pericopes if p.next_id),
        ("NEXT", "Passage"): len(passages) - len({ids.parse(p.chapter_key).book_id for p in passages}),
        ("PARALLEL",): len(snap.of("parallel_links")),
        ("ANCHORED_AT",): len({(e.event_id, a.pericope_id) for e in snap.of("events") for a in e.anchors}),
    }


def _found_counts(nodes: Rows, edges: Rows) -> Counter[tuple[str, ...]]:
    found: Counter[tuple[str, ...]] = Counter((r["kind"],) for r in nodes)
    for r in edges:
        split = r["type"] in ("HAS_PASSAGE", "NEXT")
        found[(r["type"], r["src_kind"]) if split else (r["type"],)] += 1
    return found


def _structure_problems(nodes: Rows, edges: Rows, snap: Snapshot) -> list[str]:
    found = _found_counts(nodes, edges)
    return [f"{' from '.join(key)}: {found[key]} rows, the layers hold {want}"
            for key, want in _expected_counts(snap).items() if found[key] != want]


def _expected_mentions(snap: Snapshot) -> int:
    names = {key for n in snap.of("names") for key in (n.norm_key, *n.surfaces)}
    groups: dict[str, list[str]] = defaultdict(list)
    single = 0
    for span in snap.of("name_spans"):
        if span.region != "body":
            continue
        if span.merge_group:
            groups[span.merge_group].append(span.surface)
        elif span.norm_key in names:
            single += 1
    return single + sum(1 for parts in groups.values() if "".join(parts) in names)


def _mention_problems(edges: Rows, snap: Snapshot) -> list[str]:
    totals: Counter[str] = Counter()
    for r in edges:
        if r["type"] == "MENTIONS":
            totals[r["src_kind"]] += r["props"]["count"]
    want = _expected_mentions(snap)
    return [f"MENTIONS from {kind}: {totals[kind]} mentions, the text layer holds {want}"
            for kind in ("Verse", "Passage") if totals[kind] != want]


def _end_written(person: Row, units: Sequence[str], verses: Mapping[str, str]) -> bool:
    return any(s in verses.get(u, "") for s in person["props"]["surfaces"] for u in units)


def _kin_edge_problems(r: Row, persons: Mapping[str, Row], verses: Mapping[str, str]) -> list[str]:
    props, kind = r["props"], r["type"]
    label = f"{kind} {r['src']}->{r['dst']}"
    out = []
    if props.get("provenance_class") not in PDF_CLASSES:
        out.append(f"{label}: provenance_class {props.get('provenance_class')!r} is not from the PDF")
    if props.get("role") not in (PARENT_ROLES if kind == PARENT else {NO_ROLE}):
        out.append(f"{label}: role {props.get('role')!r}")
    if kind != PARENT and r["src"] >= r["dst"]:
        out.append(f"{label}: {kind} runs from the smaller id")
    units = props.get("evidence_units") or []
    out += [f"{label}: evidence {u} is not a verse" for u in units if u not in verses]
    for node_id in (r["src"], r["dst"]):
        person = persons.get(node_id)
        if person is not None and not _end_written(person, units, verses):
            out.append(f"{label}: {person['props']['label']} is not written in {list(units)}")
    return out


def _kin_problems(nodes: Rows, edges: Rows, snap: Snapshot) -> list[str]:
    persons = {r["id"]: r for r in nodes if r["kind"] == "Person"}
    verses = {v.unit_key: v.text for v in snap.of("verse_units")}
    kin = [r for r in edges if r["type"] in KIN_TYPES]
    out = [problem for r in kin for problem in _kin_edge_problems(r, persons, verses)]
    twice = Counter((r["type"], r["src"], r["dst"]) for r in kin)
    return out + [f"{key[0]} {key[1]}->{key[2]} appears twice" for key, n in twice.items() if n > 1]


def _cycle(children: Mapping[str, Sequence[str]]) -> list[str] | None:
    """A cycle as its node ids, or None; iterative, in sorted order."""
    done: set[str] = set()
    for root in sorted(children):
        if root in done:
            continue
        path, on_path, stack = [], set(), [(root, iter(sorted(children[root])))]
        path.append(root)
        on_path.add(root)
        while stack:
            node, rest = stack[-1]
            child = next(rest, None)
            if child is None:
                stack.pop()
                path.pop()
                on_path.discard(node)
                done.add(node)
            elif child in on_path:
                return [*path[path.index(child):], child]
            elif child not in done:
                path.append(child)
                on_path.add(child)
                stack.append((child, iter(sorted(children.get(child, ())))))
    return None


def _cycle_problems(edges: Rows) -> list[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for r in edges:
        if r["type"] == PARENT:
            children[r["src"]].append(r["dst"])
    found = _cycle(children)
    return [] if found is None else [f"PARENT_OF cycle: {' -> '.join(found)}"]


def _meta_problems(nodes: Rows, edges: Rows, meta: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(meta, Mapping):
        return ["kg_meta.json is not a document"]
    want = meta_doc(nodes, edges)
    return [f"kg_meta.json {key} disagrees with the rows" for key in META_KEYS if meta.get(key) != want[key]]


def check_graph(nodes: Rows, edges: Rows, meta: Mapping[str, Any] | None, snap: Snapshot) -> GateResult:
    """``nodes``, ``edges``: the two row files; ``snap``: the records of the four layers under it."""
    known = {(r["kind"], r["id"]) for r in nodes}
    violations = [*(["the graph holds no nodes"] if not nodes else []),
                  *_node_problems(nodes), *_edge_problems(edges, known),
                  *_structure_problems(nodes, edges, snap), *_mention_problems(edges, snap),
                  *_kin_problems(nodes, edges, snap), *_cycle_problems(edges),
                  *_meta_problems(nodes, edges, meta)]
    return violations_result(NAME, violations)

"""The graph layer's schema and file format: node kinds, edge types and their ends, row order, meta.

A node row is ``{kind, id, props}``, where ``id`` is unique within its kind. An edge row is
``{type, src_kind, src, dst_kind, dst, props}``. Rows are sorted by the schema's order and then by
their ids, and encoded as canonical JSONL, so the same input gives the same bytes. No verse text
is stored: that stays in the text layer and PG.
"""

from __future__ import annotations

import json
from collections import Counter
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ragdata.store.cas import sha256_bytes
from ragdata.store.jsonl import encode_jsonl

SCHEMA_VERSION = "ragdata.kg.v1"
PDF_RULE = "pdf_rule"
PDF_CLASSES = frozenset({"pdf_deterministic", PDF_RULE})
NODE_KINDS = ("Book", "Chapter", "Pericope", "Passage", "Verse", "Name", "Person", "Event")
PARENT, SPOUSE, SIBLING = "PARENT_OF", "SPOUSE_OF", "SIBLING_OF"
KIN_TYPES = (PARENT, SPOUSE, SIBLING)
EDGE_ENDS: Mapping[str, tuple[tuple[str, str], ...]] = MappingProxyType({
    "HAS_CHAPTER": (("Book", "Chapter"),),
    "HAS_PASSAGE": (("Chapter", "Passage"), ("Pericope", "Passage")),
    "HAS_VERSE": (("Passage", "Verse"),),
    "NEXT": (("Pericope", "Pericope"), ("Passage", "Passage")),
    "MENTIONS": (("Verse", "Name"), ("Passage", "Name")),
    "TITLE_MENTIONS": (("Pericope", "Name"),),
    "PARALLEL": (("Pericope", "Pericope"),),
    "ANCHORED_AT": (("Event", "Pericope"),),
    "NAMED": (("Person", "Name"),),
    **{kin: (("Person", "Person"),) for kin in KIN_TYPES},
})
EDGE_TYPES = tuple(EDGE_ENDS)
# what tells two edges of one type between one pair apart: two parallel records between two pericopes
EDGE_KEY_PROPS: Mapping[str, tuple[str, ...]] = MappingProxyType({"PARALLEL": ("pr_id",)})
# the properties a row may hold as null; a graph database stores no null, so a projection reads
# these back as absent
NULLABLE_PROPS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "Pericope": ("section_title", "title"),
    "Passage": ("title",),
})
META_KEYS = ("schema_version", "counts", "nodes_sha256", "edges_sha256")


def node(kind: str, node_id: str, **props: Any) -> dict[str, Any]:
    return {"kind": kind, "id": node_id, "props": props}


def edge(edge_type: str, src_kind: str, src: str, dst_kind: str, dst: str, **props: Any) -> dict[str, Any]:
    return {"type": edge_type, "src_kind": src_kind, "src": src, "dst_kind": dst_kind, "dst": dst,
            "props": props}


def sorted_nodes(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda r: (NODE_KINDS.index(r["kind"]), r["id"]))


def _edge_key(row: Mapping[str, Any]) -> tuple:
    return (EDGE_TYPES.index(row["type"]), row["src_kind"], row["src"], row["dst_kind"], row["dst"],
            json.dumps(row["props"], ensure_ascii=False, sort_keys=True))


def sorted_edges(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=_edge_key)


def meta_doc(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``kg_meta.json``: the schema version, the counts and the sha256 of the two row files."""
    return {"schema_version": SCHEMA_VERSION,
            "counts": {"nodes": dict(sorted(Counter(r["kind"] for r in nodes).items())),
                       "edges": dict(sorted(Counter(r["type"] for r in edges).items()))},
            "nodes_sha256": sha256_bytes(encode_jsonl(nodes)),
            "edges_sha256": sha256_bytes(encode_jsonl(edges))}

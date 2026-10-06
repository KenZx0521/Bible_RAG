"""The in-memory KG the gate scores, built identically from a kg_snapshot/v1
directory or from a read-only projection of live Neo4j.

Both sources produce the same KG object, so a snapshot scores exactly what the
graph loaded from it would; write_snapshot() dumps a live graph in snapshot
format, which is how that parity is tested. The format is documented in
scripts/validate_kg.py.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from check_identity import TYPE_LABELS, read_query

SNAPSHOT_FORMAT = "kg_snapshot/v1"
# Every file is required. A missing file used to load as an empty set, which
# scored as a sweeping improvement (R1 -> 0 without books.jsonl) and could be
# ratcheted into the baseline shared with live runs.
SNAPSHOT_FILES = ("manifest.json", "entities.jsonl", "mentions.jsonl", "relations.jsonl",
                  "cross_references.jsonl", "pericopes.jsonl", "chunks.jsonl", "books.jsonl")
# --allow-partial may skip the others, never the entity layer every check reads.
ALWAYS_REQUIRED = ("entities.jsonl",)
# manifest mentions_granularity: "occurrence" = every mention row (a compiled
# snapshot); "edge" = one row per MENTIONS edge, what live Neo4j holds and so
# what --dump-snapshot writes. An edge snapshot scores like live: the readings
# that need every occurrence (R3 all-forms, R9) are n/a instead of measuring
# edge rows under an occurrence metric's name and baseline.
GRANULARITIES = ("occurrence", "edge")

PPG = {"Person", "Place", "Group"}
CURATED_XREF_SOURCES = {"markdown", "supplementary"}


class SnapshotError(ValueError):
    """A snapshot directory that cannot be scored as given."""


class XRef(NamedTuple):
    src: str
    tgt: str
    source: str | None
    votes: int | None
    curated: bool | None
    tsk: bool | None
    source_verses: str | None    # legacy scalars: graphs built before 1B (prod until W1)
    target_verses: str | None
    curated_sources: list[str] | None  # 1B: one row per pair, provenance as lists
    supp_anchors: list[str] | None     # 'heb 1:5>psa 2:7'
    md_anchors: list[str] | None       # 'mrk 1:?>psa 2:7' (markdown refs are pericope-level)


def is_curated_xref(x: XRef) -> bool:
    return bool(x.curated) if x.curated is not None else x.source in CURATED_XREF_SOURCES


def has_tsk_evidence(x: XRef) -> bool:
    # After 1B a curated edge can also carry TSK votes (tsk=true), so TSK-ness
    # is not "not curated".
    return bool(x.tsk) if x.tsk is not None else x.votes is not None


@dataclass
class KG:
    mode: str                                            # "live" | "snapshot"
    entity_rows: list[dict] = field(default_factory=list)  # every node row; duplicates kept for H1
    mentions: list[dict] = field(default_factory=list)     # one per MENTIONS edge
    mention_rows: list[dict] | None = None                 # occurrence rows (R3, R9); None = edges only
    relations: list[dict] = field(default_factory=list)
    xrefs: list[XRef] = field(default_factory=list)
    pericopes: dict[str, dict] = field(default_factory=dict)
    chunk_parent: dict[str, str] = field(default_factory=dict)
    books: dict[str, str] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    origin: str = ""
    missing: tuple[str, ...] = ()                          # snapshot files absent (--allow-partial)

    @cached_property
    def entities(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in self.entity_rows:
            out.setdefault(row["entity_id"], row)
        return out

    def label(self, entity_id: str) -> str | None:
        row = self.entities.get(entity_id)
        return row["labels"][0] if row and len(row["labels"]) == 1 else None

    def pericope_of(self, mention: dict) -> str | None:
        if mention["source_label"] == "Chunk":
            return self.chunk_parent.get(mention["source_id"])
        return mention["source_id"]

    @cached_property
    def anchors(self) -> dict[str, set[str]]:
        """entity_id -> pericopes mentioning it directly or through one of their chunks."""
        out: dict[str, set[str]] = defaultdict(set)
        for m in self.mentions:
            pid = self.pericope_of(m)
            if pid:
                out[m["entity_id"]].add(pid)
        return out

    @cached_property
    def mention_keys(self) -> set[tuple[str, str, str]]:
        return {(m["source_label"], m["source_id"], m["entity_id"]) for m in self.mentions}

    @cached_property
    def relation_keys(self) -> set[tuple[str, str, str]]:
        return {(r["head"], r["type"], r["tail"]) for r in self.relations}

    @cached_property
    def chunks_of(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for chunk, parent in self.chunk_parent.items():
            out[parent].append(chunk)
        return out

    @cached_property
    def book_region_edges(self) -> list[dict]:
        """MENTIONS edges whose (first) position lies inside the leading book name."""
        out = []
        for m in self.mentions:
            book = self.books.get(m["source_id"].split(":")[0])
            if m["start_pos"] is not None and book and m["start_pos"] < len(book):
                out.append(m)
        return out


def read_jsonl(path: Path, optional: bool = False) -> list[dict]:
    if optional and not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _entity_row(r: dict, is_entity: bool = True) -> dict:
    labels = r.get("labels") or ([r["type"]] if r.get("type") else [])
    return {
        "entity_id": r["entity_id"],
        "labels": sorted(label for label in labels if label in TYPE_LABELS),
        "is_entity": r.get("is_entity", is_entity),
        "canonical_name": r.get("canonical_name"),
        "aliases": r.get("aliases"),
        "description": r.get("description"),
    }


def _mention_row(r: dict) -> dict:
    if "source_label" in r:
        label, sid, text_id = r["source_label"], r["source_id"], r.get("text_id")
    else:  # legacy output/entity_mentions.jsonl row, mapped as import_neo4j does
        raw, kind = r["source_id"], r.get("source_type")
        if kind == "chunk":
            label, sid = "Chunk", raw
        else:
            label, sid = "Pericope", raw.split(":v:")[0]
        text_id = raw
    return {
        "source_label": label, "source_id": sid, "entity_id": r["entity_id"],
        "text_span": r.get("text_span"), "start_pos": r.get("start_pos"), "end_pos": r.get("end_pos"),
        "source_region": r.get("source_region"), "source": r.get("source"), "curated": r.get("curated"),
        "text_id": text_id,
    }


def _collapse(rows: list[dict]) -> list[dict]:
    edges: dict[tuple, dict] = {}
    for row in rows:
        edges.setdefault((row["source_label"], row["source_id"], row["entity_id"]), row)
    return list(edges.values())


def _relation_row(r: dict) -> dict:
    return {
        "head": r["head_id"], "type": r.get("relation") or r["type"], "tail": r["tail_id"],
        "source_pericope_id": r.get("source_pericope_id") or "",
        "extraction_phase": r.get("extraction_phase"), "notes": r.get("notes") or "",
        "curated": r.get("curated"), "backfilled": r.get("backfilled"), "source": r.get("source"),
        "direction_verified": r.get("direction_verified"), "sources": r.get("sources"),
    }


def _xref(r: dict) -> XRef:
    return XRef(r["source_id"], r["target_id"], r.get("source"), r.get("votes"), r.get("curated"),
                r.get("tsk"), r.get("source_verses"), r.get("target_verses"),
                r.get("curated_sources"), r.get("supp_anchors"), r.get("md_anchors"))


def _pericope_row(r: dict) -> dict:
    meta = r.get("metadata") or {}  # also accepts output/pericopes.jsonl rows
    return {"book_id": r.get("book_id") or meta.get("book_id"),
            "verse_range": r.get("verse_range") or meta.get("verse_range")}


def load_snapshot(path: Path, allow_partial: bool = False) -> KG:
    """Read a kg_snapshot/v1 directory. A missing file is a SnapshotError unless
    `allow_partial`; the KG then records it in `missing`, and the checks that
    need it report n/a instead of scoring an empty set."""
    path = Path(path)
    missing = tuple(name for name in SNAPSHOT_FILES if not (path / name).is_file())
    blocking = [name for name in missing if name in ALWAYS_REQUIRED or not allow_partial]
    if blocking:
        hint = "" if allow_partial else \
            " (--allow-partial scores the rest: checks needing them are n/a and --ratchet is refused)"
        raise SnapshotError(f"snapshot {path} lacks {blocking}{hint}")
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if manifest.get("format", SNAPSHOT_FORMAT) != SNAPSHOT_FORMAT:
        raise SnapshotError(f"{manifest_path}: unsupported snapshot format {manifest.get('format')!r}")
    granularity = manifest.get("mentions_granularity")
    if granularity not in (None, *GRANULARITIES):
        raise SnapshotError(f"{manifest_path}: mentions_granularity must be one of {GRANULARITIES}")
    # The marker decides; dumps written before it existed are recognised by load_live's origin.
    per_edge = granularity == "edge" if granularity else str(manifest.get("origin", "")).startswith("live")
    rows = [_mention_row(r) for r in read_jsonl(path / "mentions.jsonl", optional=True)]
    return KG(
        mode="snapshot",
        entity_rows=[_entity_row(r) for r in read_jsonl(path / "entities.jsonl")],
        mentions=_collapse(rows),
        mention_rows=None if per_edge else rows,
        relations=[_relation_row(r) for r in read_jsonl(path / "relations.jsonl", optional=True)],
        xrefs=[_xref(r) for r in read_jsonl(path / "cross_references.jsonl", optional=True)],
        pericopes={r["id"]: _pericope_row(r) for r in read_jsonl(path / "pericopes.jsonl", optional=True)},
        chunk_parent={r["id"]: r.get("pericope_id") or r.get("parent_id")
                      for r in read_jsonl(path / "chunks.jsonl", optional=True)},
        books={r["id"]: r["name"] for r in read_jsonl(path / "books.jsonl", optional=True)},
        manifest=manifest,
        origin=f"snapshot:{path}",
        missing=missing,
    )


# Label-scoped reads only: no query joins two unbound patterns, and the 250k
# CROSS_REFERENCES are streamed once as plain columns (no verse_pairs payload).
_LIVE_QUERIES = {
    "entities": """
        MATCH (n) WHERE n:Entity OR n:Person OR n:Place OR n:Group OR n:Event OR n:Object OR n:Theme
        RETURN n.entity_id AS entity_id, labels(n) AS labels, n.canonical_name AS canonical_name,
               n.aliases AS aliases, n.description AS description""",
    "mentions": """
        MATCH (s)-[m:MENTIONS]->(e:Entity)
        RETURN CASE WHEN s:Chunk THEN 'Chunk' WHEN s:Pericope THEN 'Pericope' ELSE head(labels(s)) END
                   AS source_label,
               coalesce(s.id, s.entity_id) AS source_id, e.entity_id AS entity_id,
               m.text_span AS text_span, m.start_pos AS start_pos, m.end_pos AS end_pos,
               m.source_region AS source_region, m.source AS source, m.curated AS curated""",
    "relations": """
        MATCH (a:Entity)-[r]->(b:Entity) WHERE NOT type(r) IN ['MENTIONS', 'CROSS_REFERENCES']
        RETURN a.entity_id AS head_id, type(r) AS relation, b.entity_id AS tail_id,
               r.source_pericope_id AS source_pericope_id, r.extraction_phase AS extraction_phase,
               r.notes AS notes, r.curated AS curated, r.backfilled AS backfilled, r.source AS source,
               r.direction_verified AS direction_verified, r.sources AS sources""",
    "xrefs": """
        MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
        RETURN a.id AS source_id, b.id AS target_id, r.source AS source, r.votes AS votes,
               r.curated AS curated, r.tsk AS tsk, r.source_verses AS source_verses,
               r.target_verses AS target_verses, r.curated_sources AS curated_sources,
               r.supp_anchors AS supp_anchors, r.md_anchors AS md_anchors""",
    "pericopes": "MATCH (p:Pericope) RETURN p.id AS id, p.book_id AS book_id, p.verse_range AS verse_range",
    "chunks": "MATCH (c:Chunk) RETURN c.id AS id, c.pericope_id AS pericope_id",
    "books": "MATCH (b:Book) RETURN b.id AS id, b.name AS name",
    "constraints": "SHOW CONSTRAINTS YIELD type, labelsOrTypes, properties RETURN type, labelsOrTypes, properties",
}


def load_live(driver, origin: str = "live") -> KG:
    q = {name: read_query(driver, cypher) for name, cypher in _LIVE_QUERIES.items()}
    constraints = [
        {"label": c["labelsOrTypes"][0], "property": c["properties"][0], "type": c["type"]}
        for c in q["constraints"]
        if len(c["labelsOrTypes"] or []) == 1 and len(c["properties"] or []) == 1
    ]
    return KG(
        mode="live",
        entity_rows=[_entity_row(r, is_entity="Entity" in r["labels"]) for r in q["entities"]],
        mentions=[_mention_row({**r, "text_id": None}) for r in q["mentions"]],
        relations=[_relation_row(r) for r in q["relations"]],
        xrefs=[_xref(r) for r in q["xrefs"]],
        pericopes={r["id"]: _pericope_row(r) for r in q["pericopes"]},
        chunk_parent={r["id"]: r["pericope_id"] for r in q["chunks"]},
        books={r["id"]: r["name"] for r in q["books"]},
        manifest={"format": SNAPSHOT_FORMAT, "constraints": constraints, "origin": origin},
        origin=origin,
    )


def write_snapshot(kg: KG, path: Path) -> None:
    """Write `kg` as a kg_snapshot/v1 directory (refuses to overwrite one)."""
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"{path} is not empty; refusing to overwrite a snapshot")
    path.mkdir(parents=True, exist_ok=True)

    def dump(name: str, rows) -> None:
        with open(path / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    granularity = "edge" if kg.mention_rows is None else "occurrence"
    (path / "manifest.json").write_text(
        json.dumps({**kg.manifest, "format": SNAPSHOT_FORMAT, "mentions_granularity": granularity},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    dump("entities.jsonl", kg.entity_rows)
    dump("mentions.jsonl", kg.mention_rows if kg.mention_rows is not None else kg.mentions)
    dump("relations.jsonl", ({"head_id": r["head"], "relation": r["type"], "tail_id": r["tail"],
                              **{k: v for k, v in r.items() if k not in ("head", "type", "tail")}}
                             for r in kg.relations))
    dump("cross_references.jsonl", ({"source_id": x.src, "target_id": x.tgt,
                                     **{k: v for k, v in x._asdict().items() if k not in ("src", "tgt")}}
                                    for x in kg.xrefs))
    dump("pericopes.jsonl", ({"id": pid, **row} for pid, row in kg.pericopes.items()))
    dump("chunks.jsonl", ({"id": cid, "pericope_id": pid} for cid, pid in kg.chunk_parent.items()))
    dump("books.jsonl", ({"id": bid, "name": name} for bid, name in kg.books.items()))

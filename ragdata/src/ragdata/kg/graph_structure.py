"""The graph's structure rows: books to verses, reading order, parallels and event anchors.

They come straight from the text, struct, kg0 and events layers, so G-GRAPH can hold every count
to those layers.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ragcommon import ids
from ragdata.kg.graph_schema import edge, node

Row = Mapping[str, Any]


def book_rows(books: Iterable[Row], chapters: Iterable[Row]) -> tuple[list[dict], list[dict]]:
    nodes = [node("Book", b["book_id"], name=b["name"], testament=b["testament"], ord=b["ord"])
             for b in books]
    edges = []
    for c in chapters:
        nodes.append(node("Chapter", c["chapter_key"], book_id=c["book_id"], num=c["chapter"]))
        edges.append(edge("HAS_CHAPTER", "Book", c["book_id"], "Chapter", c["chapter_key"]))
    return nodes, edges


def verse_nodes(verse_units: Iterable[Row]) -> list[dict]:
    return [node("Verse", v["unit_key"], book_id=v["book_id"], chapter=v["chapter"], ord=v["ord"])
            for v in verse_units]


def _section_title(pericope: Row, headings: Mapping[str, Row]) -> str | None:
    heading = pericope["section_heading_id"]
    return None if heading is None else headings[heading]["display_title"]


def pericope_rows(pericopes: Sequence[Row], headings: Iterable[Row]) -> tuple[list[dict], list[dict]]:
    """Pericope nodes and their NEXT (``next_id`` stays inside a book)."""
    by_heading = {h["heading_id"]: h for h in headings}
    nodes = [node("Pericope", p["pericope_id"], title=p["title"],
                  section_title=_section_title(p, by_heading), book_id=p["book_id"],
                  start_slot=p["start_slot"], end_slot=p["end_slot"]) for p in pericopes]
    edges = [edge("NEXT", "Pericope", p["pericope_id"], "Pericope", p["next_id"])
             for p in pericopes if p["next_id"]]
    return nodes, edges


def _passage_row(p: Row) -> tuple[dict, list[dict]]:
    chapter = ids.parse(p["chapter_key"])
    passage = p["passage_id"]
    row = node("Passage", passage, pericope_id=p["pericope_id"], book_id=chapter.book_id,
               chapter=chapter.chapter, title=p["title"], start_key=p["start_key"],
               end_key=p["end_key"])
    links = [edge("HAS_PASSAGE", "Chapter", p["chapter_key"], "Passage", passage),
             edge("HAS_PASSAGE", "Pericope", p["pericope_id"], "Passage", passage),
             *(edge("HAS_VERSE", "Passage", passage, "Verse", ref["unit_key"]) for ref in p["unit_refs"])]
    return row, links


def passage_rows(passages: Sequence[Row]) -> tuple[list[dict], list[dict]]:
    """Passage nodes, what holds them, the verses they hold (a verse a heading cuts has two
    passages) and NEXT between neighbours of a book."""
    nodes, edges = [], []
    for p in passages:
        row, links = _passage_row(p)
        nodes.append(row)
        edges += links
    for before, after in zip(nodes, nodes[1:]):
        if before["props"]["book_id"] == after["props"]["book_id"]:
            edges.append(edge("NEXT", "Passage", before["id"], "Passage", after["id"]))
    return nodes, edges


def parallel_edges(links: Iterable[Row]) -> list[dict]:
    return [edge("PARALLEL", "Pericope", r["from_pericope"], "Pericope", r["to_pericope"],
                 pr_id=r["pr_id"]) for r in links]


def event_rows(events: Iterable[Row]) -> tuple[list[dict], list[dict]]:
    """Event nodes and one ANCHORED_AT per pericope its anchors name."""
    nodes, edges = [], []
    for e in events:
        nodes.append(node("Event", e["event_id"], name=e["name"]))
        edges += [edge("ANCHORED_AT", "Event", e["event_id"], "Pericope", pericope)
                  for pericope in sorted({a["pericope_id"] for a in e["anchors"]})]
    return nodes, edges

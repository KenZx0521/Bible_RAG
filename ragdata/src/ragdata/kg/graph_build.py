"""Build the graph layer (the knowledge graph) and store it if G-GRAPH passes.

Input: the text, struct, kg0 and events layers and ``config/registries/person_aliases.yaml``; only
what the PDFs say (no external dataset, no pronoun resolved, no LLM). The regnal homonyms (a name
two kingdoms' kings share) and each king's verses are compiled here from the text layer with
``regnal_files``, so the layer does not depend on relations.

The layer holds ``kg_nodes.jsonl``, ``kg_edges.jsonl`` (``graph_schema``), ``kg_meta.json`` (the
contract file) and ``graph_report.json``. It holds no verse text, and neither file is a record
type: nothing of the graph goes to PG.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ragcommon.regnal import KINGDOM_NAMES
from ragdata import paths
from ragdata.contract.registry import GRAPH_REPORT, KG_EDGES, KG_META, KG_NODES, REGNAL_LAYER
from ragdata.gates.base import GateResult, Snapshot
from ragdata.gates.graph import check_graph
from ragdata.gates.runner import merge_files
from ragdata.gates.schema import check_schema
from ragdata.kg import graph_names, graph_structure, person_aliases
from ragdata.kg.graph_schema import meta_doc, sorted_edges, sorted_nodes
from ragdata.kg.kin_extract import KinRow, extract
from ragdata.kg.kin_tokens import Corpus, corpus
from ragdata.kg.layers import encode_json, load_built_on, load_inputs, with_records
from ragdata.kg.person_aliases import Aliases
from ragdata.kg.person_graph import Person, person_rows, persons_and_edges
from ragdata.kg.person_identity import Context, Pericopes, identify
from ragdata.kg.person_signs import Kings
from ragdata.kg.regnal_build import regnal_files
from ragdata.kg.registries import RegistryError
from ragdata.stages.errors import StageError
from ragdata.stages.result import BuildResult, Clock, gates_pass
from ragdata.store import LayerData, StoredLayer, encode_jsonl, write_layer

Layers = Mapping[str, LayerData]
REPORT_SCHEMA = "ragdata.graph_report.v1"
TEXT, STRUCT, KG0, EVENTS = "text", "struct", "kg0", "events"


def _names_of(king: Mapping[str, Any]) -> tuple[str, ...]:
    return (king["name"], *(king.get("aliases") or ()))


def _only(table: Mapping[tuple[str, str], set[str]]) -> dict[tuple[str, str], str]:
    return {key: next(iter(found)) for key, found in table.items() if len(found) == 1}


def kings(text: LayerData) -> Kings:
    """The regnal table, for the identity (``person_signs.Kings``); 'U', Solomon, is on no chain."""
    nodes = json.loads(regnal_files(text)[REGNAL_LAYER])["nodes"]
    in_kingdom = {(name, king["kingdom"]) for king in nodes for name in _names_of(king)}
    kingdoms: dict[str, set[str]] = defaultdict(set)
    titles: dict[tuple[str, str], set[str]] = defaultdict(set)
    sons: dict[tuple[str, str], set[str]] = defaultdict(set)
    fathers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for king in nodes:
        title = f"{KINGDOM_NAMES[king['kingdom']]}王" if king["kingdom"] in KINGDOM_NAMES else None
        father = (king["fields"].get("father") or (None,))[0]
        for name in _names_of(king):
            kingdoms[name].add(king["kingdom"])
            for unit in king["evidence"] if title else ():
                titles[(name, unit)].add(title)
            if title and father:
                sons[(name, father)].add(title)
            if title and father and (father, king["kingdom"]) in in_kingdom:
                fathers[(father, name)].add(title)
    return Kings(frozenset(name for name, found in kingdoms.items() if len(found) >= 2),
                 _only(titles), _only(sons), _only(fathers))


def _pericopes(layers: Layers) -> Pericopes:
    of_unit = {r["unit_key"]: r["pericope_id"] for r in layers[STRUCT].rows["verse_index.jsonl"]}
    parallels: dict[str, set[str]] = defaultdict(set)
    for link in layers[KG0].rows["parallel_links.jsonl"]:
        parallels[link["from_pericope"]].add(link["to_pericope"])
        parallels[link["to_pericope"]].add(link["from_pericope"])
    return Pericopes(of_unit, Counter(of_unit.values()),
                     {r["pericope_id"]: r["next_id"] for r in layers[STRUCT].rows["pericopes.jsonl"]},
                     {p: tuple(sorted(others)) for p, others in parallels.items()})


def _check_aliases(aliases: Aliases, text: LayerData, c: Corpus) -> None:
    verses = {v.unit_key: v.text for v in c.verses}
    notes = {f["fn_id"]: f for f in text.rows["footnotes.jsonl"]}
    problems = person_aliases.check_evidence(aliases, verses, notes)
    if problems:
        raise RegistryError(f"{person_aliases.NAME}: {problems}")


@dataclass(frozen=True)
class _People:
    rows: tuple[KinRow, ...]
    people: tuple[Person, ...]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    homonyms: frozenset[str]


def _people(layers: Layers, aliases: Aliases, names: Mapping[str, str]) -> _People:
    text = layers[TEXT]
    c = corpus(text.rows["verse_units.jsonl"], text.rows["name_spans.jsonl"],
               layers[KG0].rows["extra_spans.jsonl"])
    _check_aliases(aliases, text, c)
    new_testament = frozenset(b["book_id"] for b in text.rows["books.jsonl"] if b["testament"] == "NT")
    regnal = kings(text)
    ctx = Context(c, _pericopes(layers), new_testament, aliases, regnal)
    rows = extract(c)
    people, edges = persons_and_edges(rows, identify(rows, ctx), ctx)
    nodes, links = person_rows(people, edges, names)
    return _People(rows, people, nodes, links, regnal.homonyms)


def _report(layers: Layers, aliases: Aliases, found: _People, titles: graph_names.TitleMentions,
            names: Mapping[str, str]) -> dict[str, Any]:
    kin, people = found.rows, found.people
    return {
        "schema": REPORT_SCHEMA, "aliases": aliases.version,
        "depends_on": {name: layer.version for name, layer in sorted(layers.items())},
        "kin": {"rows": len(kin),
                "by_rel": dict(sorted(Counter(r.rel for r in kin).items())),
                "by_family": dict(sorted(Counter(r.family for r in kin).items())),
                "by_pattern": dict(sorted(Counter(r.pattern for r in kin).items()))},
        "identity": {"method": "D2", "persons": len(people),
                     "kin_conflict": sorted(p.label for p in people if p.kin_conflict),
                     "surfaces_without_a_name": sorted({s for p in people for s in p.surfaces} - set(names)),
                     "regnal_homonyms": sorted(found.homonyms)},
        "title_mentions": {"unplaced_heading_names": titles.unplaced},
    }


def compute(layers: Layers, aliases: Aliases) -> tuple[list[Mapping], list[Mapping], dict[str, Any]]:
    """The graph's sorted nodes and edges, and its report."""
    text, struct, kg0 = layers[TEXT], layers[STRUCT], layers[KG0]
    names, passages = graph_names.name_ids(kg0.rows["names.jsonl"]), struct.rows["passages.jsonl"]
    counts = graph_names.mention_counts(text.rows["name_spans.jsonl"], passages, names)
    titles = graph_names.title_mentions(kg0.rows["extra_spans.jsonl"], text.rows["name_spans.jsonl"],
                                        struct.rows["pericopes.jsonl"], names)
    found = _people(layers, aliases, names)
    book_nodes, book_edges = graph_structure.book_rows(text.rows["books.jsonl"], text.rows["chapters.jsonl"])
    pericope_nodes, pericope_edges = graph_structure.pericope_rows(struct.rows["pericopes.jsonl"],
                                                                   text.rows["headings.jsonl"])
    passage_nodes, passage_edges = graph_structure.passage_rows(passages)
    event_nodes, event_edges = graph_structure.event_rows(layers[EVENTS].rows["events.jsonl"])
    nodes = [*book_nodes, *pericope_nodes, *passage_nodes,
             *graph_structure.verse_nodes(text.rows["verse_units.jsonl"]),
             *graph_names.name_nodes(kg0.rows["names.jsonl"], counts, len(passages)),
             *found.nodes, *event_nodes]
    edges = [*book_edges, *pericope_edges, *passage_edges, *graph_names.mention_edges(counts),
             *graph_names.title_edges(titles),
             *graph_structure.parallel_edges(kg0.rows["parallel_links.jsonl"]),
             *event_edges, *found.edges]
    return sorted_nodes(nodes), sorted_edges(edges), _report(layers, aliases, found, titles, names)


def load_layers(text_dir: Path, struct_dir: Path, kg0_dir: Path, events_dir: Path,
                ) -> tuple[dict[str, LayerData], Snapshot]:
    """The four input layers, each built on the ones under it, and their records."""
    layers, snap = load_inputs(Path(text_dir), Path(struct_dir))
    bases = (layers[TEXT], layers[STRUCT])
    more = {KG0: load_built_on(Path(kg0_dir), KG0, bases),
            EVENTS: load_built_on(Path(events_dir), EVENTS, bases)}
    schema, own = check_schema(merge_files(list(more.values())), list(more))
    if not schema.passed:
        raise StageError(f"input layers fail G-SCHEMA: {list(schema.details[:3])}")
    return {**layers, **more}, with_records(snap, own)


def _files(nodes: list[Mapping], edges: list[Mapping], meta: Mapping[str, Any],
           report: Mapping[str, Any]) -> dict[str, bytes]:
    return {KG_NODES: encode_jsonl(nodes), KG_EDGES: encode_jsonl(edges),
            KG_META: encode_json(meta), GRAPH_REPORT: encode_json(report)}


def build_graph(text_dir: Path, struct_dir: Path, kg0_dir: Path, events_dir: Path, store_root: Path,
                registries_dir: Path = paths.REGISTRIES) -> BuildResult:
    clock = Clock()
    with clock.lap("graph"):
        layers, snap = load_layers(text_dir, struct_dir, kg0_dir, events_dir)
        nodes, edges, report = compute(layers, person_aliases.load(Path(registries_dir)))
        meta = meta_doc(nodes, edges)
    with clock.lap("gates"):
        gates: list[GateResult] = [check_graph(nodes, edges, meta, snap)]
    stored: dict[str, StoredLayer] = {}
    if gates_pass(gates):
        with clock.lap("store"):
            depends = {name: layer.version for name, layer in layers.items()}
            stored["graph"] = write_layer(store_root, "graph", _files(nodes, edges, meta, report),
                                          depends_on=depends, exist_ok=True)
    return BuildResult(MappingProxyType(stored), tuple(gates), MappingProxyType(clock.laps))

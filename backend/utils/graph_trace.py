"""What one request's graph side did, for the response's ``graph_trace``.

One entry per graph-side operation that ran, whether or not it changed the answer: the event
registry lane and the two cards, which walk an ordered chain. A new graph operation adds its
entry here, so a run can tell a graph walk from a table lookup question by question.

``hops`` is the longest stretch of explicit edges the operation's derivation covered from one
start: a seed's own reach along its chain, the distance between two seeds, the Genesis flood line's
walk from its anchor row. The project counts two or more as a graph operation (D3,
evaluation/experiments/2026-10-18_kg_cards/prereg.md), so an event's anchor, one edge away, stays a
lookup. ``edges`` lists the edges joining the visited nodes, so a distance two seeds' positions give
without visiting what lies between (a regnal gap line) has more hops than edges.
"""

from __future__ import annotations

from typing import Callable, Hashable, Iterable, Mapping, Sequence

from models.response import GraphOp
from serving import context
from utils import gen_card
from utils.gencard import engine as gen_engine
from utils.regnal import engine
from utils.regnal.card import Card as RegnalCard

# a node's (chain, position); None when it is on no chain
Position = Callable[[str], "tuple[Hashable, int] | None"]


def _distance(position: Position, a: str, b: str) -> int | None:
    at_a, at_b = position(a), position(b)
    return abs(at_a[1] - at_b[1]) if at_a and at_b and at_a[0] == at_b[0] else None


def _hops(pairs: Iterable[tuple[str, str]], position: Position) -> int:
    """The longest distance among (start, end) pairs on one chain."""
    return max((d for a, b in pairs if (d := _distance(position, a, b)) is not None), default=0)


def _chain_edges(nodes: Sequence[str], edge_type: Mapping[tuple[str, str], str]) -> list[list[str]]:
    """The edges joining neighbours of ``nodes``, which are in chain order."""
    return [[a, edge_type[(a, b)], b] for a, b in zip(nodes, nodes[1:]) if (a, b) in edge_type]


def _event_registry(stats: Mapping, results: Sequence[dict]) -> GraphOp | None:
    events = stats.get("event_registry_events") or []
    if not events:
        return None
    appended = [r for r in results if r.get("source_strategy") == "event_registry"]
    return GraphOp(op="event_registry", hops=1 if appended else 0, nodes=list(events),
                   edges=[[r["via_event_id"], "anchor", r["id"]] for r in appended],
                   injected="context" if appended else "none", passages=[r["id"] for r in appended])


def _regnal_card(card: RegnalCard) -> GraphOp:
    view = context.active().regnal.view

    def position(node: str) -> tuple[str, int] | None:
        index = view.idx(node)
        return None if index is None else (view.nodes[node]["kingdom"], index)

    nodes = engine.cards(view, list(card.kings))["rows_read"]
    reach = [(x, y) for x in card.kings for y in engine.derive(view, [x])[0]]   # each seed's own rows
    between = [(a, b) for a in card.kings for b in card.kings]
    return GraphOp(op="regnal_card", hops=_hops([*reach, *between], position), nodes=list(nodes),
                   edges=_chain_edges(nodes, view.edge_type), injected="prompt")


def _gen_card(card: gen_card.Card) -> GraphOp:
    layer = context.active().gen

    def position(node: str) -> tuple[int, int]:
        return layer.chapter[node], layer.index[node]

    nodes = sorted({*card.rows, *card.seeds}, key=position)
    edge_type = {(edge[0], edge[1]): edge[2] for edge in layer.gen["edges"]}
    between = [(a, b) for a in card.seeds for b in card.seeds]
    floods = [(gen_engine.gen_anchor(layer.gen, layer.chapter[seeds[0]]), seeds[0])
              for kind, seeds, *_ in card.tags if kind == "flood"]
    return GraphOp(op="gen_card", hops=_hops([*between, *floods], position), nodes=nodes,
                   edges=_chain_edges(nodes, edge_type), injected="prompt")


def of(stats: Mapping, results: Sequence[dict],
       card: RegnalCard | gen_card.Card | None) -> list[GraphOp]:
    """The request's graph operations, retrieval first. ``stats``: ``retrieve_and_rerank``'s;
    ``results``: its passages; ``card``: the card the generator answered with."""
    ops = [_event_registry(stats, results)]
    if isinstance(card, gen_card.Card):
        ops.append(_gen_card(card))
    elif card is not None:
        ops.append(_regnal_card(card))
    return [op for op in ops if op is not None]

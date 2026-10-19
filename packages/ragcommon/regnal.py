"""The regnal layer read as succession chains (design note 2026-10-19, Kay's P5 exception).

The regnal layer is the kings of Israel and Judah from 1 Kings 11:41 on, as the
regnal formulas name them (``ragdata.kg.regnal_formulas``): nodes with their
fields and evidence verses, succession edges, order-fallback edges and accession
synchronisms. ``load`` (but for ``View.alts``) and ``born_under`` are experiment A's
``regnal.load_auto`` and the chain walk under it, unchanged. On relations@a04b67a301dc the
contract file ``regnal_layer.json`` is the experiment-A layer byte for byte
(``reports/kg_cards_20261018/A/layer_auto.json``); the layer fixed on 2026-10-19 is not, and
Solomon is a node of 'U' there, on no chain:

- a node with neither an accession formula nor a reign length is a mention only and
  is left out (a ghost node);
- each kingdom's chain is a depth-first walk over the succession edges plus the
  fallback edges, roots first, children in node order;
- a node's primary synchronism is its first ``acc`` synchronism.

Added after the experiment (S4 guard, 2026-10-19): ``View.alts``, the other book's
accession ages and reign lengths from the layer's conflicts, and ``born_guard``, which
passes a born_under answer only when it is safe to state. Experiment A had no guard.

One reader serves the K-stage gate (G-REGNAL) and the backend's chronology card.
"""

from __future__ import annotations

import collections
import copy
from typing import Any, Mapping

KINGDOMS = ("I", "J")
KINGDOM_NAMES = {"I": "以色列", "J": "猶大"}
LAYER_FILE = "regnal_layer.json"
ALT_FIELDS = ("age", "reign")      # the conflicts born_guard reads
MIN_BORN_MARGIN = 1.0              # years the birth point must keep from either end of the reign
_NO_KING = ("UNKNOWN_REIGN", "BEFORE_CHAIN")


class View:
    """nodes[id] = dict(kingdom, name, aliases, reign, age, mother, mother_desc, father, death,
    has_acc, order, prov{field: verse}, evidence[verse]); alts[(id, field)] = the conflicting
    values of an age or reign the layer kept the first value of (Kings before Chronicles)."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.chain: dict[str, list[str]] = {"I": [], "J": []}
        self.syncs: list[tuple[str, str, int, str, bool]] = []   # (node, other, year, verse, primary)
        self.edge_type: dict[tuple[str, str], str] = {}           # (pred, succ) -> type
        self.alts: dict[tuple[str, str], list[Any]] = {}          # (node, age|reign) -> other values

    def idx(self, x: str) -> int | None:
        k = self.nodes[x]["kingdom"]
        return self.chain[k].index(x) if x in self.chain.get(k, ()) else None

    def succ(self, x: str, k: int = 1) -> str | None:
        kd, i = self.nodes[x]["kingdom"], self.idx(x)
        if i is None:
            return None
        j = i + k
        return self.chain[kd][j] if 0 <= j < len(self.chain[kd]) else None

    def names(self, x: str) -> list[str]:
        n = self.nodes[x]
        return [n["name"]] + [a for a in dict.fromkeys(n["aliases"]) if a != n["name"]]

    def chain_names(self) -> dict[str, list[str]]:
        return {kd: [self.nodes[x]["name"] for x in self.chain[kd]] for kd in KINGDOMS}


def _chain(V: View, real: set[str], edges: list, kd: str) -> list[str]:
    children: dict[str, list[str]] = collections.defaultdict(list)
    for e in edges:
        children[e[0]].append(e[1])
    has_pred = {e[1] for e in edges}
    ids = sorted([i for i in real if V.nodes[i]["kingdom"] == kd], key=lambda i: V.nodes[i]["order"])
    seq: list[str] = []
    seen: set[str] = set()

    def dfs(x: str) -> None:
        if x in seen:
            return
        seen.add(x)
        seq.append(x)
        for c in sorted(children.get(x, []), key=lambda i: V.nodes[i]["order"]):
            if V.nodes[c]["kingdom"] == kd:
                dfs(c)
    for r in [i for i in ids if i not in has_pred]:
        dfs(r)
    for i in ids:
        dfs(i)
    return seq


def load(doc: Mapping[str, Any], use_fallback: bool = True) -> View:
    """The view of a regnal layer document (``json.loads`` of ``regnal_layer.json``)."""
    V = View()
    real: set[str] = set()
    for n in doc["nodes"]:
        f = n["fields"]
        if not (n["has_acc"] or "reign" in f):
            continue
        real.add(n["id"])
        V.nodes[n["id"]] = dict(kingdom=n["kingdom"], name=n["name"], aliases=n["aliases"],
                                reign=f.get("reign", [None])[0], age=f.get("age", [None])[0],
                                mother=f.get("mother", [None])[0], mother_desc=f.get("mother_desc", [None])[0],
                                father=f.get("father", [None])[0], death=f.get("death", [None])[0],
                                has_acc=n["has_acc"], order=n["order"], prov={k: v[1] for k, v in f.items()},
                                evidence=n["evidence"])
    edges = [e for e in doc["edges"] if e[0] in real and e[1] in real]
    if use_fallback:
        edges += [e for e in doc["fallback_edges"] if e[0] in real and e[1] in real]
    for e in edges:
        V.edge_type[(e[0], e[1])] = e[2]
    for kd in KINGDOMS:
        V.chain[kd] = _chain(V, real, edges, kd)
    primary: set[str] = set()
    for (nid, other, year, verse, kind) in doc["syncs"]:
        if nid in real and other in real:
            p = kind == "acc" and nid not in primary
            if p:
                primary.add(nid)
            V.syncs.append((nid, other, year, verse, p))
    for (nid, _name, field, _kept, other) in doc["conflicts"]:
        if nid in real and field in ALT_FIELDS:
            V.alts.setdefault((nid, field), []).append(other[0])
    return V


def born_under(V: View, x: str) -> tuple[tuple[str, Any] | None, list[str]]:
    """Walk back the predecessor chain from x's accession age: ((king, margin years) |
    ('UNKNOWN_REIGN', king) | ('BEFORE_CHAIN', None) | None, the nodes read)."""
    n, read = V.nodes[x], []
    if n["age"] is None or V.idx(x) is None:
        return None, read
    rem, kd = float(n["age"]), n["kingdom"]
    for j in range(V.idx(x) - 1, -1, -1):
        y = V.chain[kd][j]
        read.append(y)
        r = V.nodes[y]["reign"]
        if r is None:
            return ("UNKNOWN_REIGN", y), read
        if rem < r:
            return (y, min(rem, r - rem)), read
        rem -= r
    return ("BEFORE_CHAIN", None), read


def _with(V: View, x: str, field: str, value: Any) -> View:
    """A view like V whose node x has ``field`` = value; V itself is not changed."""
    W = copy.copy(V)
    W.nodes = {**V.nodes, x: {**V.nodes[x], field: value}}
    return W


def born_guard(V: View, x: str) -> str | None:
    """Why born_under's answer for x is not to be stated, or None when it may be (S4 guard).

    - ``'no_king'``: born_under names no king;
    - ``'margin'`` (G1): the birth point lies under MIN_BORN_MARGIN years from an end of
      that king's reign;
    - ``'alt:<node>:<field>'`` (G3): an alternative value of x's age, or of the reign of a
      king the walk read, put in one at a time, names another king or keeps under
      MIN_BORN_MARGIN years.

    Only ``View.alts`` (ages and reigns) is read; the other conflicts are not."""
    bu, walked = born_under(V, x)
    if not bu or bu[0] in _NO_KING:
        return "no_king"
    king, margin = bu
    if margin < MIN_BORN_MARGIN:
        return "margin"
    for node, field in [(x, "age")] + [(w, "reign") for w in walked]:
        for value in V.alts.get((node, field), ()):
            alt, _read = born_under(_with(V, node, field, value), x)
            if not alt or alt[0] != king or alt[1] < MIN_BORN_MARGIN:
                return f"alt:{node}:{field}"
    return None


def acc_sync(V: View, x: str) -> list[tuple[str, int, str]]:
    """x's primary synchronisms as (other king, year, verse)."""
    return [(o, y, v) for (n, o, y, v, p) in V.syncs if n == x and p]


def fmt_reign(r: float | None) -> str:
    if r is None:
        return "?"
    if r >= 1:
        return "%d年" % round(r)
    if r >= 0.07:
        return "%d個月" % round(r * 12)
    return "%d日" % round(r * 365)

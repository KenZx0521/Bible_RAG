"""From kinship rows and identity to Person nodes and kinship edges, and their graph rows.

Every (type, source, target) is one edge and its evidence is merged: the verses of every row
(both ends' verses, when a row runs across verses; those that write both names first, so the first
verse of an edge is the one to cite), the patterns, and the role (M only when all its evidence writes
a mother). SPOUSE_OF and SIBLING_OF run from the smaller id to the larger.

``kin_conflict`` says a person's own rows do not fit one human being: two fathers of different names
(footnote aliases excepted; a name written as a woman's is no father), or written both as a man and as a
woman. The identity refuses such a merge, so what is left comes from one token's own rows.

A person's mentions are the tokens the identity gives them, but a token without a kinship row is
no mention when it is written as a people (以色列人, 猶大地), or when its name mostly is: 以色列 and 猶大
are peoples far more often than the man, and only a kinship row says it is the man. Nor, in the New
Testament's narrative, when something describes it (施洗的約翰, 亞利馬太的約瑟, 抹大拉的馬利亞, 加略人猶大): the
description says which of its many people of that name it is, and only a row can say that it is this one.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ragcommon import ids
from ragdata.kg.graph_schema import PDF_RULE, edge, node
from ragdata.kg.kin_extract import KinRow
from ragdata.kg.kin_rules import PARENT
from ragdata.kg.kin_tokens import Corpus
from ragdata.kg.person_identity import Context, Identity, in_narrative, place_of
from ragdata.kg.person_signs import Mention

ROLE_MOTHER, ROLE_PARENT, ROLE_NONE = "M", "P", "-"
PEOPLE_WORDS = ("人", "地", "支派", "全家", "家", "城", "山", "河", "谷", "省", "境", "國", "眾", "曠野", "平原",
                "營", "子孫", "族", "半支派", "軍")
PEOPLE_MIN_TOKENS = 5
PEOPLE_SHARE = 0.3         # measured: 以法蓮, 猶大 .39 and 以色列 .54; 雅各 .07, 大衛 .03, 摩西 0
DESCRIBED_AFTER = ("的", "人")


@dataclass(frozen=True)
class Person:
    person_id: str
    label: str
    surfaces: tuple[str, ...]
    kin_conflict: bool
    mentions: int
    mention_units: tuple[str, ...]


@dataclass(frozen=True)
class KinEdge:
    rel: str
    src: str
    dst: str
    role: str
    evidence_units: tuple[str, ...]
    patterns: tuple[str, ...]


@dataclass
class _Evidence:
    units: set[str]
    patterns: set[str]
    roles: set[str]
    heads: set[str]        # the names each end is written with
    tails: set[str]


Key = tuple[Mention, str, Mention]


def _merged(rows: Iterable[KinRow], identity: Identity) -> dict[Key, _Evidence]:
    """One entry per (source, type, target) of clusters; undirected types in a canonical order."""
    merged: dict[Key, _Evidence] = {}
    for r in rows:
        a = identity.node_of_mention[(r.head_unit, r.head_index)]
        b = identity.node_of_mention[(r.tail_unit, r.tail_index)]
        if a == b:
            continue
        key = (a, r.rel, b) if r.rel == PARENT or a < b else (b, r.rel, a)
        entry = merged.setdefault(key, _Evidence(set(), set(), set(), set(), set()))
        entry.units |= {r.unit, r.head_unit, r.tail_unit}
        entry.patterns.add(r.pattern)
        entry.roles.add(r.role)
        entry.heads.add(r.head)
        entry.tails.add(r.tail)
    return merged


def _labels(identity: Identity) -> dict[Mention, Counter[str]]:
    counts: dict[Mention, Counter[str]] = defaultdict(Counter)
    for mention, node in identity.node_of_mention.items():
        counts[node][identity.surface[mention]] += 1
    return counts


def _label(counts: Counter[str]) -> str:
    return min(counts, key=lambda name: (-counts[name], name))


def _one_name(names: set[str], same: Mapping[str, frozenset[str]]) -> bool:
    """Are the names one under the aliases, through each other (基甸, 耶路‧巴力, 耶路‧比設)?"""
    seen, stack = set(), list(names)[:1]
    while stack:
        name = stack.pop()
        seen.add(name)
        stack += [other for other in same.get(name, ()) if other in names and other not in seen]
    return seen == names


def _conflicted(merged: Mapping[Key, _Evidence], identity: Identity, counts: Mapping[Mention, Counter[str]],
                labels: Mapping[Mention, str], same: Mapping[str, frozenset[str]]) -> frozenset[Mention]:
    """A person with two fathers of different names, or of both sexes."""
    fathers: dict[Mention, set[str]] = defaultdict(set)
    for (a, rel, b), entry in merged.items():
        if rel == PARENT and entry.roles != {ROLE_MOTHER} and labels[a] not in identity.female:
            fathers[b].update(counts[a])
    two = {node for node, names in fathers.items() if not _one_name(names, same)}
    return frozenset(two | identity.both_sexes)


def people_names(c: Corpus) -> frozenset[str]:
    """Names written as a people or a place at least ``PEOPLE_SHARE`` of the time."""
    total: Counter[str] = Counter()
    placed: Counter[str] = Counter()
    for verse in c.verses:
        for i, token in enumerate(verse.tokens):
            total[token.norm_key] += 1
            placed[token.norm_key] += verse.after(i).startswith(PEOPLE_WORDS)
    return frozenset(name for name, n in total.items()
                     if n >= PEOPLE_MIN_TOKENS and placed[name] / n >= PEOPLE_SHARE)


def _mentions(ctx: Context, identity: Identity, nodes: frozenset[Mention],
              ) -> tuple[dict[Mention, list[str]], dict[Mention, set[str]]]:
    """Every body token that mentions a person: one verse per mention in PDF order, and its names."""
    units: dict[Mention, list[str]] = defaultdict(list)
    names: dict[Mention, set[str]] = defaultdict(set)
    peoples = people_names(ctx.corpus)
    for verse in ctx.corpus.verses:
        place = place_of(ctx, verse)
        for i, token in enumerate(verse.tokens):
            mention = (verse.unit_key, i)
            if mention not in identity.node_of_mention \
                    and (token.norm_key in peoples or verse.after(i).startswith(PEOPLE_WORDS)
                         or (in_narrative(place) and verse.preceding_char(i) in DESCRIBED_AFTER)):
                continue
            node = identity.node_of(mention, token.norm_key, place)
            if node in nodes:
                units[node].append(verse.unit_key)
                names[node].add(token.norm_key)
    return units, names


def _first(node_mentions: Sequence[str], c: Corpus) -> int:
    return min(c.position[u] for u in node_mentions)


def persons_and_edges(rows: Sequence[KinRow], identity: Identity, ctx: Context,
                      ) -> tuple[tuple[Person, ...], tuple[KinEdge, ...]]:
    """The people with at least one kinship edge, numbered in order of first mention."""
    c, same = ctx.corpus, ctx.aliases.same
    merged = _merged(rows, identity)
    nodes = frozenset(n for (a, _, b) in merged for n in (a, b))
    counts = _labels(identity)
    labels = {node: _label(counts[node]) for node in nodes}
    conflicted = _conflicted(merged, identity, counts, labels, same)
    found, names = _mentions(ctx, identity, nodes)
    ordered = sorted(nodes, key=lambda n: (_first(found[n], c), repr(n)))
    number = {node: ids.entity_id(i) for i, node in enumerate(ordered, start=1)}
    people = tuple(Person(number[n], labels[n], tuple(sorted(names[n])), n in conflicted,
                          len(found[n]), tuple(dict.fromkeys(found[n]))) for n in ordered)
    edges = [_edge(key, entry, number, c) for key, entry in merged.items()]
    return people, tuple(sorted(edges, key=lambda e: (e.rel, e.src, e.dst)))


def _writes_both(entry: _Evidence, text: str) -> bool:
    return any(name in text for name in entry.heads) and any(name in text for name in entry.tails)


def _edge(key: Key, entry: _Evidence, number: Mapping[Mention, str], c: Corpus) -> KinEdge:
    a, rel, b = key
    src, dst = number[a], number[b]
    if rel == PARENT:
        role = ROLE_MOTHER if entry.roles == {ROLE_MOTHER} else ROLE_PARENT
    else:
        src, dst, role = min(src, dst), max(src, dst), ROLE_NONE
    units = tuple(sorted(entry.units, key=lambda u: (not _writes_both(entry, c.verse(u).text), c.position[u])))
    return KinEdge(rel, src, dst, role, units, tuple(sorted(entry.patterns)))


def person_rows(people: Sequence[Person], edges: Sequence[KinEdge], name_ids: Mapping[str, str],
                ) -> tuple[list[dict], list[dict]]:
    """Person nodes; NAMED edges (a surface kg0 has no name for, 耶穌, gets none) and kin edges."""
    nodes = [node("Person", p.person_id, label=p.label, surfaces=list(p.surfaces),
                  kin_conflict=p.kin_conflict, mentions=p.mentions,
                  mention_units=list(p.mention_units)) for p in people]
    named = [edge("NAMED", "Person", p.person_id, "Name", name_ids[surface])
             for p in people for surface in p.surfaces if surface in name_ids]
    kin = [edge(e.rel, "Person", e.src, "Person", e.dst, role=e.role,
                evidence_units=list(e.evidence_units), patterns=list(e.patterns),
                provenance_class=PDF_RULE) for e in edges]
    return nodes, [*named, *kin]

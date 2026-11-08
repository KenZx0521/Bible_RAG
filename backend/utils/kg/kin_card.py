"""The kinship card: what the graph says of how the people a question names are related.

The ends and who they mean: ``utils.kg.kin_people``. Two or more people: the shortest paths between each pair,
and then, from whoever the question asks about, a walk in the direction its cue says (``kin_cues``):
亞伯拉罕的兒子以撒的妻子 is the path from 亞伯拉罕 to 以撒, and 以撒's wife. A question that asked only for the 關係 of two
people has nothing more to say without a path. 同名, or people of one name with different parents that the pool
cannot tell apart: everyone of that name and their parents; such a card brings no passages to the context, since
it does not know whose they would be.

Every row is one edge of the graph with one verse, read as a sentence, and it says no more than the edge
does. The role of a parent edge is M when all its evidence writes a mother and P otherwise, and P is no
father: 拉結 -> 約瑟, 拔示巴 -> 所羅門 and 馬利亞 -> 雅各 are P (one verse writes 的兒子), so P reads 父母之一.
A Person is what the graph could tell apart, not one human being: 大衛 is two of them, one per testament
group, and a name's other people may be the same man, so a card says 筆 and 可能, never 不只一人. A card is not
a full list: only what the rules read (利亞 has rows for two of her sons), and it says so. Nor does SIBLING_OF
tell a brother from a sister: a question asking for one is told. No edge, no card: the prompt is then what it
is without a graph.

The trace (``edges``, ``nodes``, ``evidence``) is what the card shows: the edges of its path lines and of its rows.

Neo4j not answering is a ``skip_reason``, the same as finding nothing.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

from config import settings
from database import neo4j_db
from ragcommon import books, ids
from ragcommon.routing import RoutingLexicon
from utils.kg import kin_cues, kin_people
from utils.kg.kin_cues import CHILD_FIRST, SPOUSE_FIRST, Cue
from utils.kg.kin_people import End, Person, Question

HEADER = "以下親屬關係依經文整理，只列已整理到的，可能不完整；若與經文段落不符，以經文為準。"
SIBLING_NOTE = "（親屬資料不分兄弟或姊妹，性別請依經文判斷。）"
NO_CUE, NO_PERSON, NO_EDGE = "no_cue", "no_person", "no_edge"
PARENT, SPOUSE, SIBLING = "PARENT_OF", "SPOUSE_OF", "SIBLING_OF"
ROLE_MOTHER = "M"
MAX_PAIRS = 3
MAX_WALKERS = 3
_ONE_SEX_OF_SIBLING = re.compile(r"哥|姊姊|姐姐|妹妹|妹子|弟弟|兄長")


@dataclass(frozen=True)
class KinCard:
    """A card (``text``), or why there is none (``skip_reason``); to_stats is what the response carries."""

    text: str | None = None
    seeds: tuple[str, ...] = ()            # the labels of the people asked about
    persons: tuple[str, ...] = ()          # their ids
    nodes: tuple[str, ...] = ()            # everyone the rows name
    names: tuple[str, ...] = ()            # their labels, aligned with nodes
    edges: tuple[tuple[str, ...], ...] = ()   # (from, type, to, verse key)
    hops: int = 0
    lines: int = 0
    evidence: tuple[str, ...] = ()         # the verse keys the rows cite
    passages: tuple[str, ...] = ()         # the passages holding them
    n_cypher: int = 0
    ms: float = 0.0
    skip_reason: str | None = None

    def to_stats(self) -> dict[str, Any]:
        return asdict(self)


def skipped(reason: str) -> KinCard:
    return KinCard(skip_reason=reason)


def from_stats(stats: Mapping[str, Any]) -> KinCard | None:
    """The card a request's stats carry, or None when it has none."""
    found = stats.get("kin_card")
    if not found or not found.get("text"):
        return None
    return KinCard(**{**found, **{k: tuple(found[k]) for k in (
        "seeds", "persons", "nodes", "names", "evidence", "passages")},
        "edges": tuple(tuple(e) for e in found["edges"])})


@dataclass(frozen=True)
class _Edge:
    src: str
    kind: str
    dst: str
    role: str
    unit: str


@dataclass(frozen=True)
class _Path:
    nodes: tuple[tuple[str, str], ...]
    edges: tuple[_Edge, ...]


class _Row(NamedTuple):
    """A line of the card, the verse it cites, the edges it shows."""
    text: str
    unit: str | None = None
    edges: tuple[_Edge, ...] = ()


@dataclass
class _Found:
    """What a walk found and the card will say."""

    notes: list[str] = field(default_factory=list)
    paths: list[_Path] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    asked: list[_Edge] = field(default_factory=list)     # what the cue walked to, shown first
    edges: list[_Edge] = field(default_factory=list)     # the steps of the paths
    rows: list[_Row] = field(default_factory=list)       # a same-name list
    hops: int = 0

    @property
    def anything(self) -> bool:
        return bool(self.asked or self.edges)


# --- saying it ------------------------------------------------------------------------------------

def verse_ref(unit: str) -> str:
    """創世記 21:3, 歷代志上 16:12-13."""
    parsed = ids.parse(unit)
    verses = f"{parsed.verse}-{parsed.verse_end}" if parsed.verse_end else str(parsed.verse)
    return f"{books.get_book(parsed.book_id).name} {parsed.chapter}:{verses}"


def _relation(edge: _Edge, labels: Mapping[str, str]) -> str:
    a, b = labels[edge.src], labels[edge.dst]
    if edge.kind == SPOUSE:
        return f"{a} 與 {b} 是配偶"
    if edge.kind == SIBLING:
        return f"{a} 與 {b} 是兄弟姊妹"
    return f"{a} 是 {b} 的{'母親' if edge.role == ROLE_MOTHER else '父母之一'}"


def _step(edge: _Edge, here: str, labels: Mapping[str, str]) -> str:
    """One step of a path read from ``here``."""
    if edge.kind == PARENT and edge.dst == here:
        return f"{labels[here]} 是 {labels[edge.src]} 的子女"
    return _relation(edge, labels)


def _path_line(path: _Path, labels: Mapping[str, str]) -> str:
    here, steps = path.nodes[0][0], []
    for edge in path.edges:
        steps.append(_step(edge, here, labels))
        here = edge.dst if edge.src == here else edge.src
    return f"路徑：{'，'.join(steps)}（共 {len(path.edges)} 跳）"


def _who(person: Person) -> str:
    if person.parents:
        return f"這裡用 {person.parents[0][1]} 的子女那一筆（{verse_ref(person.parents[0][3])}）"
    return f"這裡用 {verse_ref(person.units[0])} 提到的那一筆" if person.units else "這裡用其中一筆"


def _notes(picked: Mapping[str, Person], found_of: Mapping[str, Sequence[Person]]) -> list[str]:
    notes = []
    for surface, person in picked.items():
        if len(found_of[surface]) > 1:
            notes.append(f"「{surface}」在親屬資料中有 {len(found_of[surface])} 筆"
                         f"（可能是同名的不同人，也可能是同一人分列），{_who(person)}。")
        if person.conflict:
            notes.append(f"「{surface}」的資料可能混入同名者。")
    return notes


def _fit(rows: Sequence[_Row]) -> tuple[list[str], list[_Row]]:
    """The lines and rows that fit ``kin_card_max_rows`` and ``kin_card_max_chars``; what does not fit is
    said, so a list that was cut does not read as everything there is."""
    shown = list(rows[:settings.kin_card_max_rows])
    if len(rows) > len(shown):
        shown = shown[:-1]
    while True:
        cut = len(rows) - len(shown)
        lines = [*(row.text for row in shown), *([f"另有 {cut} 條關係未列"] if cut else [])]
        if len("\n".join([HEADER, *lines])) <= settings.kin_card_max_chars or not shown:
            return lines, shown
        shown = shown[:-1]


def _edge_rows(found: _Found) -> list[_Row]:
    """What the cue walked to, then the steps of the paths; rows that would read the same (two Persons of one
    name) are one."""
    rows: dict[str, _Row] = {}
    for edge in (*found.asked, *found.edges):
        said = _relation(edge, found.labels)
        rows.setdefault(said, _Row(f"{said}（{verse_ref(edge.unit)}）", edge.unit, (edge,)))
    return list(rows.values())


def _render(people: Sequence[Person], found: _Found) -> KinCard:
    labels = found.labels
    lead = [*(_Row(note) for note in found.notes), *(_Row(_path_line(p, labels), None, p.edges) for p in found.paths),
            *found.rows]
    lines, shown = _fit([*lead, *_edge_rows(found)])
    edges = list(dict.fromkeys(e for row in shown for e in row.edges))
    nodes = tuple(dict.fromkeys(n for e in edges for n in (e.src, e.dst)))
    evidence = dict.fromkeys(unit for row in shown for unit in (row.unit, *(e.unit for e in row.edges)) if unit)
    return KinCard(
        text="\n".join([HEADER, *lines]), seeds=tuple(dict.fromkeys(p.label for p in people)),
        persons=tuple(p.id for p in people), nodes=nodes, names=tuple(labels[n] for n in nodes),
        edges=tuple((e.src, e.kind, e.dst, e.unit) for e in edges), hops=found.hops, lines=len(lines),
        evidence=tuple(evidence))


# --- the walks ------------------------------------------------------------------------------------

def _path_of(row: Mapping[str, Any]) -> _Path:
    edges = tuple(_Edge(a, kind, b, role, units[0]) for a, kind, b, role, units in row["edges"])
    return _Path(tuple((n[0], n[1]) for n in row["nodes"]), edges)


def _note(found: _Found, paths: Iterable[_Path], into: list[_Edge]) -> None:
    seen = {(e.src, e.kind, e.dst) for e in (*found.asked, *found.edges)}
    for path in paths:
        found.labels.update(path.nodes)
        found.hops = max(found.hops, len(path.edges))
        for edge in path.edges:
            if (edge.src, edge.kind, edge.dst) not in seen:
                seen.add((edge.src, edge.kind, edge.dst))
                into.append(edge)


async def _pair_paths(people: Sequence[Person], reads: neo4j_db.Reads, found: _Found) -> None:
    for a, b in list(combinations(people, 2))[:MAX_PAIRS]:
        paths = [_path_of(r) for r in await reads("kin_path", x=a.id, y=b.id)]
        _note(found, paths, found.edges)
        found.paths += paths


def _plans(cue: Cue) -> list[tuple[str, dict[str, Any]]]:
    plans: list[tuple[str, dict[str, Any]]] = []
    if cue.up:
        plans.append(("kin_up", {"depth": cue.up}))
    if cue.down:
        plans.append(("kin_down", {"depth": cue.down}))
    if cue.side:
        plans.append(("kin_side", {"types": list(cue.side)}))
    return plans or [("kin_near", {})]


def _by_way_of(path: _Path, person: str, in_law: str) -> bool:
    """岳母 is reached through a spouse, 媳婦 through a child's: a brother one hop away says nothing of either."""
    first = path.edges[0]
    if in_law == SPOUSE_FIRST:
        return first.kind == SPOUSE
    return in_law == CHILD_FIRST and len(path.edges) == 2 and first.kind == PARENT and first.src == person \
        and path.edges[1].kind == SPOUSE


async def _walk_as_asked(walkers: Sequence[tuple[Person, Cue]], reads: neo4j_db.Reads, found: _Found) -> None:
    for person, cue in walkers[:MAX_WALKERS]:
        for name, params in _plans(cue):
            paths = [_path_of(r) for r in await reads(name, x=person.id, **params)]
            if cue.in_law:
                paths = [p for p in paths if _by_way_of(p, person.id, cue.in_law)]
            _note(found, paths, found.asked)


def _same_name(ends: Sequence[End], people_of: Mapping[str, Sequence[Person]], found: _Found) -> None:
    for end in ends:
        people = people_of.get(end.surface, ())
        if not people:
            continue
        found.notes.append(f"「{end.surface}」在親屬資料中共 {len(people)} 筆"
                           "（只收有親屬記載的人，同一人可能分列），以下列出各筆的父母。")
        for k, person in enumerate(people, 1):
            found.labels.update({person.id: person.label, **{p[0]: p[1] for p in person.parents}})
            found.rows += _same_name_rows(person, k)
            if person.parents:
                found.hops = max(found.hops, 1)


def _same_name_rows(person: Person, k: int) -> list[_Row]:
    """One row per parent, each with its verse."""
    if person.parents:
        return [_Row(f"{person.label}（{k}）：{label} 的子女（{verse_ref(unit)}）", unit,
                     (_Edge(pid, PARENT, person.id, role, unit),)) for pid, label, role, unit in person.parents]
    unit = person.units[0] if person.units else None
    where = f"（{verse_ref(unit)}）" if unit else ""
    return [_Row(f"{person.label}（{k}）：未整理到父母{where}", unit)]


async def _passages(evidence: Sequence[str], reads: neo4j_db.Reads) -> tuple[str, ...]:
    rows = await reads("unit_passages", units=list(evidence)) if evidence else []
    return tuple(dict.fromkeys(row["passage"] for unit in evidence for row in rows if row["unit"] == unit))


async def _same_name_card(ends: Sequence[End], people_of: Mapping[str, Sequence[Person]], reads: neo4j_db.Reads,
                          with_evidence: bool) -> KinCard:
    found = _Found()
    _same_name(ends, people_of, found)
    if not any(row.edges for row in found.rows):
        return KinCard(skip_reason=NO_EDGE)
    card = _render([p for end in ends for p in people_of.get(end.surface, ())], found)
    return replace(card, passages=await _passages(card.evidence, reads) if with_evidence else ())


async def _picked(people_of: Mapping[str, Sequence[Person]], units: frozenset[str],
                  reads: neo4j_db.Reads) -> tuple[dict[str, Person], bool]:
    """Who each name means, and whether a path between two names chose them."""
    if len(people_of) == 2:
        (first, a_side), (second, b_side) = people_of.items()
        pair = await kin_people.best_pair(a_side, b_side, units, reads)
        if pair:
            return {first: pair[0], second: pair[1]}, True
    return {surface: kin_people.pick(people, units) for surface, people in people_of.items()}, False


def _walkers(question: Question, picked: Mapping[str, Person]) -> list[tuple[Person, Cue]]:
    walkers = []
    for end in question.ends:
        cue = question.cue_of(end)
        if cue is not None and end.surface in picked:
            walkers.append((picked[end.surface], cue))
    return list({person.id: (person, cue) for person, cue in walkers}.values())


async def _card(question_text: str, entities: Sequence[str], pool: Sequence[Mapping[str, Any]],
                lexicon: RoutingLexicon, reads: neo4j_db.Reads) -> KinCard:
    question = kin_people.read_question(question_text, entities, lexicon)
    cue = question.reading.cue
    if cue is None:
        return KinCard(skip_reason=NO_CUE)
    found_of = await kin_people.candidates(question.ends, reads) if question.ends else {}
    if not found_of:
        return KinCard(skip_reason=NO_PERSON)
    if cue.same_name:
        return await _same_name_card(question.ends, found_of, reads, with_evidence=True)
    people_of = kin_people.narrowed(question, found_of)
    if not people_of:
        return KinCard(skip_reason=NO_PERSON)
    units = kin_people.pool_units(pool)
    picked, by_a_path = await _picked(people_of, units, reads)
    if not by_a_path:
        open_ends = [end for end in question.ends if question.cue_of(end) and end.surface in people_of
                     and not kin_people.settled(people_of[end.surface], units)]
        if open_ends:
            return await _same_name_card(open_ends, people_of, reads, with_evidence=False)
    return await _picked_card(question, picked, found_of, reads)


async def _picked_card(question: Question, picked: Mapping[str, Person], found_of: Mapping[str, Sequence[Person]],
                       reads: neo4j_db.Reads) -> KinCard:
    people = list({p.id: p for p in picked.values()}.values())
    found = _Found(notes=_notes(picked, found_of))
    if len(people) >= 2:
        await _pair_paths(people, reads, found)
    await _walk_as_asked(_walkers(question, picked), reads, found)
    if not found.anything:
        return KinCard(skip_reason=NO_EDGE)
    if _ONE_SEX_OF_SIBLING.search(question.masked) and any(e.kind == SIBLING for e in (*found.asked, *found.edges)):
        found.notes.append(SIBLING_NOTE)
    card = _render(people, found)
    return replace(card, passages=await _passages(card.evidence, reads))


async def build(question: str, entities: Sequence[str], pool: Sequence[Mapping[str, Any]],
                lexicon: RoutingLexicon, build_id: str) -> KinCard:
    """The card of a question ``wants`` said asks about kinship, or why there is none; Neo4j not
    answering is one such reason, and whatever was found before it is dropped."""
    started = time.perf_counter()
    reads = neo4j_db.Reads(build_id)
    try:
        card = await _card(question, entities, pool, lexicon, reads)
    except neo4j_db.Skipped as exc:
        card = KinCard(skip_reason=exc.reason)
    return replace(card, n_cypher=reads.n, ms=round((time.perf_counter() - started) * 1000, 2))


def wants(question: str, entities: Sequence[str], lexicon: RoutingLexicon) -> bool:
    """Whether the question asks about kinship (the cue, and for 關係 alone two names): no Neo4j."""
    read = kin_people.read_question(question, entities, lexicon)
    cue = read.reading.cue
    return cue is not None and kin_cues.takes(cue, len(read.ends))

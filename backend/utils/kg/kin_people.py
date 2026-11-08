"""Who a kinship question is about: the names it writes, the people each may be, who is meant.

A name can mean several people. A qualifier the table knows settles it (施洗約翰: 撒迦利亞's son), and one it
does not (亞利馬太的約翰) means none of those it knows of. Of two names, the pair with the shortest path between them
goes first, then the pool. Of one name, someone with the edge asked for goes before someone without, then
the person the candidate pool mentions most, then the one mentioned most. People with parents of different
names are said to be undecided unless the pool clearly holds one: the card then lists them all (``settled``).
A nation, a tribe or a place beside the person is no person (猶大王希西家, 便雅憫人掃羅).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from database import neo4j_db
from ragcommon.routing import MASK, Hit, RoutingLexicon
from utils.kg import kin_cues
from utils.kg.kin_cues import SIBLING, SPOUSE, Cue, Reading

_ENTITY_KINDS = ("name", "dotless")
_PERSON_KINDS = ("name", "dotless", "alias", "divine")
_A_PEOPLE_AFTER = ("人", "支派", "地", "國", "家", "族", "城")
_KINGDOM_BEFORE = "王"
_DESCRIBED_AFTER = "的"
# 施洗約翰: 約翰 the son of 撒迦利亞 (Luke 3:2); 加略人猶大: 猶大 the son of 西門 (John 6:71)
_QUALIFIERS = (("施洗的", "約翰", "撒迦利亞"), ("施洗", "約翰", "撒迦利亞"), ("加略人", "猶大", "西門"), ("加略的", "猶大", "西門"))
# 摩西的哥哥亞倫: read longest first, 哥亞 is a place and takes 亞倫's first character
_KIN_WORD_AFTER_OF = re.compile(r"(?<=的)(?:哥哥|弟弟|兄弟|弟兄|姊姊|姐姐|妹妹|姊妹|妹子|父親|母親|兒子|女兒|妻子|丈夫|祖父|祖母|孫子|孫女|岳父|岳母)")
# a one-character name the lexicon never reads (MIN_LEN): 閃的兒子
_ONE_CHARACTER = re.compile(r"(?:^|(?<=[，。？！、；：和與及]))([一-鿿])的")
_NO_ONE_CHARACTER_NAME = frozenset("他她你我誰其祂牠它神主王人父母子女兒妻夫兄弟姊妹哥祖孫這那此某彼")
_MIN_OVERLAP = 3
_CLEAR_RATIO = 2
MAX_PAIR_CANDIDATES = 16        # 亞撒利雅 is eighteen people, 約拿單 twelve, the most mentioned first


@dataclass(frozen=True)
class Person:
    id: str
    label: str
    mentions: int
    conflict: bool
    units: tuple[str, ...]
    parents: tuple[tuple[str, str, str, str], ...]     # (id, label, role, first verse), fathers first
    children: int
    spouses: int
    siblings: int


@dataclass(frozen=True)
class End:
    """A name the question writes, or an intent entity (``start`` None)."""

    surface: str
    lookups: tuple[str, ...]
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class Question:
    text: str
    masked: str
    reading: Reading
    ends: tuple[End, ...]

    def cue_of(self, end: End) -> Cue | None:
        return self.reading.of(end.end)


def _one_character_hits(question: str, taken: Sequence[Hit]) -> list[Hit]:
    out = []
    for found in _ONE_CHARACTER.finditer(question):
        at = found.start(1)
        if (found.group(1) not in _NO_ONE_CHARACTER_NAME and kin_cues.word_at(question, found.end()) is not None
                and not any(h.start <= at < h.end for h in taken)):
            out.append(Hit(found.group(1), at, at + 1, "name", ()))
    return out


def names_read(question: str, lexicon: RoutingLexicon) -> list[Hit]:
    """The lexicon's names with the kinship words blanked out first, and the one-character names."""
    blanked = _KIN_WORD_AFTER_OF.sub(lambda m: MASK * len(m.group()), question)
    hits = lexicon.match(blanked)
    return sorted([*hits, *_one_character_hits(question, hits)], key=lambda h: h.start)


def _is_a_people(question: str, hit: Hit, hits: Sequence[Hit]) -> bool:
    after = question[hit.end:]
    if after.startswith(_A_PEOPLE_AFTER):
        return True
    return after.startswith(_KINGDOM_BEFORE) and any(h.start == hit.end + len(_KINGDOM_BEFORE) for h in hits)


def _end_of(hit: Hit, written: bool) -> End:
    lookups = tuple(dict.fromkeys([hit.surface, *(t.label for t in hit.targets)]))
    return End(hit.surface, lookups, hit.start if written else None, hit.end if written else None)


def ends_of(question: str, hits: Sequence[Hit], entities: Iterable[str], lexicon: RoutingLexicon) -> tuple[End, ...]:
    """The names the question writes, then the intent entities that are exactly a name."""
    found = [_end_of(h, True) for h in hits if h.kind in _PERSON_KINDS and not _is_a_people(question, h, hits)]
    for entity in entities:
        found += [_end_of(h, False) for h in lexicon.match(entity) if h.surface == entity and h.kind in _ENTITY_KINDS]
    unique: dict[str, End] = {}
    for end in found:
        unique.setdefault(end.surface, end)
    return tuple(unique.values())


def read_question(question: str, entities: Sequence[str], lexicon: RoutingLexicon) -> Question:
    hits = names_read(question, lexicon)
    masked = kin_cues.masked(question, hits, lexicon)
    return Question(question, masked, kin_cues.reading(masked), ends_of(question, hits, entities, lexicon))


def _person(row: Mapping[str, Any]) -> Person:
    parents = tuple(sorted(((p[0], p[1], p[2], p[3][0]) for p in row["parents"]), key=lambda p: (p[2] == "M", p[0])))
    return Person(row["id"], row["label"], row["mentions"], bool(row["kin_conflict"]), tuple(row["units"]), parents,
                  row["children"], row["spouses"], row["siblings"])


async def candidates(ends: Sequence[End], reads: neo4j_db.Reads) -> dict[str, list[Person]]:
    """Each end's people: everyone whose surfaces hold one of its spellings."""
    lookups = list(dict.fromkeys(s for end in ends for s in end.lookups))
    rows = await reads("kin_persons", surfaces=lookups)
    by_surface: dict[str, dict[str, Person]] = {}
    for row in rows:
        by_surface.setdefault(row["surface"], {})[row["id"]] = _person(row)
    found = {}
    for end in ends:
        people = {pid: p for s in end.lookups for pid, p in by_surface.get(s, {}).items()}
        if people:
            found[end.surface] = sorted(people.values(), key=lambda p: (-p.mentions, p.id))
    return found


def _qualified(question: Question, end: End, people: Sequence[Person]) -> list[Person]:
    """The people left once what is written right before the name has spoken."""
    before = question.text[:end.start] if end.start is not None else ""
    for qualifier, name, parent in _QUALIFIERS:
        if end.surface == name and before.endswith(qualifier):
            return [p for p in people if any(x[1] == parent for x in p.parents)]
    return [] if len(people) > 1 and before.endswith(_DESCRIBED_AFTER) else list(people)


def _with_the_edge(people: Sequence[Person], cue: Cue | None) -> list[Person]:
    """Those with the edge asked for, if any has it."""
    if cue is None:
        return list(people)
    kept = [p for p in people if (cue.up and p.parents) or (cue.down and p.children) or cue.near
            or (SPOUSE in cue.side and p.spouses) or (SIBLING in cue.side and p.siblings)]
    return kept or list(people)


def narrowed(question: Question, found: Mapping[str, Sequence[Person]]) -> dict[str, list[Person]]:
    """Each end's people once its qualifier and its cue have spoken; an end with no one left is gone."""
    out = {}
    for end in question.ends:
        people = _with_the_edge(_qualified(question, end, found.get(end.surface, ())), question.cue_of(end))
        if people:
            out[end.surface] = people
    return out


def _overlap(person: Person, units: frozenset[str]) -> int:
    return len(units & set(person.units))


def pick(people: Sequence[Person], units: frozenset[str]) -> Person:
    return min(people, key=lambda p: (-_overlap(p, units), -p.mentions, p.id))


def settled(people: Sequence[Person], units: frozenset[str]) -> bool:
    """Can a person be told from the others of the name with other parents? The pool must clearly hold one."""
    best = pick(people, units)
    parents = {x[1] for x in best.parents}
    rivals = [p for p in people if p.id != best.id and parents and p.parents and not parents & {x[1] for x in p.parents}]
    if not rivals:
        return True
    return (_overlap(best, units) >= _MIN_OVERLAP
            and _overlap(best, units) >= _CLEAR_RATIO * max(_overlap(r, units) for r in rivals))


async def best_pair(first: Sequence[Person], second: Sequence[Person], units: frozenset[str],
                    reads: neo4j_db.Reads) -> tuple[Person, Person] | None:
    """The two people of two names with the shortest path, the pool breaking ties; None: no path, or nothing to
    choose among."""
    a_side, b_side = first[:MAX_PAIR_CANDIDATES], second[:MAX_PAIR_CANDIDATES]
    pairs = [[a.id, b.id] for a in a_side for b in b_side if a.id != b.id]
    if len(pairs) < 2:
        return None
    rows = await reads("kin_pair_hops", pairs=pairs)
    if not rows:
        return None
    by_id = {p.id: p for p in (*a_side, *b_side)}

    def rank(row: Mapping[str, Any]) -> tuple:
        a, b = by_id[row["x"]], by_id[row["y"]]
        return (row["hops"], -_overlap(a, units) - _overlap(b, units), -a.mentions - b.mentions, a.id, b.id)
    best = min(rows, key=rank)
    return by_id[best["x"]], by_id[best["y"]]


def pool_units(pool: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    return frozenset(ref["unit_key"] for c in pool for ref in c.get("unit_refs") or () if ref.get("unit_key"))

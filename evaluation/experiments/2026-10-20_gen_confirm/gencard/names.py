"""The layer and names the Genesis card reads (prereg §5.1): ``L = parse(gen_layer_json, gen_names_json)``.

``L`` (a frozen ``Layer``) holds stage-0's frozen gen_layer.json (the engine reads it unchanged) and what
the rule of §5.2 needs from it: the two chains (chapter 5, then 11), each person's chain father and son,
the begetting ages, the lifespans (stated, else the layer's derived one: ``engine.gen_lifespan``), the
taken one (``engine.taken``), the father -> son statements the layer makes (its edges and the conflict
edge across the chapters; rule 6 checks a written marker against them only) and the chain names the
layer also lists as another father's son (a namesake: rule 4's exception). From gen_names.json (schema
``gen_confirm.gen_names.v1``, exactly the contract's keys, built by names_g.py from the text layer's
name_spans and the routing lexicon; its chain must be the layer's) it takes the Cain-line and Abram-family
names (rule 4), the other books (rule 2) and the lexicon blockers (rule 3).

The names that are also common words come with their common-word blockers (``COMMON_WORDS``, the only
names this repo file holds). A chain name among them (rule 3: 閃, 他拉) is guarded: it counts only when
another chain name of its own chapter is found too, and its run into a chain name that begins with its
last character (他拉 + 拉…) is a blocker as well, since 他 + 拉… reads as well. A rule-4 name among them
(以拿 in 可以拿) is hidden by its words, which never hide a chain name (``trigger.scan``). Pure functions,
standard library only.
"""
from __future__ import annotations

import copy
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from . import engine

NAMES_SCHEMA = "gen_confirm.gen_names.v1"
NAMES_KEYS = ("schema", "text_digest", "gen_layer_sha256", "chain", "cain_line", "abram_family", "extra_persons",
              "other_books", "lexicon_blockers", "sources")             # names_g.problems' contract keys
# rules 3 and 4: the common words a name is part of or overlaps (其他 before 拉…: a tie goes to the leftmost);
# a blocker never swallows a cue (trigger.scan skips a blocker that overlaps one, so 閃過世 and 他拉出生 still
# name the person)
COMMON_WORDS = {
    "閃": ("閃電", "閃光", "閃爍", "閃耀", "閃亮", "閃避", "閃開", "閃現", "閃失", "閃身", "閃躲", "閃過", "閃動",
          "閃念", "閃閃", "閃著", "一閃", "躲閃", "忽閃"),
    "他拉": (*(f"他拉{c}" for c in "著住起開下上回進了扯近長動"), "其他"),
    "以拿": tuple(f"{c}以拿" for c in "可所難得足用藉何"),
}


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


@dataclass(frozen=True)
class Layer:
    gen: Mapping                              # gen_layer.json (a private copy; the engine's input)
    order: tuple[str, ...]                    # chain ids: chapter 5, then chapter 11
    chains: Mapping[int, tuple[str, ...]]
    name: Mapping[str, str]                   # id -> name
    id_of: Mapping[str, str]                  # name -> id (19 distinct chain names)
    chapter: Mapping[str, int]
    index: Mapping[str, int]                  # position in its chapter's chain
    beget: Mapping[str, int | None]
    lifespan: Mapping[str, int | None]
    taken: frozenset[str]
    parents: frozenset[tuple[str, str]]       # (father id, son id) the layer states
    son_namesakes: frozenset[str]             # chain names the layer also gives another father as a son
    guarded: Mapping[str, tuple[str, ...]]    # name -> its common words (counts only with a chapter mate)
    blockers: tuple[str, ...]                 # lexicon blockers, common words and run-togethers, longest first
    rule4_words: frozenset[str]               # the blockers that hide a rule-4 name (never a chain name)
    cain_line: tuple[str, ...]
    abram_family: tuple[str, ...]
    other_books: tuple[str, ...]
    gen_layer_sha256: str

    def father(self, x: str) -> str | None:
        """x's chain father inside its chapter (None for a chapter's head)."""
        i = self.index[x]
        return self.chains[self.chapter[x]][i - 1] if i > 0 else None

    def son(self, x: str) -> str | None:
        """x's chain son inside its chapter (None for a chapter's last)."""
        chain, i = self.chains[self.chapter[x]], self.index[x]
        return chain[i + 1] if i + 1 < len(chain) else None

    def distance(self, a: str, b: str) -> int | None:
        """Generations from a down to b, when b is a's chain descendant in the same chapter."""
        if self.chapter[a] != self.chapter[b] or self.index[b] <= self.index[a]:
            return None
        return self.index[b] - self.index[a]

    def age_at_birth(self, a: str, b: str) -> int | None:
        """a's age at the birth of his chain descendant b (the begetting ages a .. b's father)."""
        if self.distance(a, b) is None:
            return None
        chain = self.chains[self.chapter[a]]
        ages = [self.beget[z] for z in chain[self.index[a]:self.index[b]]]
        return None if None in ages else sum(ages)


def _frozen(d: dict) -> Mapping:
    return MappingProxyType(dict(d))


def _layer_chains(gen: dict) -> dict[int, tuple[str, ...]]:
    chapters = sorted({n["chapter"] for n in gen["nodes"]})
    return {ch: tuple(engine.gen_chain(gen, ch)) for ch in chapters}


def _son_namesakes(gen: dict, id_of: Mapping[str, str], parents: frozenset) -> frozenset[str]:
    """Chain names a node lists among its sons although the layer states no edge to that chain person."""
    return frozenset(s for n in gen["nodes"] for s in n.get("sons") or ()
                     if s in id_of and (n["id"], id_of[s]) not in parents)


def _run_together(guarded: Mapping[str, tuple[str, ...]], names) -> set[str]:
    """A guarded name of two or more characters run into a chain name that begins with its last one."""
    return {g + n[1:] for g in guarded for n in names if len(g) > 1 and n != g and n[0] == g[-1]}


def _check_keys(gen_names: dict) -> None:
    missing, extra = [k for k in NAMES_KEYS if k not in gen_names], sorted(set(gen_names) - set(NAMES_KEYS))
    if missing or extra:
        raise ValueError(f"gen_names.json keys are not the contract's: missing {missing}, extra {extra}")


def _check_chain(gen_names: dict, order: tuple[str, ...], name: Mapping, chapter: Mapping) -> None:
    if gen_names.get("schema") != NAMES_SCHEMA:
        raise ValueError(f"gen_names.json schema is not {NAMES_SCHEMA}")
    want = [{"id": x, "name": name[x], "chapter": chapter[x]} for x in order]
    if [dict(c) for c in gen_names.get("chain", [])] != want:
        raise ValueError("gen_names.json's chain is not the layer's chain")


def parse(gen_layer_json: dict, gen_names_json: dict, *,
          common_words: Mapping[str, tuple[str, ...]] = MappingProxyType(COMMON_WORDS)) -> Layer:
    """The Layer of the two contract documents; ValueError when they do not fit together."""
    _check_keys(gen_names_json)
    gen = copy.deepcopy(gen_layer_json)
    chains = _layer_chains(gen)
    order = tuple(x for ch in sorted(chains) for x in chains[ch])
    nodes = {n["id"]: n for n in gen["nodes"]}
    name = {x: nfkc(nodes[x]["name"]) for x in order}
    if len(set(name.values())) != len(order):
        raise ValueError("a chain name is borne by two layer rows")
    chapter = {x: nodes[x]["chapter"] for x in order}
    _check_chain(gen_names_json, order, name, chapter)
    if gen_names_json.get("text_digest") != gen.get("text_digest"):
        raise ValueError("gen_names.json was built from another text layer than gen_layer.json")
    id_of = {v: k for k, v in name.items()}
    parents = frozenset((e[0], e[1]) for e in gen.get("edges", []) + gen.get("conflict_edges", []))
    lists = {k: tuple(sorted({nfkc(s) for s in gen_names_json[k]} - set(id_of)))
             for k in ("cain_line", "abram_family", "other_books")}
    words = {nfkc(k): tuple(nfkc(w) for w in v) for k, v in common_words.items()}
    guarded = {k: v for k, v in words.items() if k in id_of}
    rule4 = frozenset(w for k, v in words.items() if k in lists["cain_line"] + lists["abram_family"] for w in v)
    lex = {nfkc(s) for s in gen_names_json["lexicon_blockers"]}
    chain_words = {w for ws in guarded.values() for w in ws} | _run_together(guarded, id_of)
    blockers = sorted(lex | chain_words | rule4, key=lambda s: (-len(s), s))
    return Layer(gen=gen, order=order, chains=_frozen(chains), name=_frozen(name), id_of=_frozen(id_of),
             chapter=_frozen(chapter), index=_frozen({x: chains[chapter[x]].index(x) for x in order}),
             beget=_frozen({x: engine._f(nodes[x], "beget") for x in order}),
             lifespan=_frozen({x: engine.gen_lifespan(gen, x) for x in order}),
             taken=frozenset(x for x in order if engine.taken(nodes[x])), parents=parents,
             son_namesakes=_son_namesakes(gen, id_of, parents), guarded=_frozen(guarded),
             blockers=tuple(blockers), rule4_words=rule4, gen_layer_sha256=gen_names_json["gen_layer_sha256"],
             **lists)

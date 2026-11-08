"""Which name tokens are one person: PDF-only identity over the kinship rows.

Ported from method D2 of the prototype (store reports/kg_restore_20261102/kg_plan_v2/pdf_only/
ident.py). Tokens of one name start apart and are merged, nearest evidence first and the rarest names
first (a rare name is one person more surely, and its merges let the ancestor check see further), unless
the two clusters disagree (``_Clusters.compatible``): a father each that differ (footnote aliases
excepted), a mother each that differ, a man and a woman, a title / gentile that differs, 稱呼X的 on one of the
two, two tokens of one verse the rows keep apart (``person_signs``). The steps, in order:

1. a list chain (X生Y，Y生Z), the same verse, the same pericope (long lists: within three verses);
2. a signature in common (a father, a mother, a child, a spouse, a sibling, a gentile, a title): within
   a testament group one is enough, across the Old Testament, the New Testament's genealogies (Matthew
   1, Luke 3) and its narrative that takes two. Repeated until nothing changes;
3. parallel pericopes, and neighbouring pericopes where a narrative runs on (not the name lists of
   1 Chronicles, Ezra and Nehemiah, nor the New Testament's narrative, where 雅各 of Mark 5 is not 雅各 of Mark 6);
4. in the Old Testament's narrative, the same book (for a name mentioned at least 30 times, Samuel and
   Kings are one each: 大衛 of 1 and 2 Samuel) when the name's clusters there do not conflict, agree on a gentile and, for women, on a husband; a name two kingdoms'
   kings share (``regnal_homonyms``) never merges this way. Nothing merges on sharing a testament group
   alone, and nothing in the list books or the New Testament on sharing a book alone: their people share
   few names among many (約翰, 馬利亞, 雅各, 撒迦利亞);
5. the signatures again; then the renames of ``person_aliases``: the cluster at the rename's verse, and in
   the Old Testament all of the two names' clusters if none of them conflict (以色列 is always 雅各; 瑪探雅 is more
   than one man); and every token of 耶穌, whom kg0's divine rule marks, in one person.

Every merge is refused when one cluster is the other's ancestor, so PARENT_OF has no cycle: a
genealogy reuses names (亞瑪利雅 begets 亞希突 twice in 1 Chronicles 6, generations apart).

A token without a kinship row (``Identity.node_of``) belongs to the one cluster of its name in its pericope,
else in its book, else, for a name mentioned at least 30 times with rows in three books or more, in its
testament group (摩西 has rows in few books and is the same man in the others; the 亞比米勒 of Genesis is not the
one of Judges), else to none. In a list book only that last way: 撒迦利亞 of Ezra 8:3 is not the one of 8:11. In
the New Testament's narrative beyond the pericope it also takes a name with one cluster in the whole
group, with rows in two pericopes or more: 施洗的約翰 is no 西庇太's son for want of another 約翰 with a row in
Matthew, and the 掃羅 of Acts 7 is not the king Acts 13:21 cites. A rename whose other name has no kinship row in its scope (彼得, whose rows
are all written 西門‧彼得) lends that name's tokens the cluster at the rename's evidence verse.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, NamedTuple, Sequence

from ragdata.kg.kin_extract import KinRow
from ragdata.kg.kin_tokens import JESUS, Corpus, Verse
from ragdata.kg.person_aliases import Aliases
from ragdata.kg.person_signs import Kings, Mention, Signs, signs_of

_LIST_GAPS = frozenset({"，", "；", "。", "、", ""})
_STRONG = ("ch:", "sp:", "si:", "ma:", "gent:", "ti:", "q:")
_SPELLED_ALIKE = ("ch:", "ma:", "sp:", "si:")
_CROSS_TESTAMENT = ("ch:", "sp:")
_CROSS_TESTAMENT_SHARED = 2
_LIST_BOOKS = frozenset({"1ch", "ezr", "neh"})
_LONG_PERICOPE = 15
_NEAR_VERSES = 3
_MAJOR_NAME = 30
_OLD, _GENEALOGY, _NARRATIVE = "O", "G", "N"
_MIN_PERICOPES_IN_NARRATIVE = 2
_MIN_BOOKS_IN_GROUP = 3
_ONE_BOOK = {"2sa": "1sa", "2ki": "1ki"}
_NO_BOOK_MERGE = frozenset({"num"})


class Pericopes(NamedTuple):
    """What the identity reads of the struct and kg0 layers."""
    of_unit: Mapping[str, str]
    size: Mapping[str, int]
    next_id: Mapping[str, str | None]
    parallels: Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class Context:
    corpus: Corpus
    pericopes: Pericopes
    new_testament: frozenset[str]
    aliases: Aliases
    kings: Kings = Kings()


def group_of(ctx: Context, unit: str) -> str:
    """O Old Testament; G the New Testament's genealogies (they retell the Old); N its narrative."""
    verse = ctx.corpus.verse(unit)
    if verse.book_id not in ctx.new_testament:
        return _OLD
    return _GENEALOGY if (verse.book_id, verse.chapter) in (("mat", 1), ("luk", 3)) else _NARRATIVE


def _in_narrative_of_the_old_testament(ctx: Context, unit: str) -> bool:
    return group_of(ctx, unit) == _OLD and ctx.corpus.verse(unit).book_id not in _LIST_BOOKS


class Place(NamedTuple):
    """Where a token stands, for ``Identity.node_of``: a list book has neither pericope nor book to go by."""
    pericope: str | None
    book: str | None
    group: str


def place_of(ctx: Context, verse: Verse) -> Place:
    group = group_of(ctx, verse.unit_key)
    if verse.book_id in _LIST_BOOKS:
        return Place(None, None, group)
    return Place(ctx.pericopes.of_unit.get(verse.unit_key), verse.book_id, group)


def in_narrative(place: Place) -> bool:
    return place.group == _NARRATIVE


class _Clusters:
    """Union-find over mentions; a merge is refused when the clusters disagree or when one is
    the other's ancestor (a genealogy reuses names: 亞希突 begets 撒督 twice in 1 Chronicles 6)."""

    def __init__(self, sign: Signs, aliases: Aliases) -> None:
        self.parent: dict[Mention, Mention] = {m: m for m in sign.surface}
        self.same = aliases.same
        self.renamed = aliases.renamed
        self.fathers: dict[Mention, set[str]] = defaultdict(set)
        self.mothers: dict[Mention, set[str]] = defaultdict(set)
        self.strong: dict[Mention, set[str]] = defaultdict(set)
        self.children: dict[Mention, set[Mention]] = defaultdict(set)
        self.apart: dict[Mention, set[Mention]] = defaultdict(set)
        self.woman: dict[Mention, bool] = {}
        self.man: dict[Mention, bool] = {}
        for mention in sign.surface:
            self.fathers[mention] = set(sign.fathers.get(mention, ()))
            self.mothers[mention] = set(sign.mothers.get(mention, ()))
            self.strong[mention] = set(sign.strong.get(mention, ()))
            self.children[mention] = set(sign.children.get(mention, ()))
            self.apart[mention] = set(sign.apart.get(mention, ()))
            self.woman[mention] = mention in sign.women
            self.man[mention] = mention in sign.men

    def find(self, mention: Mention) -> Mention:
        parent = self.parent
        while parent[mention] != mention:
            parent[mention] = parent[parent[mention]]
            mention = parent[mention]
        return mention

    def _descends(self, root: Mention, ancestor: Mention) -> bool:
        """Is ``root`` a descendant of the cluster ``ancestor``?"""
        seen, stack = {ancestor}, [ancestor]
        while stack:
            for child in self.children[stack.pop()]:
                node = self.find(child)
                if node == root:
                    return True
                if node not in seen:
                    seen.add(node)
                    stack.append(node)
        return False

    def _titles_agree(self, a: Mention, b: Mention) -> bool:
        for prefix in ("ti:", "gent:"):
            first = {x for x in self.strong[a] if x.startswith(prefix)}
            second = {x for x in self.strong[b] if x.startswith(prefix)}
            if first and second and not first & second:
                return False
        return True

    def _names_agree(self, first: set[str], second: set[str]) -> bool:
        if not first or not second or first & second:
            return True
        return any(self.same.get(x, frozenset()) & second for x in first)

    def _sexes_agree(self, a: Mention, b: Mention) -> bool:
        return not (self.woman[a] and self.man[b]) and not (self.man[a] and self.woman[b])

    def _kept_apart(self, a: Mention, b: Mention) -> bool:
        return any(self.find(m) == b for m in self.apart[a])

    def _called_alike(self, a: Mention, b: Mention) -> bool:
        return {x for x in self.strong[a] if x.startswith("q:")} == {x for x in self.strong[b] if x.startswith("q:")}

    def compatible(self, a: Mention, b: Mention) -> bool:
        return self._titles_agree(a, b) and self._called_alike(a, b) \
            and self._names_agree(self.fathers[a], self.fathers[b]) \
            and self._names_agree(self.mothers[a], self.mothers[b]) and self._sexes_agree(a, b) \
            and not self._kept_apart(a, b) and not self._descends(a, b) and not self._descends(b, a)

    def merge(self, first: Mention, second: Mention) -> bool:
        a, b = self.find(first), self.find(second)
        if a == b:
            return True
        if not self.compatible(a, b):
            return False
        root, other = min(a, b, key=repr), max(a, b, key=repr)
        self.parent[other] = root
        self.fathers[root] = self.fathers[a] | self.fathers[b]
        self.mothers[root] = self.mothers[a] | self.mothers[b]
        self.strong[root] = self.strong[a] | self.strong[b]
        self.children[root] = self.children[a] | self.children[b]
        self.apart[root] = self.apart[a] | self.apart[b]
        self.woman[root] = self.woman[a] or self.woman[b]
        self.man[root] = self.man[a] or self.man[b]
        return True

    def conflicted(self, mentions: Iterable[Mention]) -> bool:
        roots = {self.find(m) for m in mentions}
        return any(not self.compatible(a, b) for a in roots for b in roots if a != b)


def _by_surface(sign: Signs, c: Corpus) -> dict[str, list[Mention]]:
    by: dict[str, list[Mention]] = defaultdict(list)
    for m in sorted(sign.surface, key=lambda m: (c.position[m[0]], m[1])):
        by[sign.surface[m]].append(m)
    return by


def _merge_chain_and_verse(cl: _Clusters, ctx: Context, mentions: Sequence[Mention]) -> None:
    c = ctx.corpus
    for a, b in zip(mentions, mentions[1:]):
        same_verse_list = a[0] == b[0] and b[1] == a[1] + 1 \
            and c.verse(a[0]).gap(a[1], b[1]) in _LIST_GAPS
        next_verse = c.position[b[0]] == c.position[a[0]] + 1 and b[1] == 0 \
            and a[1] == len(c.verse(a[0]).tokens) - 1
        if same_verse_list or next_verse:
            cl.merge(a, b)


def _per_pericope(ctx: Context, mentions: Iterable[Mention]) -> dict[str | None, list[Mention]]:
    per: dict[str | None, list[Mention]] = defaultdict(list)
    for m in mentions:
        per[ctx.pericopes.of_unit.get(m[0])].append(m)
    return per


def _merge_in_pericope(cl: _Clusters, ctx: Context, mentions: Sequence[Mention]) -> None:
    """Each mention joins the nearest earlier compatible one in its pericope."""
    position, size = ctx.corpus.position, ctx.pericopes.size
    for a, b in zip(mentions, mentions[1:]):
        if a[0] == b[0]:
            cl.merge(a, b)
    for pericope, group in _per_pericope(ctx, mentions).items():
        for i, b in enumerate(group):
            for a in reversed(group[:i]):
                if abs(position[a[0]] - position[b[0]]) > _NEAR_VERSES \
                        and size.get(pericope, 0) > _LONG_PERICOPE:
                    break
                if cl.merge(a, b):
                    break


def _signature_index(cl: _Clusters, groups: Mapping[Mention, Sequence[Mention]]) -> dict[str, set[Mention]]:
    """Signature -> the clusters with it; a relative's new name (雅各, 以色列) is the same signature."""
    index: dict[str, set[Mention]] = defaultdict(set)
    for root in groups:
        for father in cl.fathers[root]:
            for name in (father, *cl.renamed.get(father, ())):
                index[f"fa:{name}"].add(root)
        for sign in cl.strong[root]:
            if not sign.startswith(_STRONG):
                continue
            prefix, name = sign.split(":", 1)
            spelled = cl.renamed.get(name, ()) if sign.startswith(_SPELLED_ALIKE) else ()
            for other in (name, *spelled):
                index[f"{prefix}:{other}"].add(root)
    return index


def _first_fit(cl: _Clusters, roots: Sequence[Mention]) -> list[Mention]:
    """Each cluster joins the first one it can; the clusters left, in order."""
    kept: list[Mention] = []
    for root in roots:
        if not any(cl.merge(other, root) for other in kept):
            kept.append(root)
    return kept


def _merge_one_signature(cl: _Clusters, ctx: Context, groups: Mapping[Mention, Sequence[Mention]],
                         roots: Sequence[Mention]) -> None:
    by_group: dict[str, list[Mention]] = defaultdict(list)
    for root in sorted(roots, key=repr):
        by_group[group_of(ctx, groups[root][0][0])].append(cl.find(root))
    kept = [_first_fit(cl, list(dict.fromkeys(members))) for members in by_group.values()]
    for first, second in zip(kept, kept[1:]):
        for a in first:
            for b in second:
                if len(_cross_signs(cl, a) & _cross_signs(cl, b)) >= _CROSS_TESTAMENT_SHARED:
                    cl.merge(a, b)


def _merge_shared_signature(cl: _Clusters, ctx: Context, mentions: Sequence[Mention]) -> None:
    """Until nothing changes: a merge gives a cluster the other's signatures."""
    while True:
        groups: dict[Mention, list[Mention]] = defaultdict(list)
        for m in mentions:
            groups[cl.find(m)].append(m)
        index = _signature_index(cl, groups)
        for key in sorted(index, key=lambda k: (0 if k.startswith("fa:") else 1, k)):
            _merge_one_signature(cl, ctx, groups, sorted(index[key], key=repr))
        if len({cl.find(m) for m in mentions}) == len(groups):
            return


def _cross_signs(cl: _Clusters, mention: Mention) -> set[str]:
    root = cl.find(mention)
    return cl.fathers[root] | {x for x in cl.strong[root] if x.startswith(_CROSS_TESTAMENT)}


def _merge_neighbour_pericopes(cl: _Clusters, ctx: Context, mentions: Sequence[Mention]) -> None:
    per = _per_pericope(ctx, [m for m in mentions if _in_narrative_of_the_old_testament(ctx, m[0])])
    for pericope, group in per.items():
        following = ctx.pericopes.next_id.get(pericope)
        if following in per:
            cl.merge(group[-1], per[following][0])


def _merge_parallels(cl: _Clusters, ctx: Context, mentions: Sequence[Mention]) -> None:
    per = _per_pericope(ctx, mentions)
    for pericope, group in per.items():
        for other in ctx.pericopes.parallels.get(pericope, ()):
            if other in per:
                cl.merge(group[0], per[other][0])


def _one_on_the_book_alone(cl: _Clusters, mentions: Iterable[Mention]) -> bool:
    """Sharing a book is no evidence: 赫人瑣轄 is not 西緬's 瑣轄 (a gentile, and a man with a father and none), and
    拉麥's 亞大 is not 以掃's (a woman with another husband)."""
    roots = {cl.find(m) for m in mentions}
    gentile = [r for r in roots if any(s.startswith("gent:") for s in cl.strong[r])]
    fathered_only = [r for r in roots if r not in gentile and cl.fathers[r]]
    husbands = [{s for s in cl.strong[r] if s.startswith("sp:")} for r in roots if cl.woman[r]]
    return not (gentile and fathered_only) and not any(a and b and not a & b for a in husbands for b in husbands)


def _merge_same_book(cl: _Clusters, ctx: Context, name: str, mentions: Sequence[Mention], major: bool) -> None:
    if name in ctx.kings.homonyms:
        return
    by: dict[str, list[Mention]] = defaultdict(list)
    for m in mentions:
        book = ctx.corpus.verse(m[0]).book_id
        if _in_narrative_of_the_old_testament(ctx, m[0]) and book not in _NO_BOOK_MERGE:
            by[_ONE_BOOK.get(book, book) if major else book].append(m)
    for group in by.values():
        if len(group) > 1 and not cl.conflicted(group) and _one_on_the_book_alone(cl, group):
            for m in group[1:]:
                cl.merge(group[0], m)


def _in_scope(cl_mentions: Sequence[Mention], ctx: Context, scope: str) -> list[Mention]:
    return [m for m in cl_mentions if group_of(ctx, m[0]) == scope]


def _main_cluster(cl: _Clusters, mentions: Sequence[Mention], evidence: str) -> Mention:
    """The cluster at the rename's verse, else the one with the most tokens."""
    at_evidence = [m for m in mentions if m[0] == evidence]
    if at_evidence:
        return cl.find(at_evidence[0])
    sizes = Counter(cl.find(m) for m in mentions)
    return min(sizes, key=lambda root: (-sizes[root], repr(root)))


def _merge_renames(cl: _Clusters, ctx: Context, by_surface: Mapping[str, Sequence[Mention]]) -> None:
    lent: dict[tuple[str, str], list[Mention]] = defaultdict(list)
    for rename in ctx.aliases.renames:
        old = _in_scope(by_surface.get(rename.old, ()), ctx, rename.scope)
        new = _in_scope(by_surface.get(rename.new, ()), ctx, rename.scope)
        if old and new:
            cl.merge(_main_cluster(cl, old, rename.evidence), _main_cluster(cl, new, rename.evidence))
        if rename.scope == _OLD and not cl.conflicted((*old, *new)):
            _first_fit(cl, sorted({cl.find(m) for m in (*old, *new)}, key=repr))
        for name, other in ((rename.old, rename.new), (rename.new, rename.old)):
            at_evidence = [m for m in by_surface.get(other, ()) if m[0] == rename.evidence]
            if at_evidence and not _in_scope(by_surface.get(name, ()), ctx, rename.scope):
                lent[(name, rename.scope)].append(at_evidence[0])
    for clusters in lent.values():
        _first_fit(cl, list(dict.fromkeys(cl.find(m) for m in clusters)))


def _renamed(cl: _Clusters, ctx: Context, by_surface: Mapping[str, Sequence[Mention]],
             ) -> dict[tuple[str, str], Mention]:
    """(name, scope) -> the cluster its renamed self has a row in at the evidence verse."""
    lent: dict[tuple[str, str], Mention] = {}
    for rename in ctx.aliases.renames:
        for name, other in ((rename.old, rename.new), (rename.new, rename.old)):
            at_evidence = [m for m in by_surface.get(other, ()) if m[0] == rename.evidence]
            in_scope = _in_scope(by_surface.get(name, ()), ctx, rename.scope)
            if at_evidence and not in_scope:
                lent[(name, rename.scope)] = cl.find(at_evidence[0])
    return lent


def _name_counts(c: Corpus) -> Counter[str]:
    return Counter(t.norm_key for verse in c.verses for t in verse.tokens)


def _rarest_first(by_surface: Mapping[str, Sequence[Mention]]) -> list[str]:
    return sorted(by_surface, key=lambda name: (len(by_surface[name]), name))


def _cluster(sign: Signs, ctx: Context, by_surface: Mapping[str, Sequence[Mention]]) -> _Clusters:
    """Every merge step in order; each step goes over every name before the next starts."""
    cl = _Clusters(sign, ctx.aliases)
    names = _rarest_first(by_surface)
    counts = _name_counts(ctx.corpus)
    for name in names:
        _merge_chain_and_verse(cl, ctx, by_surface[name])
    for step in (_merge_in_pericope, _merge_shared_signature, _merge_neighbour_pericopes, _merge_parallels):
        for name in names:
            step(cl, ctx, by_surface[name])
    for name in names:
        _merge_same_book(cl, ctx, name, by_surface[name], counts[name] >= _MAJOR_NAME)
    for name in names:
        _merge_shared_signature(cl, ctx, by_surface[name])
    _merge_renames(cl, ctx, by_surface)
    _first_fit(cl, sorted({cl.find(m) for m in by_surface.get(JESUS, ())}, key=repr))
    return cl


@dataclass(frozen=True)
class Identity:
    """Mentions with a kinship row, by cluster; and how a mention without one is resolved."""

    node_of_mention: Mapping[Mention, Mention]
    surface: Mapping[Mention, str]
    female: frozenset[str]
    in_pericope: Mapping[tuple[str, str | None], frozenset[Mention]]
    in_book: Mapping[tuple[str, str], frozenset[Mention]]
    in_group: Mapping[tuple[str, str], frozenset[Mention]]
    major: frozenset[str]                              # names mentioned 30 times or more
    thin: frozenset[Mention]                           # clusters with rows in one pericope
    few_books: frozenset[Mention]                      # clusters with rows in fewer than three books
    both_sexes: frozenset[Mention]                     # clusters a row writes as a man and one as a woman
    renamed: Mapping[tuple[str, str], Mention]

    def _in_narrative(self, name: str, book: str | None) -> Mention | None:
        whole = self.in_group.get((name, _NARRATIVE), frozenset())
        if len(whole) != 1 or next(iter(whole)) in self.thin:
            return None
        return next(iter(whole)) if name in self.major or (name, book) in self.in_book else None

    def _in_book_or_group(self, name: str, place: Place) -> Mention | None:
        in_book = self.in_book.get((name, place.book), frozenset())
        if len(in_book) == 1:
            return next(iter(in_book))
        whole = self.in_group.get((name, place.group), frozenset())
        if name not in self.major or len(whole) != 1 or next(iter(whole)) in self.few_books:
            return None
        return next(iter(whole))

    def node_of(self, mention: Mention, name: str, place: Place) -> Mention | None:
        """The cluster of a token, with a kinship row or without (``place_of``)."""
        direct = self.node_of_mention.get(mention)
        if direct is not None:
            return direct
        here = self.in_pericope.get((name, place.pericope)) if place.pericope is not None else None
        if here and len(here) == 1:
            return next(iter(here))
        found = (self._in_narrative(name, place.book) if in_narrative(place)
                 else self._in_book_or_group(name, place))
        return found if found is not None else self.renamed.get((name, place.group))


def _spread(nodes: Mapping[Mention, Mention], ctx: Context) -> tuple[frozenset[Mention], frozenset[Mention]]:
    """The clusters with rows in one pericope, and those with rows in fewer than three books."""
    pericopes: dict[Mention, set[str | None]] = defaultdict(set)
    books: dict[Mention, set[str]] = defaultdict(set)
    for mention, node in nodes.items():
        pericopes[node].add(ctx.pericopes.of_unit.get(mention[0]))
        books[node].add(ctx.corpus.verse(mention[0]).book_id)
    return (frozenset(n for n, found in pericopes.items() if len(found) < _MIN_PERICOPES_IN_NARRATIVE),
            frozenset(n for n, found in books.items() if len(found) < _MIN_BOOKS_IN_GROUP))


def identify(rows: Sequence[KinRow], ctx: Context) -> Identity:
    sign = signs_of(rows, ctx.corpus, ctx.kings)
    by_surface = _by_surface(sign, ctx.corpus)
    cl = _cluster(sign, ctx, by_surface)
    nodes = {m: cl.find(m) for m in sign.surface}
    counts = _name_counts(ctx.corpus)
    in_pericope: dict[tuple[str, str | None], set[Mention]] = defaultdict(set)
    in_book: dict[tuple[str, str], set[Mention]] = defaultdict(set)
    in_group: dict[tuple[str, str], set[Mention]] = defaultdict(set)
    for m, node in nodes.items():
        name = sign.surface[m]
        in_pericope[(name, ctx.pericopes.of_unit.get(m[0]))].add(node)
        in_book[(name, ctx.corpus.verse(m[0]).book_id)].add(node)
        in_group[(name, group_of(ctx, m[0]))].add(node)
    both = frozenset(n for n in set(nodes.values()) if cl.woman[n] and cl.man[n])
    return Identity(nodes, sign.surface, sign.female,
                    {k: frozenset(v) for k, v in in_pericope.items()},
                    {k: frozenset(v) for k, v in in_book.items()},
                    {k: frozenset(v) for k, v in in_group.items()},
                    frozenset(name for name in by_surface if counts[name] >= _MAJOR_NAME),
                    *_spread(nodes, ctx), both, _renamed(cl, ctx, by_surface))

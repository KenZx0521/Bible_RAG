"""K4's mechanical rules (Kay 2026-10-08, DOC 2 g): which terms the router may see, which
route types a target counts as, and which book forms the router masks.

Each rule has an id; the lexicon header carries their one-line descriptions (``RULES``).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ragcommon import books
from ragdata.contract.kg import ROUTE_TYPES
from ragdata.stages.errors import StageError

RULES = {
    "rt.dotless": "kg0 名稱含「‧」者另收去掉「‧」的寫法；該寫法已是別的詞時不收",
    "rt.min_len": "少於 2 字的詞不可路由",
    "rt.common_word": "名稱在 PDF 經文中落在底線外的次數 ≥3 且多於底線內，不可路由",
    "rt.untyped_place": "kg0 名稱沒有型別候選時算地點（L2 之前的暫行規則）",
    "rt.divine_person": "耶穌的稱呼（含人子、救主、基督）同指耶穌一人，法老另算一人；"
                        "耶和華、上帝、聖靈、主、神不算",
    "rt.book_forms": "書名：ragcommon.books 的 66 個正式名，加 18 個縮寫與異名",
    "rt.exclude_context": "命中處落在排除語境裏不算命中",
}
MIN_LEN = 2
COMMON_MIN_OUTSIDE = 3
# rt.divine_person: surface -> the person it names (whose pattern is the target). The titles of
# Jesus are one person, as legacy's 耶穌 and its aliases were, so two of them are no R3.
DIVINE_PERSON = {**dict.fromkeys(("主耶穌基督", "主耶穌", "耶穌基督", "基督耶穌", "耶穌", "基督",
                                  "人子", "救主"), "耶穌"), "法老": "法老"}
DIVINE_NONE = ("主耶和華", "耶和華", "上帝", "聖靈", "主", "神")
EXTRA_BOOK_FORMS = ("撒上", "撒下", "王上", "王下", "代上", "代下", "林前", "林後", "帖前", "帖後",
                    "提前", "提後", "彼前", "彼後", "約一", "約二", "約三", "尼西米記")
FULL_NAME_KINDS = ("name", "name_variant")


@dataclass(frozen=True)
class BookForm:
    surface: str
    book_id: str
    kind: str          # the ragcommon.books kind of the form


def book_forms() -> list[BookForm]:
    """rt.book_forms in router order: longer first, then full names before abbreviations,
    then canon order (``match_books`` keeps the first form of each book)."""
    forms = [BookForm(b.name, b.book_id, "name") for b in books.all_books()]
    for text in EXTRA_BOOK_FORMS:
        found = books.lookup_name(text)
        if found is None:
            raise StageError(f"rt.book_forms: {text} is no ragcommon book name")
        forms.append(BookForm(text, found.book_id, found.kind))
    return sorted(forms, key=lambda f: (-len(f.surface), f.kind not in FULL_NAME_KINDS,
                                        books.get_book(f.book_id).ord, f.surface))


def name_route_types(candidates: Iterable[str]) -> list[str]:
    """rt.untyped_place: a kg0 name counts as its Person/Place candidates, Place if it has none."""
    found = list(candidates)
    return sorted(set(found) & set(ROUTE_TYPES)) if found else ["Place"]


def divine_route_types(surface: str) -> list[str]:
    """rt.divine_person; a surface in neither table must be classified before K4 builds."""
    if surface in DIVINE_PERSON:
        return ["Person"]
    if surface in DIVINE_NONE:
        return []
    raise StageError(f"rt.divine_person: divine surface {surface} is in neither "
                     "DIVINE_PERSON nor DIVINE_NONE; classify it in kg/k4_rules.py")


def divine_person(surface: str) -> str:
    """rt.divine_person: the divine surface whose pattern ``surface`` stands for."""
    return DIVINE_PERSON.get(surface, surface)


@dataclass(frozen=True)
class Verses:
    """The PDF verse text in one string, and each unit's underlined body spans."""

    corpus: str
    starts: tuple[int, ...]                              # offset of each unit in corpus
    spans: tuple[tuple[tuple[int, int], ...], ...]       # per unit, its (start, end) spans


def verses(units: Sequence, name_spans: Iterable) -> Verses:
    body: dict[str, list[tuple[int, int]]] = {}
    for s in name_spans:
        if s.region == "body":
            body.setdefault(s.container_id, []).append((s.start, s.end))
    starts, offset = [], 0
    for u in units:
        starts.append(offset)
        offset += len(u.text_pdf) + 1
    return Verses("\n".join(u.text_pdf for u in units), tuple(starts),
                  tuple(tuple(body.get(u.unit_key, ())) for u in units))


def occurrences(key: str, text: Verses) -> tuple[int, int]:
    """(raw, inside): overlapping occurrences of ``key`` in the verses, and those lying
    within an underlined span of the unit."""
    raw = inside = 0
    i = text.corpus.find(key)
    while i != -1:
        unit = bisect.bisect_right(text.starts, i) - 1
        local = i - text.starts[unit]
        raw += 1
        inside += any(a <= local and local + len(key) <= b for a, b in text.spans[unit])
        i = text.corpus.find(key, i + 1)
    return raw, inside


def common_words(keys: Iterable[str], text: Verses) -> dict[str, dict[str, int]]:
    """rt.common_word over kg0 name keys of 2+ characters: the PDF prints them outside an
    underline at least 3 times and more often than inside one."""
    found = {}
    for key in keys:
        if len(key) < MIN_LEN:
            continue
        raw, inside = occurrences(key, text)
        outside = raw - inside
        if outside >= COMMON_MIN_OUTSIDE and outside > inside:
            found[key] = {"raw": raw, "inside": inside, "outside": outside}
    return found


def unroutable_rule(surface: str, kind: str, common: Mapping[str, object]) -> str | None:
    if len(surface) < MIN_LEN:
        return "rt.min_len"
    if kind == "name" and surface in common:
        return "rt.common_word"
    return None

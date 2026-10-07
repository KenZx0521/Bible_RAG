"""Parse Chinese scripture references into verse ranges (G63; G05 false hits).

Two entry points:

``parse_refs(text)``
    The whole string is a reference expression (a GT ``reference`` field, a PDF
    parallel-reference bracket, a footnote cross-reference). Everything must be
    consumed. ``strict=True`` raises ``RefParseError``; otherwise the result is
    empty and carries the reason.

``find_refs(text)``
    Scan free text (a user question) for embedded references. Abbreviations
    count only when a number follows immediately and is itself followed by
    ``:`` or ``章``/``篇`` (single-character ones need Arabic digits), so
    「約3天」「拿5個餅」「提前」「王上」 are not references. Before ``N章``/``N篇``
    a single-character abbreviation must also not end a word: the character
    before it is absent, non-Han or a lead such as 見、參、在, so
    「後來3章」「列出3章」「全書約3章」 are not references. An item written
    with Chinese numerals must end in ``章``/``篇``/``節``, and a bare trailing
    number followed by a measure word (天、個、歲…) is a quantity. Ambiguous
    names (提摩太) and words such as 大約、本書 never start a reference.
    Matches that name no existing verse are returned as ``rejected``.

Accepted forms: full names, PDF and colloquial abbreviations, ``3:16``,
``3：16``, full-width digits, ``3‧16``, ranges with ``-－–—~～至到``,
cross-chapter ``1:1-2:3``, chapter ranges ``7-8章``, ``第3章3節``, Chinese
numerals before ``章``/``篇``/``節``, ``3:16a`` (half-verse suffixes are read
as the whole verse), lists with ``、，,`` and ``；`` (a following segment
without a book keeps the previous book), ``篇`` as ``章`` in Psalms. A bare
number continues the verses of the current chapter after a verse-level item,
names a chapter otherwise, and is a verse in single-chapter books.

Every reference is checked against the PDF verse grid; external verse numbers
go through ref_aliases (``jhn.7.53`` → ``jhn.8.1``) and anything else raises.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache

from ragcommon import _reflex as lx
from ragcommon import books, ids
from ragcommon.versification import Versification, VersificationError, default_versification

# Common words that end in a book abbreviation (大約 → 約, 本書 → 書).
FALSE_FRIENDS = ("大約", "共約", "本書", "該書", "此書", "全書", "卷書")
# Han characters allowed right before a single-character abbreviation + N章 (見約3章).
LEAD_CHARS = frozenset("見參在和與及或")
# A bare trailing number followed by one of these is a quantity, not a verse.
GUARD_CHARS = frozenset("天年月日歲個次人位名隻頭匹條張本卷首元塊分秒點時斤里尺倍萬千號週周代層段句.%")
_OPEN, _CLOSE = "（(［[【〔", "）)］]】〕"
_SEPARATORS = (lx.COMMA, lx.SEMI)


class RefParseError(ValueError):
    """A reference expression that cannot be parsed or does not exist."""

    def __init__(self, reason: str, text: object = None):
        super().__init__(f"{reason}: {text!r}" if text is not None else reason)
        self.reason = reason
        self.text = text


@dataclass(frozen=True)
class VerseRef:
    """``ch:v_start`` to ``ch_end:v_end``; verses None means whole chapters."""

    book_id: str
    ch: int
    v_start: int | None
    v_end: int | None
    ch_end: int

    @property
    def is_whole_chapter(self) -> bool:
        return self.v_start is None

    def to_dict(self) -> dict[str, object]:
        return {"book_id": self.book_id, "ch": self.ch, "v_start": self.v_start,
                "v_end": self.v_end, "ch_end": self.ch_end}


@dataclass(frozen=True)
class ParseResult:
    refs: tuple[VerseRef, ...]
    reason: str | None = None
    aliases_applied: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.reason is None

    def to_dicts(self) -> list[dict[str, object]]:
        return [ref.to_dict() for ref in self.refs]


@dataclass(frozen=True)
class RefMatch:
    start: int
    end: int
    raw: str
    refs: tuple[VerseRef, ...]
    aliases_applied: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefRejection:
    """Text shaped like a reference that names no existing verse."""

    start: int
    end: int
    raw: str
    reason: str


@dataclass(frozen=True)
class FindResult:
    matches: tuple[RefMatch, ...]
    rejected: tuple[RefRejection, ...]

    @property
    def refs(self) -> tuple[VerseRef, ...]:
        return tuple(ref for match in self.matches for ref in match.refs)


@dataclass(frozen=True)
class _Ctx:
    book_id: str | None = None
    single: bool = False          # single-chapter book: bare numbers are verses
    chapter: int | None = None    # chapter that a bare verse number continues
    verse_level: bool = False     # the previous item named verses


class _Fail(Exception):
    def __init__(self, message: str, index: int):
        super().__init__(message)
        self.message = message
        self.index = index


# ---------------------------------------------------------------- grammar


def _kind(toks: tuple[lx.Token, ...], i: int) -> str | None:
    return toks[i].kind if i < len(toks) else None


def _skip(toks: tuple[lx.Token, ...], i: int, kind: str) -> int:
    return i + 1 if _kind(toks, i) == kind else i


def _tail(toks: tuple[lx.Token, ...], i: int) -> int:
    """Skip an optional half-verse suffix and an optional 節."""
    return _skip(toks, _skip(toks, i, lx.SUFFIX), lx.VERSE)


def _number(toks: tuple[lx.Token, ...], i: int) -> tuple[int, int]:
    if _kind(toks, i) != lx.NUM:
        raise _Fail("expected a number", i)
    if toks[i].value is None:
        raise _Fail("malformed Chinese numeral", i)
    return toks[i].value, i + 1


def _marker(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx) -> None:
    if toks[i].value == "篇" and ctx.book_id != "psa":
        raise _Fail("篇 marks chapters only in Psalms", i)


def _chapters(ctx: _Ctx, first: int, last: int, i: int):
    return VerseRef(ctx.book_id, first, None, None, last), i, replace(ctx, chapter=last, verse_level=False)


def _verses(ctx: _Ctx, chapter: int, first: int, last: int, i: int, chapter_end: int | None = None):
    end = chapter if chapter_end is None else chapter_end
    return VerseRef(ctx.book_id, chapter, first, last, end), i, replace(ctx, chapter=end, verse_level=True)


def _bare(ctx: _Ctx, first: int, last: int, i: int):
    if ctx.single:
        return _verses(ctx, 1, first, last, i)
    if ctx.verse_level:
        return _verses(ctx, ctx.chapter, first, last, i)
    return _chapters(ctx, first, last, i)


def _explicit_verses(ctx: _Ctx, first: int, last: int, i: int):
    chapter = 1 if ctx.single else ctx.chapter
    if chapter is None:
        raise _Fail("verse number without a chapter", i)
    return _verses(ctx, chapter, first, last, i)


def _cross_chapter(toks: tuple[lx.Token, ...], j: int, ctx: _Ctx) -> bool:
    if _kind(toks, j) == lx.COLON:
        return True
    if _kind(toks, j) == lx.CHAP and _kind(toks, _skip(toks, j + 1, lx.DI)) == lx.NUM:
        _marker(toks, j, ctx)
        return True
    return False


def _chapter_verse(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx, ch: int):
    """After ``ch:`` or ``ch章``: a verse, a verse range, or a cross-chapter range."""
    v, i = _number(toks, _skip(toks, i, lx.DI))
    i = _tail(toks, i)
    if _kind(toks, i) != lx.DASH or _kind(toks, _skip(toks, i + 1, lx.DI)) != lx.NUM:
        return _verses(ctx, ch, v, v, i)
    n, j = _number(toks, _skip(toks, i + 1, lx.DI))
    if _cross_chapter(toks, j, ctx):
        v_end, k = _number(toks, _skip(toks, j + 1, lx.DI))
        return _verses(ctx, ch, v, v_end, _tail(toks, k), chapter_end=n)
    return _verses(ctx, ch, v, n, _tail(toks, j))


def _chapter_range(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx, first: int):
    """After ``N章``: optionally ``-M章``."""
    j = _skip(toks, i + 1, lx.DI)
    if _kind(toks, i) != lx.DASH or _kind(toks, j) != lx.NUM:
        return _chapters(ctx, first, first, i)
    last, j = _number(toks, j)
    if _kind(toks, j) == lx.CHAP:
        _marker(toks, j, ctx)
        j += 1
    return _chapters(ctx, first, last, j)


def _after_dash(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx, first: int):
    """After ``N-``: a chapter range, a verse range, or a bare range."""
    j = _skip(toks, i + 1, lx.DI)
    if _kind(toks, j) != lx.NUM or _kind(toks, j + 1) == lx.COLON:
        return _bare(ctx, first, first, i)   # stop before the dash
    last, j = _number(toks, j)
    if _kind(toks, j) == lx.CHAP:
        _marker(toks, j, ctx)
        return _chapters(ctx, first, last, j + 1)
    if _kind(toks, j) in (lx.VERSE, lx.SUFFIX):
        return _explicit_verses(ctx, first, last, _tail(toks, j))
    return _bare(ctx, first, last, j)


def _item(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx):
    """One reference item; returns (VerseRef, next index, next context)."""
    first, i = _number(toks, _skip(toks, i, lx.DI))
    kind = _kind(toks, i)
    if kind == lx.COLON:
        return _chapter_verse(toks, i + 1, ctx, first)
    if kind == lx.CHAP:
        _marker(toks, i, ctx)
        if _kind(toks, _skip(toks, i + 1, lx.DI)) == lx.NUM:
            return _chapter_verse(toks, i + 1, ctx, first)
        return _chapter_range(toks, i + 1, ctx, first)
    if kind == lx.DASH:
        return _after_dash(toks, i, ctx, first)
    if kind in (lx.VERSE, lx.SUFFIX):
        return _explicit_verses(ctx, first, first, _tail(toks, i))
    return _bare(ctx, first, first, i)


# ---------------------------------------------------------------- validation


def _validate(ref: VerseRef, vers: Versification) -> tuple[VerseRef, tuple[str, ...]]:
    count = vers.chapter_count(ref.book_id)
    if ref.ch > ref.ch_end:
        raise RefParseError(f"range runs backwards (chapter {ref.ch} > {ref.ch_end})")
    if ref.ch < 1 or ref.ch_end > count:
        raise RefParseError(f"{ref.book_id} has chapters 1-{count}, not {ref.ch}-{ref.ch_end}")
    if ref.v_start is None:
        return ref, ()
    try:
        start, alias_start = vers.resolve(ref.book_id, ref.ch, ref.v_start)
        end, alias_end = vers.resolve(ref.book_id, ref.ch_end, ref.v_end)
    except VersificationError as exc:
        raise RefParseError(str(exc)) from None
    first, last = ids.parse(start), ids.parse(end)
    if (first.chapter, first.verse) > (last.chapter, last.verse):
        raise RefParseError(f"range runs backwards ({start} > {end})")
    applied = tuple(f"{a.external_ref}->{a.target}" for a in (alias_start, alias_end) if a)
    return VerseRef(ref.book_id, first.chapter, first.verse, last.verse, last.chapter), applied


def _validate_all(raw: list[VerseRef], vers: Versification) -> tuple[tuple[VerseRef, ...], tuple[str, ...]]:
    checked = [_validate(ref, vers) for ref in raw]
    aliases = tuple(dict.fromkeys(a for _, applied in checked for a in applied))
    return tuple(ref for ref, _ in checked), aliases


def expand_slots(ref: VerseRef, versification: Versification | None = None) -> tuple[str, ...]:
    """Every PDF slot key a (validated) reference covers, in order."""
    vers = versification or default_versification()
    keys = []
    for ch in range(ref.ch, ref.ch_end + 1):
        first = ref.v_start if ch == ref.ch and ref.v_start is not None else 1
        last = ref.v_end if ch == ref.ch_end and ref.v_end is not None else vers.max_verse(ref.book_id, ch)
        keys.extend(f"{ref.book_id}.{ch}.{v}" for v in range(first, last + 1))
    return tuple(keys)


# ---------------------------------------------------------------- parse_refs


def _alternation(texts) -> str:
    return "|".join(re.escape(t) for t in sorted(texts, key=lambda t: (-len(t), t)))


@lru_cache(maxsize=1)
def _book_regex() -> re.Pattern[str]:
    table = books.default_books()
    return re.compile(_alternation(list(table.names) + list(table.ambiguous)))


def _match_book(text: str, pos: int) -> lx.Token | None:
    m = _book_regex().match(text, pos)
    if not m:
        return None
    name = books.lookup_name(m.group())
    if name is None:
        return lx.Token(lx.AMBIGUOUS, pos, m.end(), m.group())
    return lx.Token(lx.BOOK, pos, m.end(), name)


def _book_ctx(book_id: str, vers: Versification) -> _Ctx:
    return _Ctx(book_id=book_id, single=vers.chapter_count(book_id) == 1)


def _piece(toks: tuple[lx.Token, ...], i: int, ctx: _Ctx, vers: Versification):
    """An optional book name followed by one item; a full name alone is the whole book."""
    if _kind(toks, i) == lx.AMBIGUOUS:
        raise _Fail(f"ambiguous book name {toks[i].value}", i)
    if _kind(toks, i) == lx.BOOK:
        name = toks[i].value
        ctx, i = _book_ctx(name.book_id, vers), i + 1
        if _kind(toks, i) not in (lx.NUM, lx.DI):
            if name.is_abbreviation:
                raise _Fail(f"abbreviation {name.text} alone is not a reference", i - 1)
            whole = VerseRef(name.book_id, 1, None, None, vers.chapter_count(name.book_id))
            return whole, i, ctx
    if ctx.book_id is None:
        raise _Fail("reference without a book", i)
    return _item(toks, i, ctx)


def _parse_tokens(toks: tuple[lx.Token, ...], ctx: _Ctx, vers: Versification) -> list[VerseRef]:
    out: list[VerseRef] = []
    i = 0
    while True:
        ref, i, ctx = _piece(toks, i, ctx, vers)
        out.append(ref)
        if i == len(toks):
            return out
        if toks[i].kind not in _SEPARATORS or i + 1 == len(toks):
            raise _Fail("unexpected token", i)
        i += 1


def _strip_wrapper(text: str) -> str:
    text = text.strip().rstrip("。").strip()
    if len(text) >= 2 and text[0] in _OPEN and text[-1] in _CLOSE:
        text = text[1:-1].strip()
    return text


def _describe(norm: str, toks: tuple[lx.Token, ...], exc: _Fail) -> str:
    if exc.index >= len(toks):
        return f"{exc.message} at end"
    tok = toks[exc.index]
    return f"{exc.message} {norm[tok.start:tok.end]!r} at {tok.start}"


def _parse(text: object, default_book: str | None, vers: Versification) -> ParseResult:
    if not isinstance(text, str):
        raise RefParseError("reference must be a string", text)
    norm = _strip_wrapper(lx.normalize(text))
    if not norm:
        raise RefParseError("empty reference", text)
    toks, stop = lx.tokenize(norm, 0, _match_book)
    if stop != len(norm):
        raise RefParseError(f"unexpected {norm[stop]!r} at {stop}", text)
    ctx = _book_ctx(default_book, vers) if default_book else _Ctx()
    try:
        raw = _parse_tokens(toks, ctx, vers)
    except _Fail as exc:
        raise RefParseError(_describe(norm, toks, exc), text) from None
    try:
        refs, aliases = _validate_all(raw, vers)
    except RefParseError as exc:
        raise RefParseError(exc.reason, text) from None
    return ParseResult(refs, None, aliases)


def parse_refs(text: str, *, strict: bool = False, default_book: str | None = None,
               versification: Versification | None = None) -> ParseResult:
    """Parse a whole reference expression; see the module docstring."""
    if default_book is not None and not books.is_book_id(default_book):
        raise ValueError(f"unknown default_book {default_book!r}")
    try:
        return _parse(text, default_book, versification or default_versification())
    except RefParseError as exc:
        if strict:
            raise
        return ParseResult(refs=(), reason=str(exc))


# ---------------------------------------------------------------- find_refs


@lru_cache(maxsize=1)
def _find_regex() -> re.Pattern[str]:
    table = books.default_books()
    return re.compile(_alternation(list(table.names) + list(table.ambiguous) + list(FALSE_FRIENDS)))


def _is_han(ch: str) -> bool:
    return unicodedata.name(ch, "").startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))


def _starts_word(before: str) -> bool:
    """True unless ``before`` is a Han character that may end a word with the abbreviation."""
    return not before or before in LEAD_CHARS or not _is_han(before)


def _lead_ok(toks: tuple[lx.Token, ...], name: books.BookName, book_end: int, before: str) -> bool:
    """Abbreviations need ``N:`` or ``N章`` right after them.

    Single-character ones also need Arabic digits, and before ``N章``/``N篇``
    they must not be the tail of a word (後來3章, 列出3章, 全書約3章): the
    character ``before`` them must be absent, non-Han or one of LEAD_CHARS.
    """
    if not name.is_abbreviation:
        return True
    if len(toks) < 2 or toks[0].kind != lx.NUM or toks[0].start != book_end:
        return False
    if toks[1].kind not in (lx.COLON, lx.CHAP):
        return False
    if len(name.text) > 1:
        return True
    return toks[0].arabic and (toks[1].kind == lx.COLON or _starts_word(before))


def _plausible(norm: str, toks: tuple[lx.Token, ...], i: int, j: int) -> bool:
    """Free-text checks: Chinese numerals need a closing 章/篇/節; no quantity after a bare number."""
    last = toks[j - 1]
    if last.kind in (lx.CHAP, lx.VERSE):
        return True
    if any(t.kind == lx.NUM and not t.arabic for t in toks[i:j]):
        return False
    following = norm[last.end:].lstrip()[:1]
    return following not in GUARD_CHARS and not (following.isascii() and following.isalnum())


def _scan_items(norm: str, toks: tuple[lx.Token, ...], ctx: _Ctx) -> tuple[list[VerseRef], int] | None:
    out: list[VerseRef] = []
    i, end = 0, 0
    while True:
        try:
            ref, j, next_ctx = _item(toks, i, ctx)
        except _Fail:
            break
        if not _plausible(norm, toks, i, j):
            break
        out.append(ref)
        ctx, end, i = next_ctx, toks[j - 1].end, j
        if _kind(toks, i) not in _SEPARATORS:
            break
        i += 1
    return (out, end) if out else None


def _scan_at(norm: str, m: re.Match[str], vers: Versification) -> tuple[list[VerseRef], int] | None:
    name = books.lookup_name(m.group())
    if name is None:   # ambiguous name or false friend
        return None
    toks, _ = lx.tokenize(norm, m.end())
    if not _lead_ok(toks, name, m.end(), norm[max(m.start() - 1, 0):m.start()]):
        return None
    return _scan_items(norm, toks, _book_ctx(name.book_id, vers))


def find_refs(text: str, *, versification: Versification | None = None) -> FindResult:
    """Find references embedded in free text; see the module docstring."""
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text).__name__}")
    vers = versification or default_versification()
    norm = lx.normalize(text)
    matches: list[RefMatch] = []
    rejected: list[RefRejection] = []
    pos = 0
    while (m := _find_regex().search(norm, pos)) is not None:
        hit = _scan_at(norm, m, vers)
        if hit is None:
            pos = m.end()
            continue
        raw_refs, end = hit
        raw = text[m.start():end]
        try:
            refs, aliases = _validate_all(raw_refs, vers)
            matches.append(RefMatch(m.start(), end, raw, refs, aliases))
        except RefParseError as exc:
            rejected.append(RefRejection(m.start(), end, raw, exc.reason))
        pos = end
    return FindResult(tuple(matches), tuple(rejected))

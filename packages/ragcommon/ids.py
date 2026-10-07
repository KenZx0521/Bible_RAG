"""Id grammar for every record kind (design §3.1): build, parse and validate.

This module is the only place that knows how ids are spelled. Consumers call
``parse()`` instead of splitting on ``:`` (design §3.2). Every id is ASCII with
no whitespace; keys that carry Han text (mention keys) are not ids and are
hashed into ``mn:`` ids.

Verse-shaped ids have three spellings, distinguished by ``ParsedId.kind``:
``slot`` (``jhn.3.16``), ``unit`` (merged label, ``eph.6.2-3``) and ``key``
(half verse, ``act.9.19b``). The roles ``unit`` and ``key`` also accept a plain
slot, because a single-verse unit and a whole-verse key are spelled as a slot.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable
from urllib.parse import quote, unquote

from ragcommon import books

NS_RAG = uuid.UUID("ef6733ee-5a28-5e83-9074-de6e229eb380")
LAYERS = ("src", "text", "struct", "emb", "kg0", "events", "route", "identity", "relations")
RELATION_TYPES = frozenset({"PARENT_OF", "SPOUSE_OF", "SUCCEEDED"})
LEGACY_BUILD_ID = "legacy-20261004"

KINDS = frozenset({
    "book", "chapter", "slot", "unit", "key", "superscription", "division", "heading",
    "parallel_ref", "footnote", "speaker", "name_span", "merge_group", "pericope",
    "passage", "chunk", "verse_record", "name", "mention", "entity", "event",
    "relation", "decision", "layer_version", "build",
})
ROLES = MappingProxyType({"unit": frozenset({"slot", "unit"}), "key": frozenset({"slot", "key"})})
CONTAINER_KINDS = frozenset({
    "slot", "unit", "superscription", "division", "heading", "footnote", "speaker",
})

_POS = r"[1-9][0-9]*"
_VERSE_RE = re.compile(rf"([0-9a-z]{{3}})\.({_POS})\.({_POS})(?:-({_POS})|(b))?")
_CHAPTER_RE = re.compile(rf"([0-9a-z]{{3}})\.({_POS})")
_BOOK_RE = re.compile(r"[0-9a-z]{3}")
_SEQ_RE = re.compile(rf"(.+)#({_POS})")
_OFFSET_RE = re.compile(r"(.+)@(0|[1-9][0-9]*)")
_MG_RE = re.compile(rf"((?:%[0-9A-F]{{2}}|[A-Za-z0-9._~-])+)#({_POS})")
_ENTITY_RE = re.compile(r"e([0-9]{6})")
_EVENT_RE = re.compile(r"ev([0-9]{4})")
_LAYER_RE = re.compile(r"([a-z0-9]+)@([0-9a-f]{12})")
_BUILD_RE = re.compile(r"b([0-9]{8})_([0-9a-f]{8})")
_LEGACY_RE = re.compile(r"legacy-([0-9]{8})")
_HEX_RE = re.compile(r"[0-9a-f]+")
_DIGEST_LEN = {"nm": 12, "mn": 16, "rl": 16, "dc": 16}
_DIGEST_KIND = {"nm": "name", "mn": "mention", "rl": "relation", "dc": "decision"}


class IdError(ValueError):
    """An id (or a builder argument) does not follow the grammar."""


@dataclass(frozen=True)
class ParsedId:
    """A parsed id. Fields that do not apply to the kind stay None.

    Ids anchored on a verse or chapter (headings, footnotes, passages, …) copy
    the anchor's book/chapter/verse fields up for convenience; ``parent`` keeps
    the full nested id.
    """

    kind: str
    raw: str
    book_id: str | None = None
    chapter: int | None = None
    verse: int | None = None
    verse_end: int | None = None
    half: bool = False
    seq: int | None = None
    offset: int | None = None
    parent: ParsedId | None = None
    end: ParsedId | None = None
    text: str | None = None
    digest: str | None = None
    date: str | None = None


# ---------------------------------------------------------------- parsing


def _book(book_id: str) -> str:
    if not books.is_book_id(book_id):
        raise IdError(f"unknown book id {book_id!r}")
    return book_id


def _date8(text: str) -> str:
    try:
        _dt.datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise IdError(f"invalid date {text!r}") from exc
    return text


def _parse_book(raw: str) -> ParsedId | None:
    if not _BOOK_RE.fullmatch(raw):
        return None
    return ParsedId("book", raw, book_id=_book(raw))


def _parse_chapter(raw: str) -> ParsedId | None:
    m = _CHAPTER_RE.fullmatch(raw)
    if not m:
        return None
    return ParsedId("chapter", raw, book_id=_book(m.group(1)), chapter=int(m.group(2)))


def _parse_verse(raw: str) -> ParsedId | None:
    m = _VERSE_RE.fullmatch(raw)
    if not m:
        return None
    fields = {"book_id": _book(m.group(1)), "chapter": int(m.group(2)), "verse": int(m.group(3))}
    if m.group(4) is not None:
        verse_end = int(m.group(4))
        if verse_end <= fields["verse"]:
            raise IdError(f"merged label must ascend: {raw!r}")
        return ParsedId("unit", raw, verse_end=verse_end, **fields)
    if m.group(5):
        return ParsedId("key", raw, half=True, **fields)
    return ParsedId("slot", raw, **fields)


def _parse_counter(raw: str) -> ParsedId | None:
    for pattern, kind in ((_ENTITY_RE, "entity"), (_EVENT_RE, "event")):
        m = pattern.fullmatch(raw)
        if m:
            if int(m.group(1)) == 0:
                raise IdError(f"sequence numbers start at 1: {raw!r}")
            return ParsedId(kind, raw, seq=int(m.group(1)))
    return None


def _parse_version(raw: str) -> ParsedId | None:
    m = _LAYER_RE.fullmatch(raw)
    if m:
        if m.group(1) not in LAYERS:
            raise IdError(f"unknown layer {m.group(1)!r}")
        return ParsedId("layer_version", raw, text=m.group(1), digest=m.group(2))
    m = _BUILD_RE.fullmatch(raw)
    if m:
        return ParsedId("build", raw, date=_date8(m.group(1)), digest=m.group(2))
    m = _LEGACY_RE.fullmatch(raw)
    if m:
        return ParsedId("build", raw, date=_date8(m.group(1)), text="legacy")
    return None


_UNPREFIXED = (_parse_book, _parse_chapter, _parse_verse, _parse_counter, _parse_version)


def _require(text: str, kind: str, outer: str) -> ParsedId:
    parsed = parse(text)
    if not _matches(parsed, kind):
        raise IdError(f"{outer!r}: expected a {kind} inside, got {parsed.kind}")
    return parsed


def _anchored(kind: str, raw: str, inner: ParsedId, **extra) -> ParsedId:
    return ParsedId(
        kind, raw, book_id=inner.book_id, chapter=inner.chapter, verse=inner.verse,
        verse_end=inner.verse_end, half=inner.half, parent=inner, **extra,
    )


def _split(pattern: re.Pattern[str], rest: str, raw: str) -> tuple[str, int]:
    m = pattern.fullmatch(rest)
    if not m:
        raise IdError(f"malformed id {raw!r}")
    return m.group(1), int(m.group(2))


def _chapter_text(kind: str) -> Callable[[str, str], ParsedId]:
    def handler(raw: str, rest: str) -> ParsedId:
        return _anchored(kind, raw, _require(rest, "chapter", raw))
    return handler


def _numbered(kind: str, inner_kind: str) -> Callable[[str, str], ParsedId]:
    def handler(raw: str, rest: str) -> ParsedId:
        inner, seq = _split(_SEQ_RE, rest, raw)
        return _anchored(kind, raw, _require(inner, inner_kind, raw), seq=seq)
    return handler


def _keyed(kind: str, inner_kind: str) -> Callable[[str, str], ParsedId]:
    def handler(raw: str, rest: str) -> ParsedId:
        return _anchored(kind, raw, _require(rest, inner_kind, raw))
    return handler


def _parse_name_span(raw: str, rest: str) -> ParsedId:
    container, offset = _split(_OFFSET_RE, rest, raw)
    inner = parse(container)
    if inner.kind not in CONTAINER_KINDS:
        raise IdError(f"{raw!r}: {inner.kind} cannot contain name spans")
    return _anchored("name_span", raw, inner, offset=offset)


def _parse_merge_group(raw: str, rest: str) -> ParsedId:
    m = _MG_RE.fullmatch(rest)
    if not m:
        raise IdError(f"malformed merge group id {raw!r}")
    try:
        surface = unquote(m.group(1), errors="strict")
    except UnicodeDecodeError as exc:
        raise IdError(f"bad percent-encoding in {raw!r}") from exc
    if quote(surface, safe="") != m.group(1):
        raise IdError(f"non-canonical percent-encoding in {raw!r}")
    return ParsedId("merge_group", raw, text=surface, seq=int(m.group(2)))


def _key_order(parsed: ParsedId) -> tuple[int, int, bool]:
    return (parsed.chapter, parsed.verse, parsed.half)


def _parse_chunk(raw: str, rest: str) -> ParsedId:
    parts = rest.split("~")
    if len(parts) != 2:
        raise IdError(f"chunk id needs start~end: {raw!r}")
    start, end = (_require(p, "key", raw) for p in parts)
    if start.book_id != end.book_id or _key_order(start) > _key_order(end):
        raise IdError(f"chunk range must ascend within one book: {raw!r}")
    return _anchored("chunk", raw, start, end=end)


def _digest(prefix: str) -> Callable[[str, str], ParsedId]:
    def handler(raw: str, rest: str) -> ParsedId:
        if len(rest) != _DIGEST_LEN[prefix] or not _HEX_RE.fullmatch(rest):
            raise IdError(f"{prefix}: needs {_DIGEST_LEN[prefix]} lowercase hex digits: {raw!r}")
        return ParsedId(_DIGEST_KIND[prefix], raw, digest=rest)
    return handler


_PREFIXED: dict[str, Callable[[str, str], ParsedId]] = {
    "sp": _chapter_text("superscription"),
    "dv": _chapter_text("division"),
    "hd": _numbered("heading", "key"),
    "pr": _numbered("parallel_ref", "heading"),
    "fn": _numbered("footnote", "unit"),
    "sk": _numbered("speaker", "unit"),
    "ns": _parse_name_span,
    "mg": _parse_merge_group,
    "pc": _keyed("pericope", "key"),
    "ps": _keyed("passage", "key"),
    "ck": _parse_chunk,
    "vs": _keyed("verse_record", "unit"),
    **{prefix: _digest(prefix) for prefix in _DIGEST_LEN},
}


def parse(raw: object) -> ParsedId:
    """Parse any id; raise IdError when it does not follow the grammar."""
    if not isinstance(raw, str) or not raw or not raw.isascii():
        raise IdError(f"id must be a non-empty ASCII string: {raw!r}")
    if any(ch.isspace() for ch in raw):
        raise IdError(f"id must not contain whitespace: {raw!r}")
    prefix, sep, rest = raw.partition(":")
    if sep:
        handler = _PREFIXED.get(prefix)
        if handler is None:
            raise IdError(f"unknown id prefix {prefix!r}: {raw!r}")
        return handler(raw, rest)
    for parser in _UNPREFIXED:
        parsed = parser(raw)
        if parsed is not None:
            return parsed
    raise IdError(f"not a valid id: {raw!r}")


def _matches(parsed: ParsedId, kind: str) -> bool:
    return parsed.kind in ROLES.get(kind, frozenset({kind}))


def _check_kind(kind: str | None) -> None:
    if kind is not None and kind not in KINDS:
        raise IdError(f"unknown kind {kind!r}")


def validate(raw: object, kind: str | None = None) -> ParsedId:
    """Parse ``raw`` and, when ``kind`` is given, require that kind (or role)."""
    _check_kind(kind)
    parsed = parse(raw)
    if kind is not None and not _matches(parsed, kind):
        raise IdError(f"expected {kind}, got {parsed.kind}: {raw!r}")
    return parsed


def is_valid(raw: object, kind: str | None = None) -> bool:
    _check_kind(kind)
    try:
        validate(raw, kind)
    except IdError:
        return False
    return True


# ---------------------------------------------------------------- building


def _int(value: object, name: str, minimum: int = 1, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IdError(f"{name} must be an int, got {value!r}")
    if value < minimum or (maximum is not None and value > maximum):
        raise IdError(f"{name} out of range: {value}")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdError(f"{name} must be a non-empty string")
    if any(ch.isspace() for ch in value):
        raise IdError(f"{name} must not contain whitespace: {value!r}")
    if unicodedata.normalize("NFC", value) != value:
        raise IdError(f"{name} must be NFC: {value!r}")
    return value


def _hex_prefix(value: object, name: str, length: int) -> str:
    if not isinstance(value, str) or len(value) < length or not _HEX_RE.fullmatch(value):
        raise IdError(f"{name} must be >= {length} lowercase hex digits: {value!r}")
    return value[:length]


def _sha1(*parts: str) -> str:
    payload = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _built(text: str, kind: str) -> str:
    validate(text, kind)
    return text


def chapter_key(book_id: str, chapter: int) -> str:
    return _built(f"{book_id}.{_int(chapter, 'chapter')}", "chapter")


def slot_key(book_id: str, chapter: int, verse: int) -> str:
    return _built(f"{book_id}.{_int(chapter, 'chapter')}.{_int(verse, 'verse')}", "slot")


def unit_key(book_id: str, chapter: int, v_start: int, v_end: int | None = None) -> str:
    base = slot_key(book_id, chapter, v_start)
    if v_end is None or v_end == v_start:
        return base
    return _built(f"{base}-{_int(v_end, 'v_end')}", "unit")


def verse_key(book_id: str, chapter: int, verse: int, half: bool = False) -> str:
    base = slot_key(book_id, chapter, verse)
    return _built(base + "b", "key") if half else base


def superscription_id(chapter_key_: str) -> str:
    return _built(f"sp:{chapter_key_}", "superscription")


def division_id(chapter_key_: str) -> str:
    return _built(f"dv:{chapter_key_}", "division")


def heading_id(start_key: str, n: int) -> str:
    return _built(f"hd:{start_key}#{_int(n, 'n')}", "heading")


def parallel_ref_id(heading_id_: str, k: int) -> str:
    return _built(f"pr:{heading_id_}#{_int(k, 'k')}", "parallel_ref")


def footnote_id(unit_key_: str, n: int) -> str:
    return _built(f"fn:{unit_key_}#{_int(n, 'n')}", "footnote")


def speaker_id(unit_key_: str, n: int) -> str:
    return _built(f"sk:{unit_key_}#{_int(n, 'n')}", "speaker")


def name_span_id(container_id: str, start: int) -> str:
    return _built(f"ns:{container_id}@{_int(start, 'start', minimum=0)}", "name_span")


def merge_group_id(surface: str, n: int) -> str:
    encoded = quote(_text(surface, "surface"), safe="")
    return _built(f"mg:{encoded}#{_int(n, 'n')}", "merge_group")


def pericope_id(start_key: str) -> str:
    return _built(f"pc:{start_key}", "pericope")


def passage_id(start_key: str) -> str:
    return _built(f"ps:{start_key}", "passage")


def chunk_id(start_key: str, end_key: str) -> str:
    return _built(f"ck:{start_key}~{end_key}", "chunk")


def verse_record_id(unit_key_: str) -> str:
    return _built(f"vs:{unit_key_}", "verse_record")


def point_id(record_id: str) -> str:
    """Qdrant point id: uuid5(NS_RAG, record_id)."""
    validate(record_id)
    return str(uuid.uuid5(NS_RAG, record_id))


def name_id(norm_key: str) -> str:
    _text(norm_key, "norm_key")
    return "nm:" + hashlib.sha1(norm_key.encode("utf-8")).hexdigest()[:12]


def mention_key(container_id: str, surface: str, k: int) -> str:
    container = validate(container_id)
    if container.kind not in CONTAINER_KINDS:
        raise IdError(f"{container.kind} cannot contain mentions: {container_id!r}")
    if "/" in _text(surface, "surface"):
        raise IdError(f"surface must not contain '/': {surface!r}")
    return f"{container_id}/{surface}/{_int(k, 'k')}"


def parse_mention_key(key: str) -> tuple[str, str, int]:
    parts = key.split("/") if isinstance(key, str) else []
    if len(parts) != 3 or not parts[2].isdigit():
        raise IdError(f"mention key must be container/surface/k: {key!r}")
    container, surface, k = parts[0], parts[1], int(parts[2])
    if mention_key(container, surface, k) != key:
        raise IdError(f"non-canonical mention key {key!r}")
    return container, surface, k


def mention_id(mention_key_: str) -> str:
    parse_mention_key(mention_key_)
    return "mn:" + hashlib.sha1(mention_key_.encode("utf-8")).hexdigest()[:16]


def entity_id(n: int) -> str:
    return f"e{_int(n, 'entity number', maximum=999_999):06d}"


def event_id(n: int) -> str:
    return f"ev{_int(n, 'event number', maximum=9_999):04d}"


def relation_id(rel_type: str, head: str, tail: str, evidence_unit: str, pattern: str) -> str:
    if rel_type not in RELATION_TYPES:
        raise IdError(f"unknown relation type {rel_type!r}")
    validate(head, "entity")
    validate(tail, "entity")
    validate(evidence_unit, "unit")
    _text(pattern, "pattern")
    if head == tail or (rel_type == "SPOUSE_OF" and head > tail):
        raise IdError(f"{rel_type} ends must differ (and be sorted when undirected)")
    return "rl:" + _sha1(rel_type, head, tail, evidence_unit, pattern)[:16]


def decision_id(scope: str, key: str, label: str, decided_by: str, ts: str) -> str:
    parts = (scope, key, label, decided_by, ts)
    for name, value in zip(("scope", "key", "label", "decided_by", "ts"), parts):
        _text(value, name)
    return "dc:" + _sha1(*parts)[:16]


def layer_version(layer: str, digest: str) -> str:
    if layer not in LAYERS:
        raise IdError(f"unknown layer {layer!r}")
    return _built(f"{layer}@{_hex_prefix(digest, 'digest', 12)}", "layer_version")


def build_id(date: _dt.date | str, release_sha: str) -> str:
    text = date.strftime("%Y%m%d") if isinstance(date, _dt.date) else date
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]{8}", text):
        raise IdError(f"date must be YYYYMMDD: {date!r}")
    return _built(f"b{_date8(text)}_{_hex_prefix(release_sha, 'release_sha', 8)}", "build")

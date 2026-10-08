"""Table-driven tests for the id grammar (design §3.1)."""

import hashlib
import json
import uuid

import pytest

from ragcommon import ids
from ragcommon.ids import IdError

# (id, kind, expected attributes)
VALID = [
    ("gen", "book", {"book_id": "gen"}),
    ("1sa", "book", {"book_id": "1sa"}),
    ("3jn", "book", {"book_id": "3jn"}),
    ("rev", "book", {"book_id": "rev"}),
    ("psa.3", "chapter", {"book_id": "psa", "chapter": 3}),
    ("psa.150", "chapter", {"book_id": "psa", "chapter": 150}),
    ("gen.1", "chapter", {"book_id": "gen", "chapter": 1}),
    ("jud.1", "chapter", {"book_id": "jud", "chapter": 1}),
    ("act.8.37", "slot", {"book_id": "act", "chapter": 8, "verse": 37, "verse_end": None}),
    ("jhn.3.16", "slot", {"book_id": "jhn", "chapter": 3, "verse": 16}),
    ("psa.119.176", "slot", {"chapter": 119, "verse": 176}),
    ("mat.18.11", "slot", {"verse": 11, "half": False}),
    ("2ki.25.30", "slot", {"book_id": "2ki"}),
    ("eph.6.2-3", "unit", {"book_id": "eph", "chapter": 6, "verse": 2, "verse_end": 3}),
    ("est.8.11-12", "unit", {"verse": 11, "verse_end": 12}),
    ("ezk.39.26-27", "unit", {"chapter": 39}),
    ("act.1.24-25", "unit", {"book_id": "act"}),
    ("isa.4.3-4", "unit", {"verse_end": 4}),
    ("act.9.19b", "key", {"book_id": "act", "chapter": 9, "verse": 19, "half": True}),
    ("1sa.10.1b", "key", {"half": True}),
    ("sp:psa.3", "superscription", {"book_id": "psa", "chapter": 3}),
    ("sp:psa.150", "superscription", {"chapter": 150}),
    ("dv:psa.42", "division", {"book_id": "psa", "chapter": 42}),
    ("dv:psa.107", "division", {"chapter": 107}),
    ("hd:ezk.1.1#2", "heading", {"book_id": "ezk", "chapter": 1, "verse": 1, "seq": 2, "half": False}),
    ("hd:act.9.19b#1", "heading", {"verse": 19, "half": True, "seq": 1}),
    ("hd:amo.1.3#1", "heading", {"seq": 1}),
    ("hd:mrk.6.30#12", "heading", {"seq": 12}),
    ("pr:hd:mrk.6.30#1#1", "parallel_ref", {"book_id": "mrk", "chapter": 6, "verse": 30, "seq": 1}),
    ("pr:hd:ezk.1.1#1#3", "parallel_ref", {"seq": 3}),
    ("pr:hd:act.9.19b#1#2", "parallel_ref", {"half": True, "seq": 2}),
    ("fn:mat.18.10#1", "footnote", {"book_id": "mat", "chapter": 18, "verse": 10, "seq": 1}),
    ("fn:eph.6.2-3#2", "footnote", {"verse": 2, "verse_end": 3, "seq": 2}),
    ("fn:ezk.1.1#10", "footnote", {"seq": 10}),
    ("sk:sng.1.2#1", "speaker", {"book_id": "sng", "chapter": 1, "verse": 2, "seq": 1}),
    ("sk:sng.8.14#2", "speaker", {"seq": 2}),
    ("ns:act.9.19@8", "name_span", {"book_id": "act", "chapter": 9, "verse": 19, "offset": 8}),
    ("ns:act.9.19@0", "name_span", {"offset": 0}),
    ("ns:eph.6.2-3@14", "name_span", {"verse_end": 3, "offset": 14}),
    ("ns:sp:psa.3@0", "name_span", {"book_id": "psa", "chapter": 3, "offset": 0}),
    ("ns:dv:psa.42@3", "name_span", {"chapter": 42}),
    ("ns:hd:act.9.19b#1@2", "name_span", {"half": True, "offset": 2}),
    ("ns:fn:mat.18.10#1@5", "name_span", {"verse": 10, "offset": 5}),
    ("ns:sk:sng.1.2#1@1", "name_span", {"offset": 1}),
    ("mg:%E9%B9%BD%E6%B5%B7#1", "merge_group", {"text": "鹽海", "seq": 1}),
    ("mg:%E4%BD%95%E7%83%88%E5%B1%B1#2", "merge_group", {"text": "何烈山", "seq": 2}),
    ("pc:1sa.9.25", "pericope", {"book_id": "1sa", "chapter": 9, "verse": 25, "half": False}),
    ("pc:act.9.19b", "pericope", {"half": True}),
    ("pc:gen.1.1", "pericope", {"verse": 1}),
    ("ps:1sa.10.1", "passage", {"book_id": "1sa", "chapter": 10, "verse": 1}),
    ("ps:act.9.19b", "passage", {"half": True}),
    ("ps:psa.119.1", "passage", {"chapter": 119}),
    ("ck:act.9.19b~act.9.25", "chunk", {"book_id": "act", "chapter": 9, "verse": 19, "half": True}),
    ("ck:psa.119.1~psa.119.40", "chunk", {"verse": 1}),
    ("ck:gen.1.1~gen.1.1", "chunk", {"verse": 1}),
    ("ck:act.9.1~act.9.19", "chunk", {"half": False}),
    ("vs:act.9.19", "verse_record", {"book_id": "act", "chapter": 9, "verse": 19}),
    ("vs:eph.6.2-3", "verse_record", {"verse": 2, "verse_end": 3}),
    ("vs:psa.3.1", "verse_record", {"book_id": "psa"}),
    ("vr:mat.18.3~mat.18.4", "verse_range", {"book_id": "mat", "chapter": 18, "verse": 3}),
    ("vr:gen.1.30~gen.1.31", "verse_range", {"verse": 30, "half": False}),
    ("vr:mat.18.3~mat.18.3", "verse_range", {"verse": 3}),
    ("vr:gen.1.31~gen.2.3", "verse_range", {"chapter": 1, "verse": 31}),
    ("nm:c21faeeef08a", "name", {"digest": "c21faeeef08a"}),
    ("nm:000000000000", "name", {"digest": "000000000000"}),
    ("mn:0123456789abcdef", "mention", {"digest": "0123456789abcdef"}),
    ("mn:ffffffffffffffff", "mention", {"digest": "ffffffffffffffff"}),
    ("e000231", "entity", {"seq": 231}),
    ("e000001", "entity", {"seq": 1}),
    ("e999999", "entity", {"seq": 999999}),
    ("ev0015", "event", {"seq": 15}),
    ("ev0001", "event", {"seq": 1}),
    ("ev9999", "event", {"seq": 9999}),
    ("rl:0123456789abcdef", "relation", {"digest": "0123456789abcdef"}),
    ("dc:fedcba9876543210", "decision", {"digest": "fedcba9876543210"}),
    ("text@0123456789ab", "layer_version", {"text": "text", "digest": "0123456789ab"}),
    ("src@aaaaaaaaaaaa", "layer_version", {"text": "src"}),
    ("kg0@0123456789ab", "layer_version", {"text": "kg0"}),
    ("relations@0123456789ab", "layer_version", {"text": "relations"}),
    ("b20261102_9c1e0a7d", "build", {"date": "20261102", "digest": "9c1e0a7d"}),
    ("b20240229_00000000", "build", {"date": "20240229"}),
    ("legacy-20261004", "build", {"date": "20261004", "digest": None, "text": "legacy"}),
]

INVALID = [
    "", " ", "gen ", " gen", "GEN", "xyz", "ge", "gens", "1SA", "創世記",
    "gen.0", "gen.01", "gen.", "gen.-1", "gen.1.", "gen..1", "xyz.1", "gen.a",
    "gen.1.0", "gen.1.01", "gen.1.1a", "gen.1.1B", "gen.1.1bb", "gen.1.1c",
    "eph.6.3-2", "eph.6.2-2", "eph.6.2-", "eph.6.-3", "eph.6.2-3b", "eph.6.2-03",
    "eph.6.2–3", "jhn.3.16 ", "jhn 3 16", "jhn:3:16", "jhn.3.16.1",
    "sp:psa", "sp:psa.3.1", "sp:psa.0", "sp:xyz.3", "sp:", "dv:psa.42b", "dv:psa",
    "hd:ezk.1.1", "hd:ezk.1.1#0", "hd:ezk.1.1#", "hd:ezk.1.1#01", "hd:ezk.1#1",
    "hd:eph.6.2-3#1", "hd:ezk.1.1#1#2", "hd:#1",
    "pr:hd:mrk.6.30#1", "pr:hd:mrk.6.30#1#0", "pr:mrk.6.30#1#1", "pr:hd:mrk.6.30#1#",
    "fn:mat.18.10", "fn:mat.18.10#0", "fn:mat.18#1", "fn:act.9.19b#1", "fn:mat.18.10#a",
    "sk:sng.1.2", "sk:sng.1.2#-1", "sk:sng.1#1",
    "ns:act.9.19", "ns:act.9.19@", "ns:act.9.19@-1", "ns:act.9.19@01", "ns:act.9@8",
    "ns:pc:act.9.19@8", "ns:vs:act.9.19@8", "ns:act.9.19b@8", "ns:@8", "ns:xyz.1.1@0",
    "mg:鹽海#1", "mg:#1", "mg:%E9%B9%BD", "mg:%e9%b9%bd#1", "mg:%E9%B9%BD#0", "mg:%ZZ#1",
    "mg:%E9%B9#1", "mg:%41#1",
    "pc:1sa.9", "pc:eph.6.2-3", "pc:1sa.9.25#1", "pc:1sa.9.0", "pc:",
    "ps:1sa.10", "ps:eph.6.2-3", "ps:1sa.10.1c",
    "ck:act.9.19b", "ck:act.9.25~act.9.19b", "ck:act.9.19~mat.9.25", "ck:act.9.19~",
    "ck:act.9.19b~act.9.19", "ck:eph.6.2-3~eph.6.9", "ck:act.10.1~act.9.30",
    "vs:act.9.19b", "vs:act.9", "vs:", "vs:act.9.19#1",
    "vr:mat.18.3", "vr:mat.18.4~mat.18.3", "vr:mat.18.3~mrk.18.4", "vr:eph.6.2-3~eph.6.4",
    "vr:act.9.19b~act.9.20", "vr:act.9.19~act.9.19b", "vr:mat.18.3~", "vr:", "vr:gen.2.1~gen.1.31",
    "vr:mat.18.3~mat.18.4~mat.18.5",
    "nm:c21faeeef08", "nm:c21faeeef08aa", "nm:C21FAEEEF08A", "nm:g21faeeef08a",
    "mn:0123456789abcde", "mn:0123456789ABCDEF", "mn:act.9.19/掃羅/1",
    "e00231", "e0002310", "e000000", "E000231", "e00023a", "ev015", "ev00015", "ev0000",
    "rl:0123", "rl:0123456789abcdeg", "dc:0123456789abcdef0", "dc:",
    "text@0123456789a", "text@0123456789abc", "text@0123456789AB", "foo@0123456789ab",
    "TEXT@0123456789ab", "@0123456789ab",
    "b20261302_9c1e0a7d", "b20260230_9c1e0a7d", "b2026110_9c1e0a7d", "b20261102_9c1e0a7",
    "b20261102_9C1E0A7D", "b20261102-9c1e0a7d", "legacy-2026100", "legacy-20261332",
    "legacy_20261004", "zz:gen.1.1", "gen.1.1\n", "gen\t", 3, None, b"gen",
]

ROLE_CASES = [
    ("jhn.3.16", "slot", True), ("jhn.3.16", "unit", True), ("jhn.3.16", "key", True),
    ("eph.6.2-3", "slot", False), ("eph.6.2-3", "unit", True), ("eph.6.2-3", "key", False),
    ("act.9.19b", "slot", False), ("act.9.19b", "unit", False), ("act.9.19b", "key", True),
    ("psa.3", "chapter", True), ("psa.3", "slot", False), ("gen", "book", True),
    ("vs:act.9.19", "verse_record", True), ("vs:act.9.19", "passage", False),
    ("vr:act.9.1~act.9.2", "verse_range", True), ("vr:act.9.1~act.9.2", "chunk", False),
    ("ps:act.9.19b", "passage", True), ("pc:act.9.19b", "passage", False),
    ("e000231", "entity", True), ("ev0015", "entity", False),
    ("legacy-20261004", "build", True), ("text@0123456789ab", "build", False),
]


@pytest.mark.parametrize("raw, kind, attrs", VALID)
def test_parse_valid_ids(raw, kind, attrs):
    parsed = ids.parse(raw)
    assert parsed.kind == kind
    assert parsed.raw == raw
    for name, value in attrs.items():
        assert getattr(parsed, name) == value, name
    ids.validate(raw)
    assert ids.is_valid(raw)
    assert ids.is_valid(raw, kind)


@pytest.mark.parametrize("raw", INVALID)
def test_parse_rejects_invalid_ids(raw):
    with pytest.raises(IdError):
        ids.parse(raw)
    assert not ids.is_valid(raw)


@pytest.mark.parametrize("raw, role, ok", ROLE_CASES)
def test_validate_checks_role(raw, role, ok):
    assert ids.is_valid(raw, role) is ok
    if not ok:
        with pytest.raises(IdError):
            ids.validate(raw, role)


def test_validate_rejects_unknown_role():
    with pytest.raises(IdError, match="unknown kind"):
        ids.validate("gen", "planet")


def test_nested_parents_are_parsed():
    pr = ids.parse("pr:hd:act.9.19b#1#2")
    assert pr.parent.kind == "heading"
    assert pr.parent.parent.kind == "key"
    ns = ids.parse("ns:fn:eph.6.2-3#1@4")
    assert ns.parent.kind == "footnote"
    assert ns.parent.parent.kind == "unit"
    ck = ids.parse("ck:act.9.19b~act.9.25")
    assert (ck.parent.raw, ck.end.raw) == ("act.9.19b", "act.9.25")
    vr = ids.parse("vr:gen.1.30~gen.2.3")
    assert (vr.parent.kind, vr.parent.raw, vr.end.raw) == ("slot", "gen.1.30", "gen.2.3")


BUILDERS = [
    (lambda: ids.chapter_key("psa", 3), "psa.3"),
    (lambda: ids.slot_key("act", 8, 37), "act.8.37"),
    (lambda: ids.unit_key("jhn", 3, 16), "jhn.3.16"),
    (lambda: ids.unit_key("jhn", 3, 16, 16), "jhn.3.16"),
    (lambda: ids.unit_key("eph", 6, 2, 3), "eph.6.2-3"),
    (lambda: ids.verse_key("act", 9, 19), "act.9.19"),
    (lambda: ids.verse_key("act", 9, 19, half=True), "act.9.19b"),
    (lambda: ids.superscription_id("psa.3"), "sp:psa.3"),
    (lambda: ids.division_id("psa.42"), "dv:psa.42"),
    (lambda: ids.heading_id("ezk.1.1", 2), "hd:ezk.1.1#2"),
    (lambda: ids.heading_id("act.9.19b", 1), "hd:act.9.19b#1"),
    (lambda: ids.parallel_ref_id("hd:mrk.6.30#1", 1), "pr:hd:mrk.6.30#1#1"),
    (lambda: ids.footnote_id("mat.18.10", 1), "fn:mat.18.10#1"),
    (lambda: ids.footnote_id("eph.6.2-3", 1), "fn:eph.6.2-3#1"),
    (lambda: ids.speaker_id("sng.1.2", 1), "sk:sng.1.2#1"),
    (lambda: ids.name_span_id("act.9.19", 8), "ns:act.9.19@8"),
    (lambda: ids.name_span_id("sp:psa.3", 0), "ns:sp:psa.3@0"),
    (lambda: ids.merge_group_id("鹽海", 1), "mg:%E9%B9%BD%E6%B5%B7#1"),
    (lambda: ids.pericope_id("1sa.9.25"), "pc:1sa.9.25"),
    (lambda: ids.passage_id("act.9.19b"), "ps:act.9.19b"),
    (lambda: ids.chunk_id("act.9.19b", "act.9.25"), "ck:act.9.19b~act.9.25"),
    (lambda: ids.verse_record_id("eph.6.2-3"), "vs:eph.6.2-3"),
    (lambda: ids.verse_range_id("mat.18.3", "mat.18.4"), "vr:mat.18.3~mat.18.4"),
    (lambda: ids.verse_range_id("mat.18.3", "mat.18.3"), "vr:mat.18.3~mat.18.3"),
    (lambda: ids.entity_id(231), "e000231"),
    (lambda: ids.event_id(15), "ev0015"),
    (lambda: ids.layer_version("text", "0123456789abcdef" * 4), "text@0123456789ab"),
    (lambda: ids.build_id("20261102", "9c1e0a7d" + "0" * 32), "b20261102_9c1e0a7d"),
    (lambda: ids.mention_key("act.9.19", "掃羅", 1), "act.9.19/掃羅/1"),
    (lambda: ids.mention_key("sp:psa.3", "大衛", 2), "sp:psa.3/大衛/2"),
]


@pytest.mark.parametrize("build, expected", BUILDERS)
def test_builders_produce_grammar(build, expected):
    assert build() == expected
    if "/" not in expected:  # mention keys are keys, not ids
        assert ids.parse(expected).raw == expected


BAD_BUILDS = [
    lambda: ids.chapter_key("xyz", 1),
    lambda: ids.chapter_key("gen", 0),
    lambda: ids.chapter_key("gen", True),
    lambda: ids.chapter_key("gen", "1"),
    lambda: ids.slot_key("gen", 1, 0),
    lambda: ids.unit_key("eph", 6, 3, 2),
    lambda: ids.verse_key("gen", 1, -1),
    lambda: ids.superscription_id("psa.3.1"),
    lambda: ids.heading_id("eph.6.2-3", 1),
    lambda: ids.heading_id("ezk.1.1", 0),
    lambda: ids.parallel_ref_id("mrk.6.30", 1),
    lambda: ids.footnote_id("act.9.19b", 1),
    lambda: ids.speaker_id("sng.1", 1),
    lambda: ids.name_span_id("pc:act.9.19", 0),
    lambda: ids.name_span_id("act.9.19", -1),
    lambda: ids.merge_group_id("", 1),
    lambda: ids.merge_group_id("鹽 海", 1),
    lambda: ids.merge_group_id("鹽海", 0),
    lambda: ids.pericope_id("eph.6.2-3"),
    lambda: ids.chunk_id("act.9.25", "act.9.19"),
    lambda: ids.verse_record_id("act.9.19b"),
    lambda: ids.verse_range_id("mat.18.4", "mat.18.3"),
    lambda: ids.verse_range_id("eph.6.2-3", "eph.6.4"),
    lambda: ids.verse_range_id("act.9.19b", "act.9.20"),
    lambda: ids.entity_id(0),
    lambda: ids.entity_id(1_000_000),
    lambda: ids.event_id(10_000),
    lambda: ids.layer_version("planet", "0" * 12),
    lambda: ids.layer_version("text", "0123"),
    lambda: ids.layer_version("text", "G" * 12),
    lambda: ids.build_id("20261332", "9" * 8),
    lambda: ids.build_id("20261102", "9c1e"),
    lambda: ids.build_id("2026-11-02", "9c1e0a7d"),
    lambda: ids.mention_key("act.9.19", "掃/羅", 1),
    lambda: ids.mention_key("act.9.19", "", 1),
    lambda: ids.mention_key("act.9.19", "掃羅", 0),
    lambda: ids.mention_key("act.9", "掃羅", 1),
    lambda: ids.name_id(""),
    lambda: ids.name_id(" 掃羅"),
    lambda: ids.name_id("é"),
    lambda: ids.point_id("not an id"),
]


@pytest.mark.parametrize("build", BAD_BUILDS)
def test_builders_reject_bad_input(build):
    with pytest.raises(IdError):
        build()


def _sha(*parts):
    payload = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def test_name_id_is_sha1_prefix_of_norm_key():
    assert ids.name_id("掃羅") == "nm:" + hashlib.sha1("掃羅".encode()).hexdigest()[:12]
    assert ids.name_id("掃羅") != ids.name_id("保羅")


def test_mention_id_is_sha1_prefix_of_mention_key():
    key = ids.mention_key("act.9.19", "掃羅", 1)
    assert ids.mention_id(key) == "mn:" + hashlib.sha1(key.encode()).hexdigest()[:16]
    with pytest.raises(IdError):
        ids.mention_id("act.9.19/掃羅/0")


def test_parse_mention_key_roundtrip():
    assert ids.parse_mention_key("hd:act.9.19b#1/掃羅/3") == ("hd:act.9.19b#1", "掃羅", 3)
    for bad in ("act.9.19/掃羅", "act.9.19/掃羅/01", "act.9.19/掃羅/x"):
        with pytest.raises(IdError):
            ids.parse_mention_key(bad)


def test_relation_id_hashes_fields():
    rid = ids.relation_id("PARENT_OF", "e000001", "e000002", "rut.4.18", "N1.begot")
    assert rid == "rl:" + _sha("PARENT_OF", "e000001", "e000002", "rut.4.18", "N1.begot")[:16]
    assert ids.parse(rid).kind == "relation"


@pytest.mark.parametrize(
    "args",
    [
        ("LOVES", "e000001", "e000002", "rut.4.18", "p"),
        ("PARENT_OF", "x", "e000002", "rut.4.18", "p"),
        ("PARENT_OF", "e000001", "e000002", "rut.4", "p"),
        ("PARENT_OF", "e000001", "e000002", "rut.4.18", ""),
        ("SPOUSE_OF", "e000009", "e000002", "rut.4.13", "p"),
    ],
)
def test_relation_id_rejects_bad_fields(args):
    with pytest.raises(IdError):
        ids.relation_id(*args)


def test_spouse_relation_requires_sorted_ends():
    rid = ids.relation_id("SPOUSE_OF", "e000002", "e000009", "rut.4.13", "p")
    assert rid.startswith("rl:")


def test_decision_id_hashes_fields():
    args = ("mention", "act.9.19/掃羅/1", "e000231", "kay", "2026-11-01T10:00:00+08:00")
    assert ids.decision_id(*args) == "dc:" + _sha(*args)[:16]
    with pytest.raises(IdError):
        ids.decision_id("mention", "", "e000231", "kay", "t")


def test_point_id_uses_fixed_namespace():
    assert ids.NS_RAG == uuid.UUID("ef6733ee-5a28-5e83-9074-de6e229eb380")
    assert ids.point_id("vs:eph.6.2-3") == "f2812762-c74d-5242-9f0d-ad51acd850a8"
    assert ids.point_id("ps:1sa.10.1") == "fabeb987-f45c-57de-adb6-77872fa63db0"


def test_build_id_accepts_date_object():
    import datetime

    assert ids.build_id(datetime.date(2026, 11, 2), "9c1e0a7d") == "b20261102_9c1e0a7d"
    assert ids.LEGACY_BUILD_ID == "legacy-20261004"
    assert ids.parse(ids.LEGACY_BUILD_ID).kind == "build"
